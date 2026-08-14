"""
שרת המעטפת של אן — FastAPI שמחבר את ממשק הצ'אט (web/) ל-pipeline הקיים.

עקרונות (בהתאם לכללי הפרויקט):
  * מעטפת בלבד — אפס נגיעה בלוגיקת הסוכנים/RAG: הקריאה היחידה פנימה היא
    ChatSession.run_turn, והתשובה נארזת כ-JSON לדפדפן.
  * המשכיות שיחה: הלקוח שולח user_id אנונימי (uuid שנוצר בדפדפן ונשמר
    ב-localStorage). השרת ממפה user_id -> ChatSession חי, כך שכל ההודעות
    של אותו דפדפן ממשיכות את אותה שיחה — ולכן גם נרשמות בלוג ה-SQLite
    תחת אותו session_id (שנטבע ב-ChatSession, ללא קשר לזהות המשתמש).
    ה-user_id עצמו לעולם לא נכתב ללוג — הפרטיות המבנית של storage/ נשמרת.
  * ה-import של crew/ עצל (בעת הקריאה הראשונה, עם חימום ברקע בעליית
    השרת) — כך השרת עולה מהר וקבצים סטטיים מוגשים גם בלי מפתח API.
  * אין כאן שום קריאת LLM יזומה: קריאה בתשלום מתבצעת אך ורק כשמשתמש
    שולח הודעה (POST /api/chat). /api/welcome מחזיר טקסט קבוע, חינם;
    כל נתיבי /api/admin/* חינמיים לחלוטין (קבצים ומצב תהליכים).
  * תצוגת מקורות: שורות "מקור: ..." מוסרות מגוף התשובה לפני השליחה
    לדפדפן (ראה _strip_source_lines) — ה-UI מציג את המקורות פעם אחת,
    מהשדה sources המאומת מול המאגר. אין כאן שינוי בלוגיקת הסוכנים.

אזור המנהל (/admin): בקרת גישה לאזור המנהל מבוססת משתמש מנהל יחיד,
שפרטיו נשמרים ב-.env מחוץ לבקרת גרסאות. זו החלטה מכוונת המתאימה להיקף
המערכת — משתמש אחד בפועל, ולכן אין צורך בשכבת ניהול משתמשים. הפרטים
נקראים **ממשתני הסביבה** ADMIN_EMAIL ו-ADMIN_PASSWORD (ראה .env.example).
**אין ברירת מחדל בקוד**: בלי שני המשתנים אין התחברות בכלל, אלא הודעה
מסודרת שאין פרטי כניסה.

הרצה (ידנית, לא מכאן):
    /Users/maordahan/anaconda3/envs/anne_env/bin/python3.12 -m uvicorn server.app:app --port 8000
ואז לפתוח http://localhost:8000 בדפדפן.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import queue
import re
import secrets
import socket
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NamedTuple
from urllib.parse import urljoin, urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# שכבת המסמכים של אזור המנהל (פרסור והכנה לתצוגה). stdlib + markdown
# בלבד — אין בה crew/rag/ml, ולכן הייבוא כאן זול ובטוח.
from server import documents

# טעינת .env בעליית השרת — משם מגיעים פרטי הכניסה לאזור המנהל (ומשם
# מגיע גם מפתח ה-LLM, ש-llm/config.py טוען בנפרד). load_dotenv אינו דורס
# משתני סביבה קיימים, ולכן הרצה עם משתנה מפורש בשורת הפקודה גוברת.
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"
ASSETS_DIR = PROJECT_ROOT / "assets"
ILLUSTRATIONS_DIR = PROJECT_ROOT / "illustrations"

# user_id אנונימי מהדפדפן: hex/uuid באורך סביר בלבד — שום טקסט חופשי.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# תקרת שיחות חיות בזיכרון: מעבר לה — השיחה הוותיקה ביותר (לפי פעילות)
# מפונה. משתמש שפונה יקבל שיחה חדשה (עם session_id חדש בלוג) — נסבל
# לפרויקט לימודי, ועדיף על צמיחת זיכרון בלתי חסומה.
_MAX_LIVE_SESSIONS = 100

# הודעת שגיאה קבועה כשתור נכשל טכנית ברמת השרת (רשת/ספק) — מקבילה
# ברוחה ל-FAILSAFE_REPLY_HE של ה-pipeline, בלי להמציא טיפול.
_SERVER_ERROR_REPLY_HE = (
    "סליחה, משהו השתבש אצלי בדרך ולא הצלחתי לטפל בהודעה. נסו שוב עוד רגע. "
    "ואם משהו מרגיש דחוף או מחמיר — אל תחכו לי: חייגו 101 או פנו לרופא/ה."
)


class _SessionEntry:
    """שיחה חיה אחת + מנעול פר-שיחה (run_turn אינו בטוח למקביליות באותה שיחה)."""

    def __init__(self, session, demo: bool = False) -> None:
        self.session = session
        self.lock = threading.Lock()
        self.demo = demo


# רישום השיחות החיות: user_id -> _SessionEntry, בסדר "נראה לאחרונה" (LRU).
_sessions: "OrderedDict[str, _SessionEntry]" = OrderedDict()
_sessions_lock = threading.Lock()


class ChatRequest(BaseModel):
    """
    גוף הבקשה מהדפדפן — מזהה אנונימי, הודעת המשתמש, ותמונה אופציונלית.

    התמונה מגיעה כ-base64 (data URL או גולמי) באותה בקשה של ההודעה, כדי
    שלא ייווצר "מצב תמונה" בשרת בין שתי קריאות. התקרה כאן היא הגנת קלט
    ראשונה בלבד — האימות האמיתי (סוג לפי תוכן, ממדים, EXIF) נעשה
    ב-vision/ingest.py. 9MB base64 ≈ 6.7MB בינארי, מעל מגבלת הקובץ שם.
    """

    user_id: str = Field(min_length=8, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    image_base64: str | None = Field(default=None, max_length=9_000_000)
    # תור של הרצת תרחיש הדגמה. משמעותו אחת: השיחה מבודדת — היא נפתחת
    # כ-ChatSession חדש שאינו נרשם בלוג, והמזהה שלה חד-פעמי (הדפדפן
    # טובע אותו להרצה ואינו שומר אותו). ראה web/demo.js.
    demo: bool = False


def _get_or_create_entry(user_id: str, demo: bool = False) -> _SessionEntry:
    """
    שליפת השיחה החיה של user_id, או פתיחת ChatSession חדש (import עצל).

    demo=True פותח שיחה מבודדת שאינה נרשמת בלוג. אם קיימת כבר שיחה
    לאותו מזהה במצב *אחר* — היא מוחלפת ולא ממוחזרת: מזהה שהתחיל כהדגמה
    לא יהפוך בשקט לשיחה שנרשמת (ולהפך). בפועל מזהה הדגמה הוא חד-פעמי
    ואקראי, וזו רשת ביטחון.
    """
    with _sessions_lock:
        entry = _sessions.get(user_id)
        if entry is not None and entry.demo == demo:
            _sessions.move_to_end(user_id)
            return entry

    # בניית session מחוץ למנעול הגלובלי — בנייה ראשונה עשויה לקחת שניות
    # (import של crewai + בניית סוכנים; ללא שום קריאת LLM בתשלום).
    from crew.pipeline import ChatSession

    session = ChatSession(verbose=False, log_turns=not demo)
    with _sessions_lock:
        # אם במקביל נבנה session לאותו משתמש — משתמשים בראשון שנרשם.
        entry = _sessions.get(user_id)
        if entry is None or entry.demo != demo:
            entry = _SessionEntry(session, demo=demo)
            _sessions[user_id] = entry
            while len(_sessions) > _MAX_LIVE_SESSIONS:
                _sessions.popitem(last=False)  # פינוי הוותיקה ביותר
        return entry


def _release_session(user_id: str) -> bool:
    """שחרור שיחה חיה מהזיכרון. מחזיר True אם הייתה כזו."""
    with _sessions_lock:
        return _sessions.pop(user_id, None) is not None


def _illustration_payload(record: dict | None) -> dict | None:
    """רשומת איור מהרשימה הסגורה -> מטען JSON לדפדפן (עם URL להגשה)."""
    if not record:
        return None
    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "steps": list(record.get("steps", [])),
        "image_url": f"/illustrations/{record.get('file', '')}",
    }


# ── תצוגת מקורות פעם אחת (שקף 15) ────────────────────────────────────────
# אן מסיימת את תשובתה בשורת "מקור: ..." (הנחיית הניסוח, crew/agents.py),
# וה-UI מציג ממילא את שורת המקורות מהשדה sources — המאומת מול המאגר
# (schemas.source_is_known). התוצאה בדפדפן הייתה מקור פעמיים: בתוך גוף
# ההודעה וגם למטה. כאן מוסרות שורות המקור מגוף הטקסט, כך שנשארת התצוגה
# התחתונה בלבד — זו שעברה סינון. שינוי תצוגה בלבד: ההנחיה לסוכנים,
# הייעוץ והשקיפות עצמם לא נגעו.
_SOURCE_LINE_RE = re.compile(
    r"^\s*(?:[-–—•*·]+\s*)?(?:\*\*|__)?\s*מקור(?:ות)?\s*(?:\*\*|__)?\s*:"
)


def _strip_source_lines(text: str) -> str:
    """הסרת שורות 'מקור:' / 'מקורות:' מגוף התשובה (כולל תבליט/הדגשה)."""
    kept = [
        line for line in (text or "").splitlines()
        if not _SOURCE_LINE_RE.match(line)
    ]
    # איחוד רווח אנכי שנפער במקום השורה שהוסרה.
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


# תבליטים/סימוני הדגשה שיכולים להקדים שורת מקור בתחילת שורה.
_LINE_MARKERS = " \t-–—•*·_>"


def _source_line_possible(line: str) -> bool:
    """
    האם השורה החלקית הזו עדיין עלולה להיות שורת מקור (או שהיא כבר כזו).

    נחוץ להזרמה: מקטע נשלח לדפדפן ברגע שהוא מגיע, ולכן צריך להחזיק מעט
    טקסט כל עוד ייתכן שהשורה שמצטברת היא שורת "מקור:" שממילא לא תוצג.
    ההחזקה קצרה מאוד — "מקור" הוא ארבע אותיות.
    """
    if _SOURCE_LINE_RE.match(line):
        return True
    head = line.lstrip(_LINE_MARKERS)
    if not head:
        return True  # רק תבליט/רווח עד כה — עדיין ייתכן
    return any(word.startswith(head) for word in ("מקור:", "מקורות:"))


class _StreamSourceFilter:
    """
    מסנן זורם שמשמיט שורות מקור מתוך זרם הניסוח, שורה-שורה.

    למה: אן מסיימת את תשובתה בשורת "מקור: ...", וה-UI מציג את המקורות
    בנפרד (המסוננים מול המאגר). בלי המסנן הזה שורת המקור הייתה מהבהבת
    בזרם ואז נעלמת כשהתשובה הסופית מחליפה אותה. שאר הטקסט זורם מיד.
    """

    def __init__(self) -> None:
        self._line = ""      # השורה המצטברת כרגע
        self._emitted = 0    # כמה תווים מהשורה הזו כבר נשלחו

    def feed(self, chunk: str) -> str:
        """מקטע נכנס -> הטקסט שמותר לשלוח עכשיו (ייתכן ריק)."""
        out: list[str] = []
        for part in re.split(r"(\n)", chunk or ""):
            if part == "\n":
                if not _SOURCE_LINE_RE.match(self._line):
                    out.append(self._line[self._emitted:] + "\n")
                self._line = ""
                self._emitted = 0
            elif part:
                self._line += part
                if not _source_line_possible(self._line):
                    out.append(self._line[self._emitted:])
                    self._emitted = len(self._line)
        return "".join(out)

    def flush(self) -> str:
        """סיום הזרם — שארית השורה האחרונה, אם אינה שורת מקור."""
        tail = "" if _SOURCE_LINE_RE.match(self._line) else self._line[self._emitted:]
        self._line = ""
        self._emitted = 0
        return tail


app = FastAPI(title="אן — אחות דיגיטלית", docs_url=None, redoc_url=None)


@app.on_event("startup")
def _warm_start() -> None:
    """
    חימום ברקע כדי שההודעה הראשונה לא תשלם את מחיר הטעינות הכבדות:
    (1) import של crew (crewai + הסוכנים), (2) טעינת מודל ה-embedding
    ולקוח Chroma (~2GB) דרך crew.tools.warm_up_rag — אותו חימום שרץ
    ממילא בבניית ChatSession, רק מוקדם יותר (נמדד: התור הראשון בתהליך
    שילם ~25-35 שניות נוספות בשלב הייעוץ בגלל טעינת ה-embedder).

    best-effort בלבד — כשל (למשל מפתח API חסר) לא מפיל את השרת: הקבצים
    הסטטיים מוגשים כרגיל והשגיאה תדווח בעברית בקריאת הצ'אט הראשונה.
    אין כאן שום קריאת LLM בתשלום.
    """

    def _warm() -> None:
        try:
            import crew.pipeline  # noqa: F401
        except Exception:
            return
        try:
            from crew.tools import warm_up_rag

            warm_up_rag()
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True).start()


@app.get("/api/health")
def health() -> dict:
    """בדיקת חיים + האם מפתח ה-API מוגדר (בלי לחשוף אותו, כמובן)."""
    from dotenv import load_dotenv

    load_dotenv()
    provider = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()
    var = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(
        provider, "OPENAI_API_KEY"
    )
    return {"ok": True, "api_key_configured": bool(os.getenv(var))}


@app.get("/api/welcome")
def welcome() -> dict:
    """הודעת הפתיחה הקבועה של אן — חינם, בלי LLM ובלי פתיחת שיחה."""
    from crew.pipeline import WELCOME_HE

    return {"reply_he": WELCOME_HE}


@app.get("/api/demo/scenarios")
def demo_scenarios() -> dict:
    """
    תרחישי ההדגמה מ-docs/demo_scenarios.json — חינם, בלי LLM.

    הנתיב הזה **אינו** מאחורי בקרת הגישה של אזור המנהל בכוונה: המריץ רץ
    בדף הצ'אט (/), שאין לו טוקן מנהל, ואילו התוכן הוא טקסט הדגמה בלבד —
    אותן הודעות שכל מבקר יכול להקליד בעצמו. אזור המנהל ממילא אינו מגן על
    נתון רגיש (ראה ההערה למעלה).

    הקריאה קוראת את הקובץ בכל בקשה — עריכה בתרחישים משתקפת מיד, בלי
    הפעלה מחדש של השרת. קובץ חסר/פגום מוחזר כ-available=false עם הודעה.
    """
    return documents.load_demo_scenarios()


def _image_payload(analysis) -> dict | None:
    """
    מה שהדפדפן מקבל על התמונה — שקיפות למשתמש ולכרטיס סיכום ההדגמה.
    התמונה עצמה אינה חוזרת (היא ממילא אצל הדפדפן) ואינה נשמרת בשרת.
    """
    if analysis is None:
        return None
    payload = analysis.as_dict()
    return {
        "analyzed": True,
        "quality_he": (payload.get("quality") or {}).get("summary_he", ""),
        "features_he": (analysis.features.summary_he()
                        if analysis.features else ""),
        "description_he": payload.get("description_he"),
        "description_error_he": payload.get("description_error_he"),
        "outside_scope": payload.get("outside_scope", False),
        "measurements": payload.get("features"),
        "quality": payload.get("quality"),
    }


def _turn_payload(result, image=None) -> dict:
    """
    TurnResult -> מטען ה-JSON לדפדפן (זהה בשני נתיבי הצ'אט).

    tool_usage ו-llm_calls נשלחים לתצוגה בלבד — הם מה שכרטיס הסיכום של
    מריץ התרחישים מדווח עליו ("אילו כלים הופעלו", כמה קריאות עלה התור).
    שניהם כבר קיימים ב-TurnResult; אין כאן שום חישוב חדש ושום שינוי
    בהתנהגות התור. מוצגים רק כלים שהופעלו בפועל (ערך > 0).
    """
    return {
        # שורות המקור מוסרות מהגוף — המקור מוצג פעם אחת, מ-sources.
        "reply_he": _strip_source_lines(result.reply_he),
        "emergency": result.emergency,
        "red_flags": list(result.red_flags),
        "topic": result.topic,
        "illustration": _illustration_payload(result.illustration),
        "sources": list(result.sources),
        "consulted": result.consulted,
        "tool_usage": {
            name: count
            for name, count in (getattr(result, "tool_usage", None) or {}).items()
            if count
        },
        "llm_calls": int(getattr(result, "llm_calls", 0) or 0),
        "image": _image_payload(image),
        "error": False,
    }


def _error_payload() -> dict:
    """מטען תשובת השגיאה הקבועה — בלי להמציא טיפול."""
    return {
        "reply_he": _SERVER_ERROR_REPLY_HE,
        "emergency": False,
        "red_flags": [],
        "topic": None,
        "illustration": None,
        "sources": [],
        "consulted": False,
        "tool_usage": {},
        "llm_calls": 0,
        "image": None,
        "error": True,
    }


# ── תמונה שצורפה להודעה (שכבת הראייה) ────────────────────────────────────
# הזרימה: base64 -> בייטים -> vision.analyze_image (אבטחה, איכות, מדידות,
# תיאור) -> בלוק הקשר בעברית שמוזרק לפרומפטים של הסוכנים.
#
# פרטיות: הבייטים חיים בזיכרון הבקשה בלבד. שום קובץ לא נכתב לדיסק, ה-EXIF
# (GPS ודגם מכשיר) מוסר לפני כל עיבוד, ולוג השיחות אינו מקבל מהתמונה שום
# נתון — סכמת הלוג לא השתנתה בכלל בעקבות השכבה הזו.
_DATA_URL_RE = re.compile(r"^data:image/[a-zA-Z.+-]+;base64,")


def _decode_image(raw: str | None) -> bytes | None:
    """base64 (עם/בלי קידומת data URL) -> בייטים. קלט פסול -> 400."""
    if not raw:
        return None
    payload = _DATA_URL_RE.sub("", raw.strip())
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="קידוד התמונה אינו תקין.")
    if not data:
        raise HTTPException(status_code=400, detail="התמונה שהתקבלה ריקה.")
    return data


def _analyze_attachment(raw: str | None) -> "object | None":
    """
    ניתוח התמונה המצורפת, או None כשאין. ייבוא עצל של vision/ — השרת
    עולה ומגיש גם בסביבה בלי Pillow/numpy, וכל תקלה בשכבת הראייה מוחזרת
    כשגיאת קלט מסודרת ולא כ-500.
    """
    data = _decode_image(raw)
    if data is None:
        return None
    try:
        from vision import analyze_image
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="שכבת ניתוח התמונות אינה זמינה בשרת הזה.",
        )
    analysis = analyze_image(data)
    if not analysis.ok:
        raise HTTPException(status_code=400,
                            detail=analysis.error_he or "התמונה נדחתה.")
    return analysis


def _image_context(analysis) -> str | None:
    """בלוק ההקשר שמוזרק לסוכנים — או None כשלא צורפה תמונה."""
    return getattr(analysis, "context_he", None) or None if analysis else None


def _prepare_turn(request: ChatRequest) -> tuple[_SessionEntry, str, object | None]:
    """אימות הבקשה + שליפת השיחה החיה — משותף לשני נתיבי הצ'אט."""
    if not _USER_ID_RE.match(request.user_id):
        raise HTTPException(status_code=400, detail="user_id לא תקין")
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="הודעה ריקה")
    analysis = _analyze_attachment(request.image_base64)
    try:
        entry = _get_or_create_entry(request.user_id, request.demo)
    except RuntimeError as exc:
        # ensure_api_key — מפתח API חסר; הסבר בעברית כפי שנוסח ב-pipeline.
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"כשל בפתיחת שיחה: {exc}")
    return entry, message, analysis


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict:
    """תור-שיחה אחד (תשובה אחת בסוף): הודעה -> run_turn -> תשובת אן.

    נשמר גם אחרי הוספת ההזרמה: זהו נתיב הגיבוי של הדפדפן (אם ההזרמה
    נכשלת) והנתיב הפשוט לכל צרכן אחר. מבצע קריאות LLM בתשלום — מופעל אך
    ורק ביוזמת משתמש ששלח הודעה.
    """
    entry, message, image = _prepare_turn(request)
    with entry.lock:  # תורים של אותו משתמש רצים בזה אחר זה
        try:
            result = entry.session.run_turn(
                message, image_context=_image_context(image),
            )
        except Exception:
            # כשל תשתית (רשת/ספק) שחמק מה-fallbacks של ה-pipeline — לא
            # מפילים את השיחה: תשובת שגיאה קבועה, בלי להמציא טיפול.
            return _error_payload()
    return _turn_payload(result, image)


# ── הזרמת התשובה (SSE) ───────────────────────────────────────────────────
# למה: תור-ייעוץ אורך ~10-15 שניות, ובלי הזרמה המשתמש רואה "אן מקלידה…"
# לאורך כולן ואז קיר טקסט. כאן התור רץ ב-thread, ומדווח דרך on_progress:
# שלבים (בטיחות/ייעוץ/ניסוח) ומקטעי הניסוח תוך כדי כתיבה. משך התור לא
# משתנה — הזמן המורגש כן. התוצאה הסופית תמיד נשלחת באירוע done, והיא
# מקור האמת (הזרם עובר מסנן שורות-מקור כדי שלא יהבהב בו מה שיוסר בסוף).
_STAGE_LABELS_HE = {
    "gate_triage": "בודקת את ההודעה…",
    "consult": "מתייעצת עם הצוות הרפואי…",
    "compose": "מנסחת את התשובה…",
}

# סנטינל סוף-הזרם בתור.
_STREAM_DONE = object()


def _sse(event: str, data: dict) -> str:
    """פריים SSE אחד. json.dumps דואג שלא יישברו שורות בתוך data."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class SessionEndRequest(BaseModel):
    """סגירת שיחה חיה — גוף מינימלי: המזהה בלבד."""

    user_id: str = Field(min_length=8, max_length=64)


@app.post("/api/chat/session/end")
def end_session(request: SessionEndRequest) -> dict:
    """
    שחרור השיחה החיה של מזהה נתון — חינם, בלי LLM.

    מריץ ההדגמה קורא לזה בסיום כל תרחיש: כך ההקשר של ההרצה נזרק מיד
    ולא נשאר בזיכרון עד שה-LRU יפנה אותו. אין כאן סיכון: ההשלכה
    היחידה של שחרור שיחה היא שההודעה הבאה מאותו מזהה תתחיל שיחה חדשה.
    """
    if not _USER_ID_RE.match(request.user_id):
        raise HTTPException(status_code=400, detail="user_id לא תקין")
    return {"released": _release_session(request.user_id)}


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """
    אותו תור-שיחה בדיוק, כזרם SSE: stage -> delta* -> done.

    ה-pipeline רץ ב-thread נפרד (run_turn חוסם), ומקטעים/שלבים עוברים
    דרך תור. גם אם הדפדפן מתנתק — התור מסתיים ונרשם בלוג כרגיל.
    """
    entry, message, image = _prepare_turn(request)
    updates: "queue.Queue[object]" = queue.Queue()

    def _on_progress(payload: dict) -> None:
        updates.put(payload)

    def _worker() -> None:
        try:
            with entry.lock:
                result = entry.session.run_turn(
                    message, on_progress=_on_progress,
                    image_context=_image_context(image),
                )
            updates.put({"type": "done", "payload": _turn_payload(result, image)})
        except Exception:
            updates.put({"type": "done", "payload": _error_payload()})
        finally:
            updates.put(_STREAM_DONE)

    threading.Thread(target=_worker, daemon=True).start()

    def _events():
        source_filter = _StreamSourceFilter()
        while True:
            update = updates.get()
            if update is _STREAM_DONE:
                break
            kind = update.get("type")
            if kind == "stage":
                stage = update.get("stage", "")
                yield _sse("stage", {
                    "stage": stage,
                    "label_he": _STAGE_LABELS_HE.get(stage, ""),
                })
            elif kind == "delta":
                text = source_filter.feed(update.get("text", ""))
                if text:
                    yield _sse("delta", {"text": text})
            elif kind == "done":
                tail = source_filter.flush()
                if tail:
                    yield _sse("delta", {"text": tail})
                yield _sse("done", update.get("payload", _error_payload()))

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # שלא ייאגר ע"י proxy מול המשתמש
        },
    )


# ═══════════════════════════════════════════════════════════════════════
#  אזור המנהל — בקרת גישה + מסמכי הפרויקט + קישור לאפליקציות
# ═══════════════════════════════════════════════════════════════════════
# בקרת גישה לאזור המנהל מבוססת משתמש מנהל יחיד, שפרטיו נשמרים ב-.env
# מחוץ לבקרת גרסאות. זו החלטה מכוונת המתאימה להיקף המערכת — משתמש אחד
# בפועל, ולכן אין צורך בשכבת ניהול משתמשים. המימוש בהתאם: השוואה בשרת
# מול שני משתני הסביבה, וטוקן בזיכרון התהליך (8 שעות).
# בהתאם לאותו היקף, אזור המנהל גם אינו מגן על נתון רגיש: מוגשים ממנו רק
# מסמכי הפרויקט (מצגת, README, תוכנית בדיקות...) — לא לוג השיחות ולא .env.
#
# הפרטים עצמם **אינם בקוד**: הם נקראים מ-ADMIN_EMAIL / ADMIN_PASSWORD
# בסביבה (ב-.env המקומי, שאינו עולה ל-Git; ב-.env.example יש רק
# מציין-מיקום). שתי סיבות מעשיות לקרוא אותם בכל בקשה ולא לקבע אותם
# בקבועי מודול: אין ערך ישן שנתקע בזיכרון אחרי שינוי בסביבה, ואין שני
# מקורות אמת שאפשר לשכוח לסנכרן.
#
# **אין ברירת מחדל שמאפשרת התחברות.** חסר אחד מהשניים -> אין כניסה, גם
# לא עם שדות ריקים: השוואת bytes בין "" ל-"" הייתה מחזירה True, ולכן
# הבדיקה "האם הוגדרו פרטים" היא שער אמיתי ולא קישוט.
def admin_email() -> str:
    """כתובת המנהל מהסביבה (מנורמלת, ללא רישיות) — מחרוזת ריקה אם לא הוגדרה."""
    return _normalize_credential(os.getenv("ADMIN_EMAIL", "")).lower()


def admin_password() -> str:
    """סיסמת המנהל מהסביבה — מחרוזת ריקה אם לא הוגדרה."""
    return _normalize_credential(os.getenv("ADMIN_PASSWORD", ""))


def admin_credentials_configured() -> bool:
    """האם *שני* המשתנים הוגדרו. אחרת — אזור המנהל סגור לחלוטין."""
    return bool(admin_email() and admin_password())


ADMIN_CREDENTIALS_MISSING_HE = (
    "לא הוגדרו פרטי כניסה. יש להגדיר ADMIN_EMAIL ו-ADMIN_PASSWORD בקובץ "
    "הסביבה (.env) ולהפעיל מחדש את השרת."
)

# תוקף טוקן: 8 שעות, עד 50 טוקנים חיים במקביל.
_ADMIN_TOKEN_TTL_SECONDS = 8 * 60 * 60
_MAX_ADMIN_TOKENS = 50
_admin_tokens: "OrderedDict[str, float]" = OrderedDict()  # token -> תוקף (epoch)
_admin_tokens_lock = threading.Lock()

# ══ שתי אפליקציות ה-Streamlit — רשומה אחת לכל כרטיס ═══════════════════
# המימוש הזה נבנה מחדש מאפס, ובכוונה: קודם היו כאן שני כרטיסים שנבנו
# בשני בלוקים נפרדים בתוך admin_overview, וכל שדה (כתובת, פורט, סקריפט,
# פקודה) הועתק ידנית לכל אחד — בדיוק המבנה שבו כרטיס אחד יכול להצביע על
# היעד של השני בלי שהקוד "ישקר" באופן גלוי. עכשיו יש **מפרט אחד לכל
# אפליקציה** (AppSpec), וכל השדות שהכרטיס מציג נגזרים ממנו ומהמפתח שלו:
# משתנה הסביבה, הכתובת, הפורט (מהכתובת), קובץ האפליקציה ופקודת ההרצה.
# אין דרך להצביע על היעד השגוי בלי לשנות את המפרט עצמו.
#
# שתי האפליקציות הן שני תהליכים בשני פורטים: דשבורד הסקירה בפורט ברירת
# המחדל של streamlit (8501) ועמוד מודל החיזוי בשכן שלו (8502). אותם שמות
# משתני סביבה נקראים גם ב-dashboard/ui.py (לקישור ההדדי בסרגל הצד).
@dataclass(frozen=True)
class AppSpec:
    """
    אפליקציית Streamlit אחת = כרטיס אחד באזור המנהל.

    script  — קובץ האפליקציה. מקור האמת לשלושה דברים: פקודת ההרצה,
              בדיקת הזהות של המאזין בפורט, וההודעה כשאפליקציה אחרת
              תפסה אותו. אינו מוצג למשתמש (ראה ההערה על נתיבים בתצוגה).
    env_var — משתנה הסביבה שדוחף כתובת אחרת (הדגמה מרוחקת).
    """

    key: str
    title: str
    description: str
    script: str
    env_var: str
    default_url: str
    default_port: int

    @property
    def url(self) -> str:
        return os.getenv(self.env_var, self.default_url).rstrip("/")

    @property
    def port(self) -> int:
        """הפורט של הכתובת *שלה* (ברירת המחדל כשהכתובת בלי פורט מפורש)."""
        return urlsplit(self.url).port or self.default_port

    @property
    def command(self) -> str:
        """
        פקודת ההרצה של האפליקציה הזו, **עם הפורט שלה מוצמד**.

        ההצמדה אינה קוסמטיקה (באג מאומת): `streamlit run` בלי
        --server.port לוקח את 8501, ואם הוא תפוס — מדלג בשקט לפורט הפנוי
        הבא, כלומר 8502, שהוא הפורט של עמוד החיזוי. כך שני דשבורדים (אחד
        ותיק שנשאר מאתמול) הפכו את 8502 לדשבורד, וכפתור "מודל חיזוי" פתח
        את הדשבורד. הפקודה נגזרת מהמפרט, ולכן היא תמיד של הכרטיס שמציג
        אותה. היא מועברת ללקוח להעתקה ול-tooltip בלבד — ולא מוצגת כטקסט.
        """
        return f"streamlit run {self.script} --server.port {self.port}"


ADMIN_APPS: tuple[AppSpec, ...] = (
    AppSpec(
        key="dashboard",
        title="דשבורד אנליטיקה",
        description=(
            "מדדי שיחות מלוג התורים האנונימי: תחומים, נתיבי ייעוץ, "
            "זמני שלבים, איורים ודגלים אדומים."
        ),
        script="dashboard/app.py",
        env_var="ANNE_DASHBOARD_URL",
        default_url="http://localhost:8501",
        default_port=8501,
    ),
    AppSpec(
        key="ml",
        title="מודל חיזוי (ML)",
        description=(
            "הסתברות שתור יסתיים בהפניה למיון — הדגמה לימודית על נתונים "
            "סינתטיים, לא כלי קליני. אפליקציה נפרדת, בפורט משלה."
        ),
        script="dashboard/ml_app.py",
        env_var="ANNE_ML_URL",
        default_url="http://localhost:8502",
        default_port=8502,
    ),
)

APPS_BY_KEY: dict[str, AppSpec] = {spec.key: spec for spec in ADMIN_APPS}
# שם ידידותי לכל קובץ אפליקציה — כדי שהודעת "פורט תפוס" תנקוב בשם
# האפליקציה הפולשת ולא בנתיב הקובץ שלה (אין נתיבים בתצוגה).
APP_TITLE_BY_SCRIPT: dict[str, str] = {
    spec.script: spec.title for spec in ADMIN_APPS
}

# שמות תואמים-לאחור (נקראים בסוויטת הבדיקות ובקוד קיים) — נגזרים מהמפרטים
# עצמם, כך שאין כאן העתק שני שיכול להיפרד מהמקור.
DASHBOARD_SCRIPT = APPS_BY_KEY["dashboard"].script
ML_APP_SCRIPT = APPS_BY_KEY["ml"].script
DASHBOARD_URL = APPS_BY_KEY["dashboard"].url
ML_APP_URL = APPS_BY_KEY["ml"].url
DASHBOARD_PORT = APPS_BY_KEY["dashboard"].port
ML_APP_PORT = APPS_BY_KEY["ml"].port
DASHBOARD_COMMAND = APPS_BY_KEY["dashboard"].command
ML_APP_COMMAND = APPS_BY_KEY["ml"].command

# מסמכי הפרויקט המוגשים למנהל — הרשימה הסגורה (documents.DOCUMENTS) חיה
# ב-server/documents.py יחד עם הפרסור לתצוגה (מציג אחד + רנדרר לכל סוג);
# כאן נשארת רק ההגשה. הקבצים נקראים *ממקומם האמיתי* בפרויקט בכל בקשה —
# אין העתקים ואין מטמון, ומה שמוצג הוא תמיד מה שעל הדיסק. רשימה סגורה =
# אין מעבר על נתיבים (path traversal): המפתח מהדפדפן הוא תמיד מזהה
# מהמילון, לא נתיב.


class AdminLoginRequest(BaseModel):
    """גוף בקשת ההתחברות לאזור המנהל."""

    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=120)


# ── נרמול פרטי ההתחברות (באג מאומת) ──────────────────────────────────────
# מה שקרה: ההשוואה נעשתה ב-secrets.compare_digest על *מחרוזות*, וזו זורקת
# TypeError כשיש בקלט תו לא-ASCII ("comparing strings with non-ASCII
# characters is not supported"). בדף RTL קל מאוד לגרור תו כיווניות סמוי
# (RLM/LRM וכד') לתוך שדה המייל — בהדבקה או במיתוג שדה — ו-str.strip()
# אינו מסיר אותו כי הוא אינו רווח. התוצאה: התחברות עם הפרטים *הנכונים*
# החזירה 500, הדפדפן לא הצליח לפרסר את גוף השגיאה, והציג את הודעת ברירת
# המחדל "אימייל או סיסמה שגויים" — כלומר באג נראה כמו סיסמה שגויה.
# התיקון: מנקים תווים סמויים, מקצצים רווחים, ומשווים על *bytes* (שם
# compare_digest לעולם אינו זורק). כשל השוואה מתנקז ל-401, לא ל-500.
#   200b-200f: רוחב-אפס + RLM/LRM · 202a-202e: עקיפות כיווניות
#   2066-2069: בידוד כיווניות   · feff: BOM
_INVISIBLE_CHARS_RE = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]"
)


def _normalize_credential(value: str) -> str:
    """ניקוי תווים סמויים ורווחים מקלט התחברות (לפני השוואה)."""
    return _INVISIBLE_CHARS_RE.sub("", value or "").strip()


def _credentials_match(email: str, password: str) -> bool:
    """
    האם הפרטים תואמים למשתמש שהוגדר בסביבה. האימייל אינו תלוי רישיות;
    משני השדות מקוצצים רווחים ותווים סמויים (לסיסמת הדגמה אין שום שימוש
    לגיטימי ברווח בקצה, ורווח סורר לא יעצור את המשתמש). ההשוואה על
    bytes — אינה יכולה לזרוק על קלט לא-ASCII.

    לא הוגדרו פרטים -> False תמיד, לפני כל השוואה: אחרת שדות ריקים מול
    ערכים ריקים היו מתאימים זה לזה ופותחים את השער לכל אחד.
    """
    if not admin_credentials_configured():
        return False
    email_ok = secrets.compare_digest(
        _normalize_credential(email).lower().encode("utf-8"),
        admin_email().encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        _normalize_credential(password).encode("utf-8"),
        admin_password().encode("utf-8"),
    )
    return email_ok and password_ok


def _mint_admin_token() -> str:
    """יצירת טוקן מנהל חדש (בזיכרון התהליך, עם תוקף) ופינוי טוקנים שפגו."""
    token = secrets.token_urlsafe(24)
    now = time.time()
    with _admin_tokens_lock:
        for expired in [t for t, exp in _admin_tokens.items() if exp <= now]:
            _admin_tokens.pop(expired, None)
        _admin_tokens[token] = now + _ADMIN_TOKEN_TTL_SECONDS
        while len(_admin_tokens) > _MAX_ADMIN_TOKENS:
            _admin_tokens.popitem(last=False)
    return token


def _admin_token_valid(token: str | None) -> bool:
    """האם הטוקן קיים ובתוקף."""
    if not token:
        return False
    with _admin_tokens_lock:
        expiry = _admin_tokens.get(token)
        if expiry is None:
            return False
        if expiry <= time.time():
            _admin_tokens.pop(token, None)
            return False
    return True


def _require_admin(token: str | None) -> None:
    """שער אזור המנהל — 401 בעברית כשהטוקן חסר/פג (הדפדפן יחזיר להתחברות)."""
    if not _admin_token_valid(token):
        raise HTTPException(status_code=401, detail="נדרשת התחברות מחדש")


def _port_is_open(url: str, timeout: float = 0.25) -> bool:
    """
    האם יש מאזין ב-host:port של הכתובת (בדיקת TCP קצרה, בלי HTTP).

    כך כרטיס "דשבורד" יודע להציג "זמין" / "לא רץ" בלי לתלות את הדפדפן
    בבקשת cross-origin. כשל/שגיאה -> False (מוצג "לא רץ").
    """
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _is_local_url(url: str) -> bool:
    """האם הכתובת מצביעה על המכונה הזו (ולכן ניתן לזהות מי מאזין שם)."""
    return (urlsplit(url).hostname or "localhost") in _LOCAL_HOSTS


# ── בדיקת זמינות של אפליקציה מרוחקת (פרוסה בענן) ────────────────────────
# בדיקת TCP מספיקה לאפליקציה מקומית — פורט פתוח = תהליך רץ. על כתובת
# ענן היא **חסרת משמעות, ובאופן שמשקר לטובה**: כל אפליקציות Streamlit
# Cloud יושבות מאחורי אותו host משותף, ולכן חיבור TCP ל-443 מצליח לכל
# תת-דומיין שקיים ב-DNS — גם לאפליקציה שאינה פרוסה בכלל. נמדד כאן: חיבור
# ל-*.streamlit.app הצליח גם עבור שם אפליקציה מומצא, כלומר הכרטיס היה
# מציג "זמין" תמיד, ולא משנה מה הוגדר בכתובת.
#
# מה כן מבדיל: קוד הסטטוס של HTTP על הכתובת עצמה. נמדד מול שתי
# האפליקציות הפרוסות ומול שם מומצא — אפליקציה קיימת מחזירה 200 (גם כשהיא
# "נמה" ומוגש לה מסך ההתעוררות, וזה עדיין יעד תקין: הקישור מעיר אותה),
# ושם שאינו פרוס מחזיר 404 עם הפניה למסך השגיאה של Streamlit. לכן
# ההחלטה כאן היא לפי סטטוס, וכשל רשת אינו "לא נמצא" אלא "לא נגישה" —
# שתי הודעות שונות, כי הן דורשות שתי פעולות שונות מהמנהל.
#
# **ומכאן הטעות שנמצאה אחר כך, וזו אותה טעות בדיוק שכבה אחת מעלה.** הגרסה
# הראשונה קראה ב-follow_redirects=True והחזירה את הסטטוס ה*סופי*. אפליקציה
# ששירות האירוח מגן עליה בשער התחברות מפנה כל נתיב — כולל /_stcore/health —
# ל-host של שירות האימות וממנו חזרה למסך התחברות ב-host שלה, שמחזיר 200.
# כלומר הכרטיס הציג "זמין" לאפליקציה שאף מבקר אינו יכול לפתוח: **נכשל
# פתוח**, בדיוק כמו בדיקת ה-TCP שההערה למעלה באה להחליף. נמדד על שתי
# האפליקציות הפרוסות: 303 -> 303 -> 303 -> 200, ושני העמודים הסופיים
# זהים בית-בית (9,272 בתים, אותו sha256) ואינם מכילים אף תו עברי — כלומר
# מסך התחברות ולא תוכן האפליקציה.
#
# לכן ההפניות **אינן** נבלעות: הבדיקה הולכת בעצמה, וברגע שהשרשרת עוזבת את
# ה-host של האפליקציה זו התשובה — שער התחברות, לא זמינות. הפניה שנשארת
# באותו host (תוספת "/" בסוף, http->https) עדיין נבלעת, כי היא באמת אותה
# אפליקציה; מספר הקפיצות חסום, כדי שלולאת הפניות תיפול ל"לא נגישה" ולא
# תיתלה.
_HEALTH_PATH = "/_stcore/health"  # נתיב הבריאות של Streamlit
_REMOTE_TIMEOUT_SECONDS = 4.0
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MAX_SAME_HOST_HOPS = 3


class _RemoteProbe(NamedTuple):
    """
    תוצאת בדיקה של יעד מרוחק.

    status         — קוד הסטטוס, או None כשלא ניתן היה להגיע בכלל.
    left_host_for  — הכתובת שאליה השרשרת יצאה *מחוץ* ל-host של האפליקציה,
                     או None. זה השדה שמבדיל שער התחברות מזמינות, והוא
                     נשמר בנפרד מהסטטוס דווקא מפני שהסטטוס לבדו משקר.
    """

    status: int | None
    left_host_for: str | None = None


# תפר לבדיקות: הסוללה האופליינית מזריקה בודק מזויף, כדי שסיווג התשובות
# ייבדק **בלי שום קריאת רשת** — אותה גישה של set_connection_factory
# בשכבת ה-Postgres. בודק מוזרק יכול להחזיר סטטוס בלבד (int/None) או
# (status, left_host_for) — הצורה הראשונה נשמרה כדי שבדיקות קיימות
# יישארו קריאות, והשנייה היא זו שמבטאת הפניה.
_remote_probe: Callable[[str], object] | None = None


def set_remote_probe(probe: Callable[[str], object] | None) -> None:
    """החלפת בודק הזמינות המרוחק (בדיקות אופליין). None = חזרה ל-HTTP."""
    global _remote_probe
    _remote_probe = probe


def _as_probe(value: object) -> _RemoteProbe:
    """נרמול תשובת בודק מוזרק לצורה אחת."""
    if isinstance(value, _RemoteProbe):
        return value
    if isinstance(value, tuple):
        return _RemoteProbe(*value)
    return _RemoteProbe(value, None)  # type: ignore[arg-type]


def _http_probe(url: str) -> _RemoteProbe:
    """
    בדיקת GET לכתובת, בלי לבלוע הפניה שעוזבת את ה-host של האפליקציה.

    לעולם אינו זורק: כרטיס באזור המנהל אינו סיבה להפיל בקשה. httpx כבר
    תלות מוצהרת של המעטפת (הוא הלקוח של fastapi.testclient).
    """
    if _remote_probe is not None:
        return _as_probe(_remote_probe(url))
    try:
        import httpx

        origin = urlsplit(url).hostname
        target = url
        for _ in range(_MAX_SAME_HOST_HOPS + 1):
            response = httpx.get(
                target, timeout=_REMOTE_TIMEOUT_SECONDS, follow_redirects=False,
            )
            if response.status_code not in _REDIRECT_CODES:
                return _RemoteProbe(response.status_code, None)
            target = urljoin(target, response.headers.get("location") or "")
            if (urlsplit(target).hostname or origin) != origin:
                return _RemoteProbe(response.status_code, target)
        return _RemoteProbe(None, None)  # לולאת הפניות בתוך אותו host
    except Exception:
        return _RemoteProbe(None, None)


def _remote_app_state(url: str) -> dict:
    """
    מצב אפליקציה מרוחקת, לפי תשובת ה-HTTP של הכתובת *שלה*.

    זהות המאזין אינה נבדקת (mismatch=False תמיד): היא נשענת על התהליך
    המקומי, ולתהליך בענן אין PID כאן. זו גם אינה בעיה — התנגשות פורטים
    היא תקלה מקומית בלבד.
    """
    probe = _http_probe(url.rstrip("/") + _HEALTH_PATH)
    status = probe.status
    if probe.left_host_for is not None:
        # שער התחברות של שירות האירוח. נבדק *לפני* הסטטוס בכוונה: הסטטוס
        # בשרשרת כזו הוא 3xx (ואחרי בליעה — 200), ושניהם היו מסווגים כזמין.
        reason = "auth_required"
    elif status is None:
        reason = "unreachable"
    elif status == 404:
        reason = "not_found"
    elif 200 <= status < 400:
        reason = "ok"
    else:
        reason = "http_error"
    return {
        "listening": reason == "ok",
        "available": reason == "ok",
        "mismatch": False,
        "script": None,
        "pid": None,
        "remote": True,
        "reason": reason,
        "status": status,
        "redirect_to": probe.left_host_for,
    }


def _listener_script(url: str) -> tuple[str | None, int | None]:
    """
    איזה סקריפט Streamlit מאזין בפורט של הכתובת, ובאיזה PID.

    למה בכלל: בדיקת TCP אומרת רק "יש מאזין" — לא *מי*. בדיוק שם נולד
    הבאג: דשבורד שגלש ל-8502 (streamlit בלי --server.port) גרם לכרטיס
    "מודל חיזוי" להציג "זמין" ולפתוח... את הדשבורד. כאן מזהים את התהליך
    שמחזיק את הפורט ומחזירים את שם הסקריפט שלו, כדי שהכרטיס יגיד אמת.

    best-effort בלבד ולעולם לא זורק: זהות אינה זמינה מעל HTTP (שתי
    האפליקציות מגישות אותו index.html של Streamlit ואותו /_stcore/health),
    ולכן היא נשענת על התהליך המקומי — כלומר רק על כתובת מקומית ורק אם
    lsof/ps זמינים. כשלא ניתן לדעת: (None, None) = "לא ידוע", וההתנהגות
    חוזרת לבדיקת ה-TCP בלבד.
    """
    if not _is_local_url(url):
        return None, None
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    import subprocess

    try:
        listing = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
            capture_output=True, text=True, timeout=1.5,
        ).stdout
    except Exception:
        return None, None
    pids = [line[1:] for line in listing.splitlines() if line.startswith("p")]
    for pid in pids:
        try:
            command = subprocess.run(
                ["ps", "-o", "command=", "-p", pid],
                capture_output=True, text=True, timeout=1.5,
            ).stdout
        except Exception:
            return None, None
        # הסדר חשוב: "app.py" הוא תת-מחרוזת של "ml_app.py", ולכן נבדק
        # תחילה הנתיב הארוך יותר (נגזר מהמפרטים, לא מרשימה ידנית).
        scripts = sorted(
            (spec.script for spec in ADMIN_APPS), key=len, reverse=True,
        )
        for script in scripts:
            if script in command.replace("\\", "/"):
                try:
                    return script, int(pid)
                except ValueError:
                    return script, None
    return None, None


def _app_state(url: str, script: str) -> dict:
    """
    מצב האפליקציה בכתובת *שלה*: האם היא עונה, והאם זו האפליקציה הנכונה.

    הבדיקה תמיד על הכתובת של הכרטיס — לא על localhost — ולכן היא נחלקת
    לפי סוג היעד, כי "עונה" נמדד אחרת בכל אחד מהם:
      * מקומי — פורט TCP פתוח + זהות התהליך שמאזין (ראה _listener_script).
      * מרוחק — קוד הסטטוס של הכתובת עצמה (ראה _remote_app_state), כי
        פורט 443 של host ענן משותף פתוח גם כשאין שם אפליקציה.

    available = היעד עונה **והאפליקציה שעונה היא זו של הכרטיס**. כשזהות
    המאזין אינה ידועה (אין lsof) לא מניחים רעה: mismatch נשאר False.
    """
    if not _is_local_url(url):
        return _remote_app_state(url)
    listening = _port_is_open(url)
    found, pid = _listener_script(url) if listening else (None, None)
    mismatch = bool(found) and found != script
    return {
        "listening": listening,
        "available": listening and not mismatch,
        "mismatch": mismatch,
        "script": found,
        "pid": pid,
        "remote": False,
        "reason": "mismatch" if mismatch else ("ok" if listening else "closed"),
        "status": None,
    }


def _mismatch_hint_he(state: dict, spec: AppSpec) -> str:
    """
    הסבר + הדרך לתקן, כשאפליקציה אחרת תפסה את הפורט של הכרטיס.

    הפולשת מזוהה בשם הידידותי שלה ולא בנתיב הקובץ: באזור המנהל אין
    נתיבים בתצוגה. פקודת התיקון עצמה נשלחת בשדה נפרד (command) — הכרטיס
    מעתיק אותה בלחיצה במקום להציג אותה.
    """
    pid = f", PID {state['pid']}" if state.get("pid") else ""
    intruder = APP_TITLE_BY_SCRIPT.get(state["script"], "אפליקציה לא מזוהה")
    return (
        f"בפורט {spec.port} מאזינה אפליקציה אחרת ({intruder}{pid}) ולא זו "
        "של הכרטיס — כך נראה streamlit שהופעל בלי הצמדת פורט וגלש לפורט "
        "הפנוי הבא. עצרו את התהליך והריצו מחדש עם פקודת ההרצה של הכרטיס "
        "(כפתור ההעתקה)."
    )


def _app_card(spec: AppSpec, ml_metrics: str | None) -> dict:
    """
    כרטיס אפליקציה אחד — כל שדותיו נגזרים מהמפרט *שלו*.

    כאן נסגר הבאג שגרר את הבנייה מחדש: אין יותר שני בלוקים מקבילים שכל
    אחד מהם נושא כתובת, פורט וסקריפט שהועתקו בנפרד. הפונקציה מקבלת מפרט
    אחד ומחזירה את הכרטיס שלו, ולכן `url`, `command` ובדיקת הזמינות תמיד
    מתייחסים לאותה אפליקציה. אין בכרטיס שום כתובת/נתיב להצגה: הכתובת
    יושבת בקישור של הכפתור, והפקודה — בהעתקה וב-tooltip.

    ml_metrics מועבר מבחוץ (טעינת ה-bundle יקרה ומשותפת) ומשמש רק את
    כרטיס מודל החיזוי.
    """
    state = _app_state(spec.url, spec.script)
    available = state["available"]
    remote = state["remote"]
    reason = state["reason"]
    if available:
        if spec.key == "ml":
            # על יעד מקומי המודל השמור הוא *של אותה מכונה*, ולכן הסטטוס
            # יכול להצהיר עליו. על יעד בענן זו כבר טענה על מכונה אחרת:
            # ה-bundle אינו בבקרת גרסאות, האפליקציה הפרוסה מאמנת מודל
            # משלה, ו"זמין — ללא מודל מאומן" היה נשמע כמו עובדה על העמוד
            # שנפתח. לכן בענן הסטטוס אומר רק "זמין", והמדדים המקומיים
            # מוצגים ברמז ומיוחסים במפורש למכונה הזו.
            if remote:
                status_he = "זמין"
                hint_he = (
                    f"מדדי המודל השמור במחשב הזה: {ml_metrics}. האפליקציה "
                    "הפרוסה מאמנת ושומרת מודל משלה." if ml_metrics else ""
                )
            else:
                status_he = ("זמין — מודל מאומן" if ml_metrics
                             else "זמין — ללא מודל מאומן")
                hint_he = (f"מדדי המודל השמור: {ml_metrics}" if ml_metrics else
                           "אין עדיין מודל מאומן — אפשר לאמן אותו מהכפתור "
                           "שבעמוד עצמו.")
        else:
            status_he, hint_he = "זמין", ""
    elif state["mismatch"]:
        # שבב הסטטוס נשאר קצר (white-space: nowrap בכרטיס) — ההסבר המלא
        # יושב ב-hint_he.
        status_he = "פורט תפוס"
        hint_he = _mismatch_hint_he(state, spec)
    elif reason == "auth_required":
        status_he = "דורש התחברות"
        hint_he = (
            "שירות האירוח מפנה את הכתובת למסך התחברות, ולכן מי שאין לו "
            "הרשאת צפייה בשירות אינו יכול לפתוח את האפליקציה — גם עם "
            "הקישור. אם זו הכוונה, אין מה לתקן; אחרת יש לשנות את הרשאות "
            "הצפייה של האפליקציה בשירות האירוח לציבורי."
        )
    elif reason == "not_found":
        status_he = "כתובת לא נמצאה"
        hint_he = (
            "הכתובת שהוגדרה לאפליקציה הזו בסביבה אינה מצביעה על אפליקציה "
            "פרוסה — שירות האירוח החזיר 'לא נמצא'. בדקו את שם האפליקציה "
            "בשירות ואת הכתובת שהוגדרה לה."
        )
    elif reason == "http_error":
        status_he = "לא נגישה"
        hint_he = (
            "שירות האירוח החזיר שגיאה בבדיקת הזמינות. הקישור עדיין פועל — "
            "ייתכן שהאפליקציה בתהליך התעוררות, ואפשר לנסות לפתוח אותה."
        )
    elif remote:
        status_he = "לא נגישה"
        hint_he = (
            f"לא הצלחתי להגיע ל{spec.title} בכתובת שהוגדרה לה בסביבה — "
            "ייתכן שאין חיבור לאינטרנט או ששירות האירוח אינו זמין כרגע. "
            "הקישור עדיין פועל, אפשר לנסות לפתוח אותה."
        )
    else:
        status_he = "לא רץ"
        hint_he = (
            f"{spec.title} היא אפליקציית Streamlit נפרדת (פורט {spec.port}) "
            "— הריצו אותה בטרמינל (כפתור העתקת פקודת ההרצה) ואז לחצו כאן."
        )
    return {
        "key": spec.key,
        "title": spec.title,
        "description": spec.description,
        "url": spec.url,
        "available": available,
        "status_he": status_he,
        "hint_he": hint_he,
        # פקודת ההרצה המקומית — רק כשהיעד מקומי. על יעד בענן היא הייתה
        # שקר שימושי-למראה: היא מרימה אפליקציה ב-localhost, שאינה הכתובת
        # שהכפתור שליד פותח. הלקוח מציג את כפתור ההעתקה רק אם השדה קיים,
        # ולכן ההשמטה כאן מסלקת אותו בלי שינוי בצד הדפדפן.
        # לא מוצגת כטקסט: הלקוח מעתיק אותה ושם אותה כ-tooltip בלבד.
        "command": None if remote else spec.command,
        "open_label_he": f"פתיחת {spec.title}",
    }


def _ml_model_path() -> Path:
    """נתיב מודל החיזוי — ANNE_ML_MODEL אם הוגדר, אחרת ברירת המחדל של ml/."""
    override = os.getenv("ANNE_ML_MODEL")
    if override:
        return Path(override)
    return PROJECT_ROOT / "ml" / "models" / "er_referral.joblib"


def _ml_metrics_he() -> str | None:
    """
    שורת מדדים קצרה מכרטיס המודל השמור (אם קיים ונטען) — להצגה בלבד.

    טעינת ה-bundle עצלה ועטופה: היעדר sklearn/joblib או גרסה לא תואמת
    לא שוברים את אזור המנהל, פשוט לא תוצג שורת מדדים.
    """
    path = _ml_model_path()
    if not path.exists():
        return None
    try:
        import joblib

        bundle = joblib.load(path)
        metrics = bundle.get("metrics") or {}
        parts = [
            f"{name}={value:.2f}"
            for name, value in metrics.items()
            if isinstance(value, (int, float))
        ]
        return " · ".join(parts[:4]) or None
    except Exception:
        return None


@app.post("/api/admin/login")
def admin_login(request: AdminLoginRequest) -> dict:
    """
    התחברות לאזור המנהל מול המשתמש היחיד שהוגדר בסביבה (הדגמה בלבד).

    הקלט מנורמל לפני ההשוואה (רווחים, רישיות בכתובת, תווי כיווניות
    סמויים) — ראה _credentials_match והרציונל שלידו. כל חריגה בלתי
    צפויה בהשוואה נחשבת כשל אימות (401) ולא כשגיאת שרת: כך אי אפשר שוב
    שתקלה תיראה למשתמש כמו "סיסמה שגויה".

    לא הוגדרו פרטי כניסה -> 503 עם הודעה מסודרת, ולא 401: המשתמש לא
    הקליד שום דבר שגוי, וההבדל בין "הסיסמה לא נכונה" לבין "לא הוגדרה
    סיסמה" הוא בדיוק מה שחוסך רבע שעה של חיפוש.
    """
    if not admin_credentials_configured():
        raise HTTPException(
            status_code=503, detail=ADMIN_CREDENTIALS_MISSING_HE,
        )
    try:
        matched = _credentials_match(request.email, request.password)
    except Exception:
        matched = False
    if not matched:
        raise HTTPException(status_code=401, detail="אימייל או סיסמה שגויים")
    return {"ok": True, "token": _mint_admin_token(), "email": admin_email()}


@app.post("/api/admin/logout")
def admin_logout(token: str = "") -> dict:
    """יציאה — מבטלת את הטוקן (אם קיים). תמיד מחזירה ok."""
    with _admin_tokens_lock:
        _admin_tokens.pop(token, None)
    return {"ok": True}


@app.get("/api/admin/overview")
def admin_overview(token: str = "") -> dict:
    """
    כל מה שאזור המנהל מציג, בקריאה אחת: האפליקציות (דשבורד/מודל חיזוי)
    ומסמכי הפרויקט — כולל האם כל קובץ/שירות זמין כרגע. חינם לחלוטין.
    """
    _require_admin(token)

    # כל אפליקציה נבדקת בכתובת *שלה*, ובזהות של מי שמאזין שם: קודם שתיהן
    # הצביעו לאותה כתובת (עמוד החיזוי היה טאב בדשבורד), ואחרי הפיצול
    # בדיקת ה-TCP עוד לא ידעה *מי* עונה — דשבורד שגלש ל-8502 נראה לכרטיס
    # "מודל חיזוי" כמו זמינות תקינה. עכשיו כל כרטיס נבנה ממפרט אחד
    # (ADMIN_APPS) ואומר אמת על עצמו בלבד.
    ml_metrics = _ml_metrics_he()
    # שני הכרטיסים נבנים במקביל, כי כל אחד מהם ממתין לבדיקת זמינות של
    # יעד *אחר*: על יעד מקומי זו בדיקת TCP של פחות ממילישנייה, אבל על יעד
    # בענן זו קריאת HTTP — נמדד ~2.3 שניות לכל אחת, כלומר ~4.6 שניות
    # סדרתיות לטעינת הלוח. שתי הבדיקות בלתי תלויות לחלוטין (כתובות שונות,
    # שום מצב משותף), ולכן הן שתי המתנות I/O מקבילות. הסדר נשמר (map).
    with ThreadPoolExecutor(max_workers=len(ADMIN_APPS)) as pool:
        apps = list(pool.map(
            lambda spec: _app_card(spec, ml_metrics), ADMIN_APPS,
        ))

    # כרטיסי המסמכים נבנים בשכבת המסמכים — כאן רק מעבירים את הטוקן,
    # שנדרש בקישורי ה-iframe/ההורדה (הם אינם יכולים לשלוח כותרות).
    return {
        "email": admin_email(),
        "apps": apps,
        "docs": documents.document_cards(token),
    }


@app.get("/api/admin/doc/{key}/view")
def admin_doc_view(key: str, token: str = "") -> dict:
    """
    התוכן המפורסר של מסמך, לתצוגה *בתוך* אזור המנהל.

    מחזיר `kind` + המטען המתאים לו (טקסט / צ'קליסט / מקורות / גלריה /
    כתובת iframe), והלקוח בוחר רנדרר לפי אותו מפתח. מקור חסר או ריק אינו
    שגיאה: הוא מוחזר עם available/empty והודעה בעברית, כדי שהמציג יראה
    כרטיס הסבר ולא מסך שבור. מפתח לא מוכר -> 404.
    """
    _require_admin(token)
    try:
        return documents.document_view(key, token)
    except documents.UnknownDocument:
        raise HTTPException(status_code=404, detail="מסמך לא מוכר")


@app.get("/api/admin/doc/{key}/page", response_class=HTMLResponse)
def admin_doc_page(key: str, token: str = "") -> HTMLResponse:
    """
    עמוד ה-HTML שמוצג ב-iframe של המציג (מסמכי html/markdown בלבד).

    Markdown מומר כאן ל-HTML ממותג; קובץ HTML שלם מוגש כמות שהוא. בשני
    המקרים הקריאה היא מהדיסק בכל בקשה — אין עותק מוטמע ואין מטמון.
    """
    _require_admin(token)
    try:
        return HTMLResponse(documents.document_page_html(key))
    except documents.UnknownDocument:
        raise HTTPException(status_code=404, detail="מסמך לא מוכר")


@app.get("/accessibility", response_class=HTMLResponse)
def accessibility_statement() -> HTMLResponse:
    """
    הצהרת הנגישות — נתיב **ציבורי** (בלי טוקן, חינם, בלי LLM).

    למה לא מאחורי שער המנהל כמו שאר המסמכים: הצהרת נגישות שרק מנהל יכול
    לקרוא אינה שווה דבר — היא נכתבת בשביל המשתמש. אותו קובץ בדיוק
    (docs/accessibility.md) מוגש גם במציג של אזור המנהל, נקרא חי בכל
    בקשה, ומרונדר לעמוד HTML ממותג עם אותם טוקני צבע.

    הפאנל בפינת המסך והקישור בתחתית הצ'אט מפנים לכאן.
    """
    return HTMLResponse(documents.document_page_html("accessibility"))


@app.get("/api/admin/doc/{key}")
def admin_doc(key: str, token: str = "") -> FileResponse:
    """
    הורדת הקובץ המקורי של מסמך — כפתור הגיבוי שלצד כל מציג.

    ברוב המסמכים זהו הקובץ שהמציג קורא; בשניים (מקורות הידע והסטוריבורד)
    המציג בונה תצוגה חיה מ-data/ ומקטלוג האיורים, וההורדה מגישה את
    הקובץ המקורי (docx/xlsx) — לכן spec.download_path ולא spec.source.

    ה-token מגיע ב-query כי הקישורים נפתחים בלשונית חדשה (<a target=_blank>
    אינו יכול לשלוח כותרות) — מקובל בהיקף הזה, שבו הטוקן פותח מסמכי
    פרויקט בלבד. מפתח שאינו במילון -> 404, כך שאין דרך לבקש נתיב שרירותי.
    """
    _require_admin(token)
    try:
        spec = documents.get_spec(key)
    except documents.UnknownDocument:
        raise HTTPException(status_code=404, detail="מסמך לא מוכר")
    path = spec.download_path
    if path is None or not path.exists():
        raise HTTPException(
            status_code=404,
            detail=(f"הקובץ אינו קיים בפרויקט: {path.name}" if path
                    else "למסמך הזה אין קובץ להורדה — הוא נבנה חי מהפרויקט."),
        )
    # inline — נפתח בלשונית (HTML/טקסט); אחרת הורדה (docx/xlsx).
    disposition = "inline" if spec.download_inline else "attachment"
    return FileResponse(
        path,
        media_type=spec.download_media_type,
        filename=path.name,
        content_disposition_type=disposition,
    )


@app.get("/admin")
def admin_page() -> FileResponse:
    """דף אזור המנהל (מסך התחברות + אזור הניהול באותו קובץ)."""
    return FileResponse(WEB_DIR / "admin.html")


@app.get("/admin/")
def admin_page_slash() -> RedirectResponse:
    """נרמול הכתובת עם לוכסן בסוף."""
    return RedirectResponse(url="/admin")


# הגשת קבצים סטטיים — אחרי רישום נתיבי ה-API (סדר ההתאמה ב-Starlette):
# הנכסים (לוגו/אווטאר/פלטה), האיורים מהרשימה הסגורה, ולבסוף ה-UI בשורש.
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
app.mount(
    "/illustrations",
    StaticFiles(directory=ILLUSTRATIONS_DIR),
    name="illustrations",
)
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
