"""
זרימת תור-השיחה של "אן" — החיבור בין כל הסוכנים לכדי שיחה אחת.

לכל הודעת משתמש (תור) ארבעה שלבים:

    1+2. שער הבטיחות + החלטת אן — במקביל (שתי קריאות I/O-bound):
         Dr. Dexter בוחן את התור (מפקח-על, שקף 8) בעוד אן מבצעת אנמנזה.
         פסיקת חירום של Dexter גוברת תמיד: אם is_emergency — תוצאת
         האנמנזה נזרקת, מוחזרת הפניה מיידית ואין שום ניסיון טיפול.
    3.   ייעוץ מומחה — בשני מסלולים:
         * ניתוב ישיר (המסלול המהיר, ברוב המקרים): כאשר topic_hint של אן
           הוא אחד מארבעת התחומים — הרופא המומחה רץ ישירות (Agent.kickoff
           עם response_format=SpecialistAdvice), בלי manager ובלי סבבי
           האצלה. הרופא נבנה עם אותם RAG נעול-תחום ורשימת איורים סגורה.
         * ה-crew ההיררכי (fallback): רק כש-topic_hint חסר או other —
           ה-manager מנתב ומאציל לרופא המתאים.
    4.   ניסוח אן — אן הופכת את הייעוץ הפנימי לתשובה אחת בקולה —
         הקול היחיד שהמשתמש שומע.

בנוסף:
  * **פלט מובנה בקריאה אחת:** כל שלב מובנה (שער הבטיחות, triage, ייעוץ
    ישיר) מזריק את הסכמה לפרומפט ומפרסר את התשובה בקוד, במקום לשלם את
    קריאת ההמרה הנוספת של crewai. נסיגה אוטומטית להמרה ההיא כשהפירוק
    נכשל — ראה parse_structured_output ו-_structured_kickoff.
  * **הזרמת הניסוח:** run_turn מקבל on_progress אופציונלי ומדווח דרכו על
    השלב הנוכחי ועל מקטעי הניסוח תוך כדי כתיבה (crew/streaming.py). זה
    צינור תצוגה בלבד — הזרימה, התוצאה וההיסטוריה אינן משתנות.
  * בבניית ChatSession נטען ברקע מודל ה-embedding (חימום מוקדם), כך
    שקריאת ה-RAG הראשונה בשיחה לא משלמת את מחיר הטעינה (~2GB).
  * הקשר-זמן (שעה/תאריך/יום) מוזרק דטרמיניסטית לכל הפרומפטים מ-
    tools.clock — קריאת פייתון חינמית, בלי סבב כלי של ה-LLM.
  * ההיסטוריה המוגשת לסוכנים מנוקה משורות "מקור:" של תשובות קודמות —
    מונע זיהום מקורות בין תורים (הרופא מצטט רק את ה-RAG של התור הנוכחי).
  * מוני הפעלות הכלים מאופסים בתחילת כל תור ונאספים ל-TurnResult.tool_usage.
  * כל תור נרשם כרשומה אנונימית בלוג ה-SQLite (storage/turn_log.py) דרך
    _log_turn_safe — best-effort: כשל בלוג לעולם לא מפיל ולא משנה את השיחה.

עקרון עמידות: כל כשל המרה/תשתית מתנקז ל-fallback בטוח וקבוע — המערכת
לעולם לא ממציאה טיפול ולעולם לא מפילה את השיחה בגלל JSON סורר.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from uuid import uuid4

from pydantic import BaseModel

from llm.config import get_provider
from tools.clock import get_current_time as _clock_now
from tools.location import geocode_location as _geocode
from tools.weather import get_weather as _weather

from .agents import SPECIALISTS, build_anne, build_safety, build_specialist
from .crew import build_care_crew
from .emergency_referral import (
    build_referral_block,
    detect_locality,
    escalate_level,
)
from .illustrations import get_illustration, suggest_illustration
from .metrics import get_llm_calls, reset_llm_calls
from .red_flags import cardiac_red_flag
from .schemas import (
    AnneDecision,
    SafetyVerdict,
    SpecialistAdvice,
    pop_filtered_sources,
)
from .streaming import stream_to
from .tools import (
    deterministic_rag_context,
    get_tool_usage,
    record_tool_use,
    reset_tool_usage,
    warm_up_rag,
)

# כמה הודעות אחרונות מהתמליל מוזנות לסוכנים (חוסם תפיחת הקשר בשיחה ארוכה).
MAX_HISTORY_MESSAGES = 16

# מה שנכתב בפרומפט כשלא צורפה תמונה. ערך מפורש ולא מחרוזת ריקה — כך
# הסוכן יודע שהשדה נבדק ואין בו מידע, ולא "ממציא" שראה תמונה.
NO_IMAGE_HE = "לא צורפה תמונה"

# תשובת fallback קבועה כשהייעוץ הפנימי נכשל טכנית — בלי להמציא טיפול.
FAILSAFE_REPLY_HE = (
    "סליחה, משהו השתבש אצלי רגע ולא הצלחתי להשלים את הבדיקה מול הצוות. "
    "אפשר לנסח את זה שוב במילים אחרות? ואם משהו מרגיש דחוף או מחמיר — "
    "אל תחכו לי: פנו לרופא/ה או למוקד רפואי."
)

# הודעת הפתיחה של אן (קבועה — לא דורשת קריאת LLM).
WELCOME_HE = (
    "שלום, אני אן — אחות דיגיטלית לעזרה ראשונית. אני כאן בשביל פצעים "
    "וחתכים, חרדה, התייבשות והצטננות. מה מרגישים? ספרו לי במילים שלכם."
)

# תשובה קבועה לברכה/שיחת חולין שה-triage ניתב בטעות לייעוץ (הגנת קוד —
# באג מאומת מריצה אמיתית: "שלום אן" נותב לטיפול מלא בחרדה).
SMALLTALK_REPLY_HE = (
    "שלום! נעים לפגוש אותך. אני כאן לעזרה ראשונית — פצעים וחתכים, חרדה, "
    "התייבשות והצטננות. ספרו לי מה מרגישים או מה קרה, ואשמח לעזור."
)

# לקסיקון ברכות/שיחת חולין: הודעה קצרה שכל מילותיה כאן איננה מקרה רפואי.
_SMALLTALK_WORDS = {
    "שלום", "היי", "הי", "אהלן", "הלו", "בוקר", "צהריים", "ערב", "לילה",
    "טוב", "טובים", "אן", "אנה", "מה", "נשמע", "קורה", "שלומך", "העניינים",
    "תודה", "רבה", "לך", "אחות", "יקרה", "hello", "hi", "hey",
}


def _is_smalltalk_only(text: str) -> bool:
    """
    זיהוי דטרמיניסטי של ברכה/שיחת חולין בלבד (ללא שום תוכן רפואי):
    הודעה קצרה (עד 5 מילים) שכל מילותיה בלקסיקון הברכות. שמרני בכוונה —
    כל מילה שאינה בלקסיקון ("כואב", "נחתכתי", "חום"...) מבטלת את ההתאמה.
    """
    tokens = re.sub(r"[!?.,:;()\"'״׳\-]+", " ", text or "").split()
    return bool(tokens) and len(tokens) <= 5 and all(
        t.lower() in _SMALLTALK_WORDS for t in tokens
    )


# ── הגנת קוד לעקרון היסוד (שקף 15): אן לעולם לא כותבת טיפול בעצמה ────────
# באג מאומת מריצה אמיתית (מעבר מחרדה לחתך באמצע שיחה): אן ענתה
# ב-action=reply עם הוראות טיפול בפצע — בלי ייעוץ, בלי RAG ובלי מקורות.
# ההנחיה חודדה (agents.py), אך לא סומכים על פרומפט בלבד: היוריסטיקה כאן
# ממירה reply כזה ל-consult. היא שמרנית בכוונה — נדרשים *שני* התנאים:
#   1. ההודעה האחרונה של המשתמש מתארת תלונה רפואית (סמן מהלקסיקון,
#      ולא שיחת חולין בלבד) — בלי סמן כזה לא מתערבים.
#   2. תוכן ה-reply נראה כהוראות טיפול: לפחות 2 שורות רשימה שאינן
#      שאלות (צעדים ממוספרים/מתובלטים), או לפחות 2 מילות פעולה
#      טיפוליות שונות (התאמת מילה-שלמה, לא תת-מחרוזת).
# תשובות אנמנזה לגיטימיות (שאלות המשך) אינן נתפסות: שאלות מסתיימות
# ב-"?" ואינן מכילות שתי מילות ציווי טיפוליות.

# מילות פעולה טיפוליות (ציווי/שם-פועל) בתשובת אן. בכוונה הושמטו צורות
# דו-משמעיות ("לחץ" הוא גם שם-עצם בתלונות חרדה; "שתי" היא גם המספר 2).
_TREATMENT_ACTION_WORDS = frozenset({
    "שטפי", "שטוף", "שטפו", "לשטוף",
    "לחצי", "לחצו", "ללחוץ",
    "חבשי", "חבשו", "לחבוש",
    "מרחי", "מרחו", "למרוח",
    "הניחי", "הניחו", "להניח",
    "כסי", "כסו", "לכסות",
    "הרימי", "הרימו", "להרים",
    "שתו", "לשתות", "לגמי", "לגמו", "ללגום",
    "גרגרי", "גרגרו", "לגרגר",
    "קררי", "קררו", "לקרר",
    "חטאי", "חטאו", "לחטא",
    "נשמי", "נשמו", "לנשום", "הרפי", "להרפות",
})

# סמני תלונה רפואית בהודעת המשתמש (התאמת תת-מחרוזת — צורות נטויות).
_COMPLAINT_MARKERS = (
    "כואב", "כאב", "נחתכ", "חתך", "פצע", "דימום", "מדמם", "שריט", "כווי",
    "נכוו", "חום", "צמרמורת", "נזלת", "שיעול", "גרון", "התעלפ", "סחרחור",
    "בחיל", "הקא", "חרד", "פאניק", "דופק", "נשימ", "התייבש", "צמא",
    "יובש", "שמש", "מכת", "נפיחות", "נפוח", "עקיצ", "נשכ", "שבר", "נקע",
    "אלרגי", "פריח", "גירוד", "מזיע", "רועד", "חולש",
)


def _mentions_medical_complaint(text: str) -> bool:
    """האם ההודעה מכילה סמן תלונה רפואית (תנאי 1 של הגנת הטיפול)."""
    return any(marker in (text or "") for marker in _COMPLAINT_MARKERS)


# ── רשת ביטחון דטרמיניסטית לניתוב (topic_hint) ──────────────────────────
# נצפה בריצות אמיתיות: לפעמים אן מחליטה consult בלי topic_hint — או גורע
# מזה, מסווגת "other" — גם במקרה מובהק ("נזלת, כאב גרון... מרגיש מצונן"),
# והתור נופל לנתיב ה-manager ההיררכי: איטי, יקר ופחות אמין במודל החסכוני.
# הלקסיקון כאן משלים רמז חסר/other רק כשבדיוק תחום אחד מתאים; בכל עמימות
# (0 או 2+ תחומים) — ה-crew ההיררכי מנתב כרגיל. מקרה other אמיתי (כאב
# שיניים, כאב גב) אינו מכיל אף מילת מפתח ולכן אינו נדרס; וגם אם הושלם
# רמז שגוי — הרופא הישיר רשאי להחזיר topic=other והמקרה מטופל כרגיל.
# רמז מפורש לאחד מארבעת התחומים לעולם לא נדרס.
_TOPIC_HINT_KEYWORDS = {
    "wounds": ("נחתכ", "חתך", "פצע", "דימום", "מדמם", "שריט", "כווי", "נכוו"),
    "anxiety": ("חרדה", "פאניק", "לחוץ", "להירגע", "מתח נפשי"),
    "dehydration": ("התייבש", "צמא", "בשמש", "מכת חום", "יובש בפה"),
    "cold": ("מצונן", "הצטננ", "נזלת", "שיעול", "כאב גרון", "אף סתום", "צינון"),
}


def _infer_topic_hint(text: str) -> str | None:
    """זיהוי תחום יחיד וברור לפי מילות מפתח; בעמימות כלשהי — None."""
    matched = [
        topic for topic, keywords in _TOPIC_HINT_KEYWORDS.items()
        if any(keyword in (text or "") for keyword in keywords)
    ]
    return matched[0] if len(matched) == 1 else None


def _looks_like_treatment_steps(text: str) -> bool:
    """האם טקסט נראה כהוראות טיפול (תנאי 2 של הגנת הטיפול)."""
    text = text or ""
    step_lines = [
        line.strip() for line in text.splitlines()
        if re.match(r"^\s*(\d+[.)]|[-•*])\s", line)
        and not line.strip().endswith("?")
    ]
    if len(step_lines) >= 2:
        return True
    words = set(re.findall(r"[א-ת]+", text))
    return len(words & _TREATMENT_ACTION_WORDS) >= 2


def apply_cardiac_safety_net(
    verdict: SafetyVerdict, user_message: str,
) -> tuple[SafetyVerdict, bool]:
    """
    רשת ביטחון: תיאור חד-משמעי של לחץ/כאב בחזה מבטיח פסיקת חירום.

    הכיוון היחיד שהרשת פועלת בו הוא **להחמיר**: היא לעולם לא מבטלת
    פסיקת חירום של Dexter ולא מורידה דגל. היא נוספה יחד עם ההבחנה
    ההקשרית בהנחייתו ("לחץ" נפשי מול לחץ בחזה) — חידוד הנחיה עלול
    להוליד false negative, וזו התקלה החמורה מבין השתיים, ולכן הצד
    הזה מגובה בקוד דטרמיניסטי ולא בניסוח.

    מחזיר (פסיקה, האם הרשת פעלה).
    """
    if verdict.is_emergency or not cardiac_red_flag(user_message):
        return verdict, False
    flags = list(verdict.red_flags)
    marker = "חשד ללחץ/כאב בחזה"
    if marker not in flags:
        flags.append(marker)
    return SafetyVerdict(
        is_emergency=True,
        red_flags=flags,
        reasoning_he=(
            "רשת הביטחון בקוד: ההודעה מתארת לחץ/כאב בחזה או הקרנה "
            f"אופיינית. הפסיקה המקורית: {verdict.reasoning_he}"
        ),
        # referral_he ו-referral_level מושלמים ע"י הוולידטור בסכמה
        # (נוסח ארצי קבוע + רמה critical) — הפניה לעולם לא נשארת ריקה.
        referral_level="critical",
    ), True


def _time_context_he() -> str:
    """
    שורת הקשר-זמן בעברית לפרומפטים — מוזרקת דטרמיניסטית לכל הסוכנים
    (קריאת פייתון חינמית ל-tools.clock, בלי קריאת כלי ובלי סבב ReAct).
    """
    info = _clock_now()
    if not info.get("ok"):
        return "לא זמין"
    return (
        f"יום {info['weekday']}, {info['date']}, השעה {info['time'][:5]} "
        f"({info['timezone']})"
    )


def _weather_context_he(locality: str) -> str | None:
    """
    הקשר מזג אוויר דטרמיניסטי ליישוב שהוזכר — באותה פילוסופיה של הזרקת
    השעה: ה-pipeline מביא את הנתונים בקוד (geocoding + מזג אוויר, שתי
    קריאות HTTP חינמיות) ומזריק אותם לפרומפט הייעוץ, במקום לסמוך על
    לולאת הכלים של המודל החסכוני (נצפתה לא-יציבה בריצות אמיתיות: פעם
    דילגה על הכלים ופעם נתקעה במיצוי איטרציות). ההפעלות נרשמות במוני
    הכלים — אותה יכולת, מסלול הפעלה אמין; כלי ה-LLM נשארים כגיבוי.
    כשל רשת/גיאוקודינג -> None (ההנחיה מפנה את הרופא למסלול הגיבוי).
    """
    try:
        record_tool_use("locate_place")
        location = _geocode(locality)
        if not location.get("ok"):
            return None
        record_tool_use("get_weather")
        weather = _weather(location["latitude"], location["longitude"])
        if not weather.get("ok") or weather.get("temperature_c") is None:
            return None
    except Exception:
        return None
    line = f"ב{locality} כעת {weather['temperature_c']}°C"
    description = weather.get("description")
    if description and description != "לא ידוע":
        line += f" ({description})"
    if weather.get("temp_max_today_c") is not None:
        line += f", מקסימום היום {weather['temp_max_today_c']}°C"
    return line


_GATE_PROMPT = (
    "בדוק את תור-השיחה הבא וזהה דגלים אדומים.\n\n"
    "הקשר זמן נוכחי (מהמערכת): {current_time}\n\n"
    "הקשר מתמונה (מהמערכת): {image_context}\n\n"
    "תמליל השיחה עד כה:\n{transcript}\n\n"
    "ההודעה החדשה של המשתמש:\n{message}\n\n"
    "פסוק עכשיו לפי כללי הבטיחות שלך."
)

# משימת הייעוץ במסלול הישיר — מקבילה ל-_CONSULT_DESCRIPTION של ה-crew,
# אך מנוסחת לרופא יחיד שכבר נבחר (אין ניתוב). הטקסטים עוברים _sanitize
# לפני ההצבה, כך שסוגריים מסולסלים בקלט לא שוברים את ה-format.
_DIRECT_CONSULT_PROMPT = (
    "אן, האחות המתשאלת, מעבירה אליך מקרה לייעוץ מקצועי בתחומך.\n"
    "\n"
    "הקשר זמן נוכחי (מהמערכת): {current_time}\n"
    "\n"
    "הקשר מזג אוויר (מהמערכת): {weather_context}\n"
    "\n"
    "הקשר מתמונה שהמשתמש העלה (מהמערכת): {image_context}\n"
    "\n"
    "סיכום המקרה מאן:\n{case_summary}\n"
    "\n"
    "ההודעה האחרונה של המשתמש, כלשונה:\n{user_message}\n"
    "\n"
    "תמליל השיחה עד כה (רקע בלבד — לא מקור לציטוט):\n{chat_history}\n"
    "\n"
    "קטעי הידע שנשלפו מהמאגר עבור המקרה (שליפת מערכת — הבסיס להמלצתך):\n"
    "{rag_context}\n"
    "\n"
    "איורים שהמשתמש כבר ראה בשיחה הזו: {shown_illustrations}\n"
    "\n"
    "בסס את ההמלצה אך ורק על הקטעים שסופקו לעיל; אם חסר בהם מידע חיוני "
    "— מותר חיפוש משלים אחד ב-search_first_aid_knowledge, ולא יותר. "
    "שדה sources חייב להכיל אך ורק את ערכי 'מקור:' של הקטעים שבהם "
    "השתמשת בפועל, מועתקים במדויק מילה במילה — לעולם לא מקורות מהתמליל "
    "או מתשובות קודמות, לעולם לא שמות מומצאים. בחר "
    "illustration_id לפי כללי הרשימה הסגורה שבהנחייתך. אם המקרה אינו "
    "בתחום מומחיותך כלל — קבע topic=other, השאר את sources ריק לחלוטין "
    "(אין שליפה רלוונטית — אסור להמציא שמות מקורות), והמלץ בעדינות על "
    "פנייה לרופא/ת המשפחה, בלי להמציא טיפול."
)

_COMPOSE_PROMPT = (
    "{message}\n\n"
    "[בלוק פנימי מהצוות הרפואי — לניסוח בלבד, אסור להציגו כלשונו]\n"
    "הקשר זמן נוכחי: {current_time}\n"
    "הקשר מזג אוויר שנבדק: {weather}\n"
    "הקשר מתמונה שהמשתמש העלה: {image_context}\n"
    "המלצת הטיפול: {advice}\n"
    "שאלות המשך מומלצות: {questions}\n"
    "איור מודרך זמין: {illustration}\n"
    "מקורות: {sources}\n"
    "[סוף הבלוק הפנימי]\n\n"
    "נסחי עכשיו את תשובתך הסופית למשתמש, בקולך."
)


def ensure_api_key() -> None:
    """
    בדיקה מוקדמת שמפתח ה-API של הספק הפעיל מוגדר בסביבה.

    ב-crewai 1.6.1 המפתח נדרש כבר בבניית הסוכנים (ולא רק בריצה), ובלעדיו
    מתקבלת שגיאה עמומה — לכן בודקים כאן ומסבירים בעברית.
    """
    provider = get_provider()
    var = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[provider]
    if not os.getenv(var):
        raise RuntimeError(
            f"חסר מפתח API: יש להגדיר {var} בקובץ .env "
            f"(העתק את .env.example ל-.env ומלא את המפתח). "
            f"הספק הפעיל: {provider}."
        )


# ── לוג אבחון (כבוי כברירת מחדל) ────────────────────────────────────────
# ANNE_DIAG=1 מדפיס, לכל תור, בדיוק את שלושת הדברים שקשה לאבחן בלעדיהם
# כשמשהו "לא מגיע" לתשובה:
#   (א) אילו כלים הופעלו בתור ומה הם החזירו (מזג אוויר/גיאוקודינג/RAG);
#   (ב) מחרוזות ההקשר כפי שהוזרקו בפועל לרופא המומחה;
#   (ג) אורך ההיסטוריה בתחילת התור ובסופו — האם היא נצברת בין תורים.
# מדפיס גם טקסט שיחה, ולכן מיועד להרצה מקומית בזמן אבחון בלבד. אין לו
# שום השפעה על הזרימה או על התוצאה.
def _diag_on() -> bool:
    return os.getenv("ANNE_DIAG", "").strip().lower() in {"1", "true", "yes"}


def _diag(label: str, value: object = "") -> None:
    if _diag_on():
        text = str(value)
        if len(text) > 400:
            text = text[:400] + f"… (סה\"כ {len(str(value))} תווים)"
        print(f"[אבחון] {label}: {text}" if text else f"[אבחון] {label}")


def _env_verbose() -> bool:
    """קריאת דגל הלוגים המפורטים מהסביבה (ANNE_VERBOSE)."""
    return os.getenv("ANNE_VERBOSE", "").strip().lower() in {"1", "true", "yes"}


# ── חימום RAG ברמת התהליך ────────────────────────────────────────────────
# מודל ה-embedding ולקוח Chroma הם משאבי-תהליך (globals ב-tools.py), לכן
# די ב-thread חימום אחד לכל התהליך — גם כשנבנות כמה ChatSession (למשל
# session נקי לכל תרחיש בסוללת הבדיקות): ה-session הראשון מתניע את החימום,
# והבאים אחריו כבר נהנים ממודל טעון בלי להקים thread מחדש לכל שיחה.
_WARMUP_STARTED = False
_WARMUP_START_LOCK = threading.Lock()


def _start_rag_warmup_once() -> None:
    """התנעת חימום ה-RAG ברקע — פעם אחת לתהליך (בטוח לקריאה חוזרת)."""
    global _WARMUP_STARTED
    with _WARMUP_START_LOCK:
        if _WARMUP_STARTED:
            return
        _WARMUP_STARTED = True
    threading.Thread(target=warm_up_rag, daemon=True).start()


def _sanitize(text: str) -> str:
    """
    נטרול סוגריים מסולסלים בקלט משתמש לפני אינטרפולציית crewai —
    מונע התנגשות עם משתני התבנית של המשימה ({case_summary} וכד').
    """
    return (text or "").replace("{", "(").replace("}", ")")


# ── פלט מובנה בקריאת LLM אחת (במקום שתיים) ───────────────────────────────
# מה שהיה: kickoff(..., response_format=Model) ב-crewai 1.6.1 מריץ את הסוכן,
# ואז — תמיד — מריץ Converter.to_pydantic (crewai/utilities/converter.py)
# ששולח את הפלט ל-LLM *שוב* רק כדי לעצב אותו לסכמה. אין שם קיצור-דרך של
# json.loads: כל שלב מובנה שילם שתי קריאות. נמדד בלוג: תור שכלל רק שער
# בטיחות + triage רשם 4 קריאות במקום 2, ותור ייעוץ ישיר 7 במקום 4.
#
# מה שיש: הסכמה מוזרקת לפרומפט (בדיוק כמו שה-Converter מנחה), התשובה
# מפורסרת כאן בקוד, וקריאת ההמרה נחסכת. אם הפירוק נכשל — נסיגה אוטומטית
# ל-Converter של crewai על אותו טקסט, כלומר בדיוק ההתנהגות הקודמת: המסלול
# החדש לעולם לא גרוע מהקודם, רק מהיר ממנו כשהמודל מחזיר JSON תקין (הרוב
# המוחלט). כל שכבות ה-fallback הבטוחות שהיו — נשארו במקומן.
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"^```[A-Za-z]*\s*|\s*```$")


def _field_type_he(spec: dict) -> str:
    """תיאור קצר בעברית של טיפוס שדה מתוך סכמת pydantic."""
    if "enum" in spec:
        return "אחד מ: " + " / ".join(str(value) for value in spec["enum"])
    if "anyOf" in spec:
        parts = [_field_type_he(option) for option in spec["anyOf"]]
        return " או ".join(dict.fromkeys(parts))
    kind = spec.get("type")
    if kind == "array":
        return f"רשימה של {_field_type_he(spec.get('items', {}))}"
    return {
        "string": "טקסט", "boolean": "true/false", "integer": "מספר שלם",
        "number": "מספר", "null": "null", "object": "אובייקט",
    }.get(kind, "טקסט")


def _field_placeholder(spec: dict) -> str:
    """מציין-מקום לשדה בשלד ה-JSON שמוצג לסוכן (לא ערך אמיתי)."""
    if "enum" in spec:
        return "<" + "|".join(str(value) for value in spec["enum"]) + ">"
    if "anyOf" in spec:
        inner = [
            option for option in spec["anyOf"] if option.get("type") != "null"
        ]
        base = _field_placeholder(inner[0]) if inner else "<טקסט>"
        return f"{base} או null"
    kind = spec.get("type")
    if kind == "array":
        return f"[{_field_placeholder(spec.get('items', {}))}, ...]"
    if kind == "boolean":
        return "<true|false>"
    if kind in {"integer", "number"}:
        return "<מספר>"
    return "<טקסט בעברית>"


def _schema_instruction(model: type[BaseModel]) -> str:
    """
    הנחיית הפלט המובנה שמוזרקת לפרומפט: רשימת השדות + שלד האובייקט.

    באג מאומת מריצה חיה: כשהוזרקה סכמת ה-JSON *כמו שהיא*
    (model_json_schema, שמפתחותיה "description"/"properties"), המודל חיקה
    את מבנה הסכמה והחזיר {"description": ..., "properties": {הערכים}} —
    פלט שאינו מופע תקין, ולכן כל שלב נפל לנסיגת ההמרה ושילם קריאה שנייה.
    זה ביטל בדיוק את החיסכון שלמענו נעשה השינוי. לכן כאן מוצגים שמות
    השדות ותיאוריהם בלבד, עם שלד מפורש — ואיסור מובהק להחזיר את הסכמה.

    הניסוח מכוון ל*תשובה הסופית* ("final answer") ולא ל"החזר JSON בלבד",
    בדיוק כמו ההנחיה שה-crewai עצמו מוסיף (i18n: lite_agent_response_format).
    זה חשוב לסוכן עם כלים (Dr. Dexter): שם עוטפת את התשובה scaffold של
    ReAct, ודרישה ל"JSON בלבד" עלולה להוביל לפלט שה-parser של crewai דוחה
    ("Failed to parse LLM output") — כלומר איטרציה מבוזבזת, ההפך מהמטרה.
    """
    schema = model.model_json_schema()
    properties: dict = schema.get("properties", {})
    required = set(schema.get("required", ()))

    field_lines = []
    skeleton_parts = []
    for name, spec in properties.items():
        obligation = "חובה" if name in required else "אופציונלי"
        description = spec.get("description", "")
        field_lines.append(
            f"  \"{name}\" ({_field_type_he(spec)}, {obligation})"
            + (f": {description}" if description else "")
        )
        skeleton_parts.append(f"\"{name}\": {_field_placeholder(spec)}")

    fields = "\n".join(field_lines)
    skeleton = "{" + ", ".join(skeleton_parts) + "}"
    return (
        "פורמט התשובה הסופית (חובה): התשובה הסופית שלך חייבת להיות אובייקט "
        "JSON יחיד ותקין, שמפתחותיו הם *בדיוק* שמות השדות הבאים (באנגלית) "
        "והתוכן בעברית:\n"
        f"{fields}\n"
        f"מבנה התשובה: {skeleton}\n"
        "אסור להחזיר את הסכמה עצמה, ואסור להשתמש במפתחות \"properties\" או "
        "\"description\" — רק אובייקט עם השדות שלמעלה. בלי טקסט לפני או "
        "אחרי, ובלי סימוני code block (```)."
    )


def parse_structured_output(
    raw: str, model: type[BaseModel]
) -> BaseModel | None:
    """
    פירוק פלט טקסטואלי של סוכן למודל pydantic — בלי קריאת LLM.

    סלחני בכוונה לעטיפות הנפוצות: רווחים, ```json ... ```, וטקסט מסביב
    לאובייקט. אימות הסכמה עצמו נשאר קשיח (כולל הוולידטורים שמסננים מקורות
    ואיורים לא מוכרים). כשל -> None, והקורא בוחר מה לעשות.
    """
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = _CODE_FENCE_RE.sub("", text).strip()
    candidates = [text]
    match = _JSON_OBJECT_RE.search(text)
    if match and match.group(0) != text:
        candidates.append(match.group(0))  # JSON עטוף בטקסט מסביב
    for candidate in candidates:
        try:
            return model.model_validate_json(candidate)
        except Exception:
            pass
        # חגורת ביטחון ל"חיקוי סכמה": מודל שמחזיר את הערכים עטופים
        # ב-{"properties": {...}} (נצפה בריצה חיה) — פורקים את העטיפה
        # במקום לשלם קריאת המרה נוספת.
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        inner = payload.get("properties") if isinstance(payload, dict) else None
        if isinstance(inner, dict):
            try:
                return model.model_validate(inner)
            except Exception:
                continue
    return None


def _with_schema_instruction(payload, model: type[BaseModel]):
    """הוספת הנחיית הסכמה לפרומפט — מחרוזת או רשימת הודעות (triage)."""
    instruction = _schema_instruction(model)
    if isinstance(payload, str):
        return f"{payload}\n\n{instruction}"
    messages = [dict(message) for message in payload]
    messages[-1]["content"] = f"{messages[-1]['content']}\n\n{instruction}"
    return messages


def _notify(on_progress: Callable[[dict], None] | None, payload: dict) -> None:
    """
    דיווח התקדמות לשכבת התצוגה (שלב נוכחי / מקטע טקסט זורם).

    כל חריגה נבלעת: צרכן שנעלם (דפדפן שהתנתק) לעולם לא מפיל תור-שיחה.
    """
    if on_progress is None:
        return
    try:
        on_progress(payload)
    except Exception:
        pass


@dataclass
class TurnResult:
    """תוצאת תור-שיחה אחד — התשובה למשתמש + מטא-דאטה לשכבות הבאות (UI/לוג)."""

    reply_he: str
    emergency: bool = False
    red_flags: list[str] = field(default_factory=list)
    topic: str | None = None
    illustration_id: str | None = None
    illustration: dict | None = None  # הרשומה המלאה מהרשימה הסגורה, אם יש
    # האיור הזה הוצג כבר בשיחה, והוא מוצג שוב מפני שלא נמצאה חלופה
    # מתאימה בקטלוג התחום (observability — מבחין בין "מניעת החזרה לא
    # עבדה" לבין "אין למה להחליף"; ראה _pick_illustration).
    illustration_repeated: bool = False
    sources: list[str] = field(default_factory=list)
    # מקורות שהרופא ציטט אך נפסלו בסינון מול המאגר (observability —
    # מבחין בין "לא ציטט" ל"ציטט מקור שאינו במאגר וסונן").
    filtered_sources: list[str] = field(default_factory=list)
    consulted: bool = False  # האם התור עבר ייעוץ מומחה (ישיר או crew)
    # מדדי ביצועים לתור: משך כל שלב בשניות (מפתחות: safety_gate, triage,
    # consult_direct / consult_crew, compose, total) ומספר קריאות ה-LLM
    # שהושלמו בפועל בתור — נספר במקור דרך ה-event bus של crewai
    # (LLMCallCompletedEvent, ראה crew/metrics.py) בכל הנתיבים.
    timings: dict[str, float] = field(default_factory=dict)
    llm_calls: int = 0
    # כמה שלבים מובנים נזקקו לנסיגה ל-Converter של crewai (קריאת LLM
    # נוספת) מפני שהפלט לא היה JSON תקין. 0 = המסלול המהיר החזיק בכל
    # השלבים; מספר גדול באופן קבוע = סימן שההנחיה או המודל צריכים תשומת לב.
    structured_retries: int = 0
    # מוני הפעלות כלים בתור (שם כלי -> מספר הפעלות) — observability
    # לדשבורד המתוכנן ולבדיקה שכלי ההקשר מופעלים כשצריך (ורק כשצריך).
    tool_usage: dict[str, int] = field(default_factory=dict)
    # הפניית חירום: הרמה שנקבעה (critical / urgent_care) והיישוב שלפיו
    # נבנתה רשימת היעדים. None כשאין חירום או כשלא נמצא יישוב מוכר
    # (ואז מוצג הנוסח הארצי הקבוע). לא נכתבים ללוג — הלוג נשאר בסכמה
    # הקיימת, ואלה שדות תצוגה/בדיקה בלבד.
    referral_level: str | None = None
    referral_locality: str | None = None
    # האם התור קיבל הקשר מתמונה (vision/). שדה תצוגה/בדיקה בלבד — הלוג
    # האנונימי לא מקבל מהתמונה שום נתון, וסכמתו לא השתנתה.
    image_used: bool = False


def _log_turn_safe(
    *,
    session_id: str,
    turn_index: int,
    user_message: str,
    result: TurnResult,
    verbose: bool = False,
) -> None:
    """
    רישום התור בלוג ה-SQLite האנונימי (storage/turn_log.py) — best-effort.

    ה-import עצל וכל חריגה נבלעת: גם שכבת אחסון חסרה/שבורה לא מפילה את
    השיחה ולא משנה את התשובה למשתמש. log_turn עצמו כבר בולע כשלים ומחזיר
    False — ה-try כאן הוא חגורת ביטחון נוספת (למשל כשל import). הרשומה
    אנונימית במבנה: טקסטים נשמרים כאורכים בלבד (ראה scrub_record והסכמה).
    """
    try:
        from storage.turn_log import log_turn

        ok = log_turn(
            result,
            session_id=session_id,
            turn_index=turn_index,
            user_message=user_message,
        )
        if not ok and verbose:
            print("[לוג] רישום התור נכשל (השיחה ממשיכה כרגיל).")
    except Exception as exc:
        if verbose:
            print(f"[לוג] רישום התור נכשל (השיחה ממשיכה כרגיל): {exc}")


class ChatSession:
    """
    שיחה אחת עם אן: מחזיקה את הסוכנים, ה-crew והתמליל, ומריצה תורים.

    הסוכנים וה-crew נבנים פעם אחת לשיחה; כל תור מפעיל אותם מחדש עם
    ההקשר העדכני (crewai משחזר את תבניות המשימה בכל kickoff).
    """

    def __init__(self, verbose: bool | None = None, log_turns: bool = True):
        """
        log_turns=False — שיחה שאינה נרשמת בלוג האנונימי.

        נועד להרצות הדגמה: תרחיש שרץ מול קהל אינו "שיחה אמיתית", ורישום
        שלו מזהם את נתוני הניתוח (הדשבורד ומודל החיזוי מודדים שימוש
        אמיתי). הדגל יושב על השיחה ולא על התור — כך אי אפשר לשכוח אותו
        בתור בודד, ושיחה שנפתחה כהדגמה נשארת כזו עד סופה.
        """
        ensure_api_key()
        self.verbose = _env_verbose() if verbose is None else verbose
        self.log_turns = log_turns
        self.dexter = build_safety(verbose=self.verbose)
        self.anne_triage = build_anne("triage", verbose=self.verbose)
        # מופע הניסוח זורם (stream=True): התוכן זהה, אך המקטעים נפלטים
        # תוך כדי כתיבה וניתן להזרים אותם לדפדפן (ראה _compose ו-streaming.py).
        self.anne_voice = build_anne("compose", verbose=self.verbose, stream=True)
        self.care_crew = build_care_crew(verbose=self.verbose)
        # רופאים למסלול הישיר — נבנים בעצלנות לפי תחום ונשמרים לשיחה כולה.
        self._direct_specialists: dict = {}
        self.history: list[dict] = []  # [{"role": "user"/"assistant", "content": str}]
        self.referred = False  # הועלה חירום והשיחה הופנתה לעזרה מקצועית
        # האיורים שהוצגו כבר בשיחה הזו — מונע הצגת אותו איור בתורים
        # עוקבים (ראה _pick_illustration). ריק בכל שיחה חדשה.
        self._shown_illustrations: set[str] = set()
        # היישוב האחרון שהוזכר בשיחה — נשמר בין תורים כדי שהפניית חירום
        # בתור מאוחר תדע לאן להפנות גם אם העיר נאמרה בתור הראשון (מקרה
        # מאומת בתרחיש ההדגמה: "אבא שלי בחיפה" בתור 1, כאב בחזה בתור 3).
        self._locality: str | None = None
        # מזהה שיחה אנונימי ללוג ה-SQLite — uuid אקראי פר-שיחה, מקבץ את
        # התורים לשיחה אחת בלי שום קשר לזהות המשתמש (privacy by design).
        self.session_id = uuid4().hex
        self._turn_index = 0
        # מונה נסיגות ההמרה בתור הנוכחי (מאופס בכל run_turn).
        self._structured_retries = 0
        # חימום מוקדם: טעינת מודל ה-embedding ו-Chroma ב-thread רקע, כדי
        # שקריאת ה-RAG הראשונה לא תמתין לטעינה (~2GB). ברמת התהליך —
        # פעם אחת לכל התהליך גם כשנבנות כמה שיחות (ראה _start_rag_warmup_once);
        # הנעילה ב-tools.py מבטיחה שקריאה מוקדמת תמתין ולא תטען כפול.
        _start_rag_warmup_once()

    # ── תשתית תמליל ──────────────────────────────────────────────────
    # ההיסטוריה נשמרת מלאה, אך לסוכנים מוגשת גרסה שמנוקות ממנה שורות
    # "מקור: ..." של תשובות קודמות של אן. זה סוגר באג זיהום מאומת מריצה
    # אמיתית: הרופא העתיק לשדה sources מקורות של תור קודם (מתחום אחר)
    # מתוך chat_history, במקום את מקורות קטעי ה-RAG של התור הנוכחי.
    _SOURCE_LINE_PREFIXES = ("מקור:", "מקורות:")

    @classmethod
    def _strip_source_lines(cls, text: str) -> str:
        return "\n".join(
            line for line in (text or "").splitlines()
            if not line.strip().startswith(cls._SOURCE_LINE_PREFIXES)
        ).strip()

    def _recent_history(self) -> list[dict]:
        return self.history[-MAX_HISTORY_MESSAGES:]

    def _agent_history(self) -> list[dict]:
        """ההיסטוריה כפי שמוגשת לסוכנים: תשובות אן ללא שורות המקור."""
        return [
            {**m, "content": self._strip_source_lines(m["content"])}
            if m["role"] == "assistant" else m
            for m in self._recent_history()
        ]

    def _transcript(self) -> str:
        if not self.history:
            return "(תחילת שיחה — אין תמליל קודם)"
        names = {"user": "משתמש", "assistant": "אן"}
        return "\n".join(
            f"{names.get(m['role'], m['role'])}: {m['content']}"
            for m in self._agent_history()
        )

    def _commit(self, user_message: str, reply_he: str) -> None:
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": reply_he})

    # ── קריאה מובנית אחת (משותפת לשער הבטיחות, ל-triage ולייעוץ הישיר) ──
    def _structured_kickoff(
        self, agent, payload, model: type[BaseModel]
    ) -> tuple[BaseModel | None, str]:
        """
        הרצת סוכן עם דרישת פלט מובנה — בקריאת LLM אחת.

        הסכמה מוזרקת לפרומפט, והתשובה מפורסרת בקוד (parse_structured_output).
        נכשל הפירוק? נסיגה ל-Converter של crewai על אותו טקסט — קריאה שנייה,
        בדיוק כמו לפני האופטימיזציה (ראה ההסבר ליד parse_structured_output).
        מחזיר (המודל או None, הטקסט הגולמי) — הגולמי דרוש ל-triage, שמותר לו
        להשתמש בתשובה חופשית של אן כתשובה למשתמש.
        """
        output = agent.kickoff(_with_schema_instruction(payload, model))
        raw = (getattr(output, "raw", "") or "").strip()
        parsed = parse_structured_output(raw, model)
        if parsed is not None:
            return parsed, raw

        self._structured_retries += 1
        if self.verbose:
            print(f"[פלט מובנה] פירוק ישיר נכשל ({model.__name__}) — "
                  "נסיגה להמרה של crewai.")
        try:
            from crewai.utilities.converter import Converter

            converted = Converter(
                llm=agent.llm,
                text=raw,
                model=model,
                instructions=_schema_instruction(model),
            ).to_pydantic()
        except Exception as exc:
            if self.verbose:
                print(f"[פלט מובנה] גם ההמרה נכשלה: {exc}")
            return None, raw
        return (converted if isinstance(converted, model) else None), raw

    # ── שלב 1: שער הבטיחות ──────────────────────────────────────────
    # (קריאות ה-LLM של כל השלבים נספרות במקור — event bus, crew/metrics.py.)
    def _safety_gate(self, user_message: str,
                     image_context: str | None = None) -> SafetyVerdict:
        verdict, _ = self._structured_kickoff(
            self.dexter,
            _GATE_PROMPT.format(
                current_time=_time_context_he(),
                image_context=image_context or NO_IMAGE_HE,
                transcript=self._transcript(),
                message=user_message,
            ),
            SafetyVerdict,
        )
        if isinstance(verdict, SafetyVerdict):
            return verdict
        # ההמרה נכשלה (נדיר): ממשיכים לצוות — גם לרופאים ולאן יש הנחיות
        # דגלים אדומים, כך שהכשל אינו מבטל את שכבות ההגנה האחרות.
        return SafetyVerdict(
            is_emergency=False,
            red_flags=[],
            reasoning_he="המרת פסיקת הבטיחות נכשלה — ממשיכים בזהירות לצוות.",
        )

    # ── יעדי חירום: מיקום, שעה, ורמת הפניה ──────────────────────────
    def _remember_locality(self, decision: AnneDecision,
                           user_message: str) -> str | None:
        """
        היישוב הרלוונטי לתור, ומעדכן את זיכרון השיחה.

        שלושה מקורות, לפי סדר אמינות: השדה locality_he של אן (התשאול
        קרא את המשפט), איתור דטרמיניסטי של שם יישוב מהמאגר בתוך ההודעה
        (רשת ביטחון — בתור חירום תוצאת ה-triage נזרקת, ולפעמים גם לא
        זיהתה), ולבסוף מה שנאמר בתורים קודמים.
        """
        candidate = (decision.locality_he or "").strip() or detect_locality(
            user_message)
        if candidate:
            self._locality = candidate
        return self._locality

    def _emergency_destinations(
        self, verdict: SafetyVerdict, user_message: str, locality: str | None,
    ) -> tuple[str, str | None]:
        """
        (רמת ההפניה, בלוק היעדים או None) — הכול מקוד ומקובץ מקומי.

        best-effort במוצהר: כל תקלה בבניית הבלוק (קובץ חסר/פגום, יישוב
        לא מוכר) מחזירה None, וההפניה נשארת הנוסח הארצי הקבוע שכתב
        Dexter. הפניית חירום לא נשברת בגלל מאגר.
        """
        level = escalate_level(
            verdict.referral_level, list(verdict.red_flags), user_message,
        )
        try:
            block = build_referral_block(locality, level)
        except Exception as exc:      # pragma: no cover - הגנת קצה
            if self.verbose:
                print(f"[הפניית חירום] בניית היעדים נכשלה: {exc}")
            block = None
        if self.verbose:
            print(f"[הפניית חירום] רמה={level} · יישוב={locality or '—'} · "
                  f"יעדים={'צורפו' if block else 'ללא'}")
        return level, block

    # ── שלב 2: החלטת אן (אנמנזה או ייעוץ) ───────────────────────────
    @staticmethod
    def _triage_content_he(user_message: str,
                           image_context: str | None = None) -> str:
        """
        גוף הודעת ה-triage לאן: ההודעה + הקשר-הזמן כהערת-מערכת בסופה —
        אן "יודעת" מה השעה בלי כלי ובלי קריאת LLM נוספת (רלוונטי לאנמנזה
        ולניסוח ההפניה). חשוף כפונקציה כדי שבדיקות אופליין יאמתו את
        ההזרקה על הקוד האמיתי.
        """
        image_block = f"\n\n{image_context}" if image_context else ""
        return (
            f"{user_message}\n\n"
            f"[הקשר זמן מהמערכת, לא מהמשתמש — אין לצטט כלשונו: "
            f"{_time_context_he()}]"
            f"{image_block}"
        )

    def _decide(self, user_message: str,
                image_context: str | None = None) -> AnneDecision:
        content = self._triage_content_he(user_message, image_context)
        messages = [*self._agent_history(), {"role": "user", "content": content}]
        decision, raw = self._structured_kickoff(
            self.anne_triage, messages, AnneDecision,
        )

        if not isinstance(decision, AnneDecision):
            if raw and not raw.lstrip().startswith("{"):
                # אן ענתה בטקסט חופשי במקום JSON — נשתמש בו כתשובה ישירה.
                return AnneDecision(action="reply", reply_he=raw)
            # אין פלט שמיש (או JSON פגום שגם ההמרה לא הצילה) — לצוות עם
            # ההודעה כמות שהיא (הצד הבטוח).
            return AnneDecision(action="consult", consult_query_he=user_message)

        # נרמול: reply בלי טקסט -> ייעוץ; consult בלי סיכום -> ההודעה עצמה.
        if decision.action == "reply" and not (decision.reply_he or "").strip():
            return AnneDecision(
                action="consult",
                consult_query_he=decision.consult_query_he or user_message,
                topic_hint=decision.topic_hint,
            )
        if decision.action == "consult" and not (decision.consult_query_he or "").strip():
            decision.consult_query_he = user_message
        return decision

    # ── שלב 3א: ייעוץ ישיר אצל הרופא המומחה (המסלול המהיר) ──────────
    def _consult_direct(
        self,
        topic: str,
        decision: AnneDecision,
        user_message: str,
        weather_context: str | None,
        image_context: str | None = None,
    ) -> SpecialistAdvice | None:
        """
        הרצת הרופא המומחה של התחום ישירות (LiteAgent, כמו אן ו-Dexter) —
        בלי manager ובלי סבבי האצלה. הרופא נבנה עם ה-RAG נעול-התחום ורשימת
        האיורים הסגורה שלו (build_specialist), כך שחובת השליפה מהמאגר
        והאימות מול הרשימה הסגורה נשמרות גם במסלול הזה.
        """
        agent = self._direct_specialists.get(topic)
        if agent is None:
            # המסלול הישיר: רופא ללא כלים — ה-RAG ומזג האוויר מוזרקים
            # לפרומפט בקוד, כך שהייעוץ הוא קריאה מובנית אחת (ראה
            # build_specialist על הרציונל; לולאת הכלים נצפתה לא-יציבה).
            agent = build_specialist(topic, verbose=self.verbose, with_tools=False)
            self._direct_specialists[topic] = agent
        # RAG-first דטרמיניסטי: התחום ידוע, אז הקטעים נשלפים בקוד ומוזרקים
        # לפרומפט (deterministic_rag_context) — חובת הביסוס על המאגר נאכפת
        # בקוד; כלי החיפוש נותר לרופא רק כחיפוש משלים.
        case_summary = decision.consult_query_he or user_message
        rag_context = _sanitize(deterministic_rag_context(topic, case_summary))
        prompt = _DIRECT_CONSULT_PROMPT.format(
            current_time=_time_context_he(),
            weather_context=weather_context or "לא סופק",
            image_context=image_context or NO_IMAGE_HE,
            case_summary=_sanitize(case_summary),
            user_message=_sanitize(user_message),
            chat_history=_sanitize(self._transcript()),
            rag_context=rag_context,
            shown_illustrations=self._shown_illustrations_he(),
        )
        _diag("הקשר שהוזרק לרופא המומחה",
              f"תחום={topic} · מזג אוויר={weather_context or 'לא סופק'} · "
              f"תמונה={'כן' if image_context else 'לא'} · "
              f"אורך קטעי RAG={len(rag_context)} תווים")
        _diag("פרומפט הייעוץ המלא", prompt)
        try:
            advice, _ = self._structured_kickoff(agent, prompt, SpecialistAdvice)
        except Exception as exc:
            print(f"[אזהרה] הייעוץ הישיר נכשל: {exc}")
            return None
        # כשל פירוק/המרה מתנקז ל-fallback הבטוח הקבוע ב-run_turn (None),
        # בדיוק כמו כשל של ה-crew.
        return advice if isinstance(advice, SpecialistAdvice) else None

    # ── שלב 3ב: ייעוץ הצוות ההיררכי (fallback לניתוב) ────────────────
    def _consult(
        self,
        decision: AnneDecision,
        user_message: str,
        weather_context: str | None,
        image_context: str | None = None,
    ) -> SpecialistAdvice | None:
        inputs = {
            "current_time": _time_context_he(),
            "weather_context": weather_context or "לא סופק",
            "image_context": image_context or NO_IMAGE_HE,
            "case_summary": _sanitize(decision.consult_query_he or user_message),
            "topic_hint": decision.topic_hint or "לא צוין",
            "user_message": _sanitize(user_message),
            "chat_history": _sanitize(self._transcript()),
            "shown_illustrations": self._shown_illustrations_he(),
        }
        try:
            result = self.care_crew.kickoff(inputs=inputs)
        except Exception as exc:
            # output_pydantic ב-1.6.1 זורק כשההמרה נכשלת סופית — לא מפילים שיחה.
            print(f"[אזהרה] ייעוץ הצוות נכשל: {exc}")
            return None
        advice = getattr(result, "pydantic", None)
        return advice if isinstance(advice, SpecialistAdvice) else None

    # ── בחירת האיור לתור (fallback + מניעת חזרה בשיחה) ───────────────
    def _shown_illustrations_he(self) -> str:
        """
        שורת ההקשר שמוזרקת לפרומפט הייעוץ: אילו איורים המשתמש כבר ראה.

        זו שכבת ההנחיה; שכבת האכיפה היא הקוד ב-_pick_illustration (באותה
        פילוסופיה של הזרקת הזמן/מזג האוויר: לא סומכים על הפרומפט לבד).
        """
        if not self._shown_illustrations:
            return "אין — עדיין לא הוצג איור בשיחה הזו"
        return (
            ", ".join(sorted(self._shown_illustrations))
            + " — העדף איור אחר שמתאים לפעולה שאתה ממליץ עליה; אם המתאים "
              "היחיד הוא אחד מאלה, מותר לבחור בו שוב"
        )

    def _pick_illustration(self, advice: SpecialistAdvice) -> bool:
        """
        קביעת האיור הסופי של התור, בשתי שכבות — שתיהן דטרמיניסטיות:

        1. **fallback** (באג מאומת בתחום cold): הרופא המליץ על פעולות שיש
           להן איור אך החזיר null -> התאמת מילות מפתח מול איורי קטגוריית
           התחום (suggest_illustration).
        2. **מניעת חזרה**: איור שכבר הוצג בשיחה הזו לא יוצג שוב — מחפשים
           חלופה *מתאימה* באותה קטגוריה. אין חלופה מובהקת? מותר להציג
           שוב: עדיף איור נכון שחוזר מאשר איור אחר שאינו מתאים להמלצה.

        פועל לפני הניסוח, כדי שאן תזכיר את האיור שנבחר בתשובתה. מחזיר
        True כשהאיור שנבחר הוצג כבר בשיחה (כלומר: חזרה שהותרה מפני שלא
        נמצאה חלופה) — לצורכי דיווח ב-TurnResult.illustration_repeated.
        """
        if advice.topic not in SPECIALISTS:
            # topic=other: אין קטלוג תחום, ולכן אין ממה לבחור חלופה.
            return False
        shown = self._shown_illustrations
        repeated = False
        if advice.illustration_id is None:
            # מעדיפים איור שטרם הוצג, ואם רק המוכר מתאים — הוא נבחר.
            fresh = suggest_illustration(
                advice.topic, advice.advice_he, exclude=shown,
            )
            chosen = fresh or suggest_illustration(advice.topic, advice.advice_he)
            if chosen:
                advice.illustration_id = chosen
                repeated = chosen in shown
                if self.verbose:
                    print(f"[איור] נבחר ב-fallback דטרמיניסטי: {chosen}"
                          + (" (הוצג כבר בשיחה, ואין חלופה מתאימה)"
                             if repeated else ""))
        elif advice.illustration_id in shown:
            alternative = suggest_illustration(
                advice.topic, advice.advice_he, exclude=shown,
            )
            if alternative:
                if self.verbose:
                    print(f"[איור] {advice.illustration_id} הוצג כבר בשיחה — "
                          f"הוחלף בחלופה {alternative}.")
                advice.illustration_id = alternative
            else:
                repeated = True
                if self.verbose:
                    print(f"[איור] {advice.illustration_id} הוצג כבר בשיחה, "
                          "ואין חלופה מתאימה בקטלוג התחום — מוצג שוב.")
        if advice.illustration_id:
            shown.add(advice.illustration_id)
        return repeated

    # ── שלב 4: ניסוח התשובה בקולה של אן ─────────────────────────────
    def _compose(
        self,
        user_message: str,
        advice: SpecialistAdvice,
        weather_context: str | None = None,
        on_progress: Callable[[dict], None] | None = None,
        image_context: str | None = None,
    ) -> str:
        illustration = (
            get_illustration(advice.illustration_id) if advice.illustration_id else None
        )
        illustration_desc = (
            f"כן — '{illustration['name']}' (id: {illustration['id']}). "
            "חובה להזכיר במשפט שצירפת איור שממחיש את השלבים."
            if illustration else "אין"
        )
        prompt = _COMPOSE_PROMPT.format(
            message=user_message,
            current_time=_time_context_he(),
            weather=weather_context or "לא נבדק",
            image_context=image_context or NO_IMAGE_HE,
            advice=advice.advice_he,
            questions="; ".join(advice.follow_up_questions_he) or "אין",
            illustration=illustration_desc,
            sources=", ".join(advice.sources) or "לא צוינו",
        )
        messages = [*self._agent_history(), {"role": "user", "content": prompt}]
        if on_progress is None:
            output = self.anne_voice.kickoff(messages)
        else:
            # הזרמה: כל מקטע שה-LLM של הניסוח פולט נשלח לצרכן (SSE לדפדפן)
            # תוך כדי הכתיבה. הטקסט המוחזר מ-kickoff נשאר המלא והסופי —
            # ההזרמה היא תוספת תצוגה, לא מקור האמת.
            def _sink(chunk: str) -> None:
                _notify(on_progress, {"type": "delta", "text": chunk})

            with stream_to(self.anne_voice.llm, _sink):
                output = self.anne_voice.kickoff(messages)
        reply = (getattr(output, "raw", "") or "").strip()
        if reply:
            return reply
        # fallback דטרמיניסטי: מרכיבים תשובה ישירות מהייעוץ, בלי LLM נוסף.
        reply = advice.advice_he
        if advice.follow_up_questions_he:
            reply += "\n\n" + "\n".join(advice.follow_up_questions_he)
        if advice.sources:
            reply += f"\n\nמקור: {', '.join(advice.sources)}"
        return reply

    # ── תור שלם ──────────────────────────────────────────────────────
    def run_turn(
        self,
        user_message: str,
        on_progress: Callable[[dict], None] | None = None,
        image_context: str | None = None,
    ) -> TurnResult:
        """
        הרצת תור-שיחה אחד מקצה-לקצה. מחזיר את תשובת אן + מטא-דאטה.

        image_context (אופציונלי) הוא בלוק ההקשר שהופק מתמונה שהמשתמש
        צירף (vision/analyze.py :: ImageAnalysis.context_he) — מדידות
        ותיאור חזותי, בעברית. הוא מוזרק לכל ארבעת השלבים בדיוק כמו הקשר
        השעה ומזג האוויר: **הקשר לתשאול, לא אבחון.** אף החלטה אינה עוברת
        לשכבת הראייה — שער הבטיחות והרופא המומחה מכריעים כמו קודם, רק עם
        מידע נוסף. ה-pipeline אינו מייבא את vision/ (אין לו תלות ב-Pillow):
        מי שמנתח את התמונה הוא הצד שקיבל אותה — server/app.py.

        on_progress (אופציונלי) הוא צינור לשכבת התצוגה, ואינו משנה דבר
        בזרימה או בתוצאה. הוא מקבל מילונים:
            {"type": "stage", "stage": "gate_triage"|"consult"|"compose"}
            {"type": "delta", "text": "..."}   # מקטעי הניסוח, תוך כדי כתיבה
        כשהוא None (CLI, בדיקות) התור מתנהג בדיוק כמו קודם. חריגה מהצרכן
        נבלעת (_notify) — דפדפן שהתנתק לא מפיל תור.
        """
        user_message = (user_message or "").strip()
        if not user_message:
            return TurnResult(
                reply_he="לא קיבלתי הודעה — ספרו לי מה מרגישים ואשמח לעזור."
            )

        _diag(f"תור {self._turn_index + 1} נפתח",
              f"session={self.session_id[:8]} · הודעות בהיסטוריה לפני התור="
              f"{len(self.history)} · יישוב זכור={self._locality or '—'} · "
              f"רישום ללוג={'כן' if self.log_turns else 'לא'}")

        turn_start = time.perf_counter()
        timings: dict[str, float] = {}
        reset_tool_usage()  # מוני הכלים נספרים פר-תור (observability)
        reset_llm_calls()   # וכך גם מונה קריאות ה-LLM (event bus, metrics.py)
        self._structured_retries = 0

        def _finish(result: TurnResult) -> TurnResult:
            result.timings = timings
            result.timings["total"] = time.perf_counter() - turn_start
            result.llm_calls = get_llm_calls()
            result.tool_usage = get_tool_usage()
            result.structured_retries = self._structured_retries
            _diag("סוף התור",
                  f"כלים={result.tool_usage or 'לא הופעלו'} · "
                  f"קריאות LLM={result.llm_calls} · "
                  f"הודעות בהיסטוריה אחרי={len(self.history)}")
            # רישום התור בלוג האנונימי — נקודת היציאה של כל המסלולים
            # (חירום, reply, smalltalk, failsafe, ייעוץ מלא). כתיבת רשומה
            # אחת ל-SQLite (אלפיות שנייה מול תור של שניות), best-effort.
            # שיחת הדגמה (log_turns=False) אינה נכתבת כלל — ראה __init__.
            self._turn_index += 1
            if not self.log_turns:
                return result
            _log_turn_safe(
                session_id=self.session_id,
                turn_index=self._turn_index,
                user_message=user_message,
                result=result,
                verbose=self.verbose,
            )
            return result

        def _timed(name: str, fn, *args):
            start = time.perf_counter()
            value = fn(*args)
            timings[name] = time.perf_counter() - start
            return value

        # 1+2. שער הבטיחות והחלטת אן — במקביל (שתי קריאות I/O-bound).
        # שני השלבים רק קוראים מ-self.history (הכתיבה ב-_commit מתרחשת
        # אחרי ששניהם הסתיימו) — אין מצב מירוץ.
        _notify(on_progress, {"type": "stage", "stage": "gate_triage"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            gate_future = pool.submit(_timed, "safety_gate", self._safety_gate,
                                      user_message, image_context)
            decide_future = pool.submit(_timed, "triage", self._decide,
                                        user_message, image_context)
            verdict = gate_future.result()
            decision = decide_future.result()

        _diag("החלטת אן",
              f"action={decision.action} · topic_hint={decision.topic_hint} · "
              f"locality_he={decision.locality_he!r}")

        # רשת ביטחון לבבית: אם ההודעה מתארת חד-משמעית לחץ/כאב בחזה
        # ו-Dexter בכל זאת לא פסק חירום — הקוד מעלה את הפסיקה. מחמיר
        # בלבד (ראה apply_cardiac_safety_net).
        verdict, net_fired = apply_cardiac_safety_net(verdict, user_message)
        if net_fired and self.verbose:
            print("[בטיחות] רשת הביטחון בקוד העלתה את הפסיקה לחירום "
                  "(לחץ/כאב בחזה בהודעה).")

        # היישוב הידוע לשיחה מתעדכן בכל תור (גם בתור שאינו חירום), כדי
        # שהפניה בתור מאוחר תוכל להישען על עיר שנאמרה קודם.
        locality = self._remember_locality(decision, user_message)

        # פסיקת חירום של Dexter גוברת — תוצאת ה-triage נזרקת.
        if verdict.is_emergency:
            reply = verdict.referral_he  # מובטח לא-ריק ע"י הוולידטור בסכמה
            # יעדי החירום מצורפים בקוד, לא ע"י המודל: שמות, טלפונים ושעות
            # מגיעים מהמאגר המקומי המאומת בלבד (ראה crew/emergency_referral).
            level, destinations = self._emergency_destinations(
                verdict, user_message, locality,
            )
            if destinations:
                reply = f"{reply}\n\n{destinations}"
            self._commit(user_message, reply)
            self.referred = True
            return _finish(TurnResult(
                reply_he=reply, emergency=True, red_flags=list(verdict.red_flags),
                referral_level=level,
                referral_locality=locality if destinations else None,
                image_used=bool(image_context),
            ))

        # 2. אן מחליטה: תשובה ישירה / אנמנזה, או ייעוץ.
        if decision.action == "reply":
            # הגנת קוד (עקרון היסוד, שקף 15): reply שנראה כהוראות טיפול
            # להודעה שמתארת תלונה רפואית -> מומר ל-consult. טיפול מגיע
            # אך ורק מהצוות, מבוסס-RAG (היוריסטיקה מתועדת למעלה).
            if (
                _mentions_medical_complaint(user_message)
                and not _is_smalltalk_only(user_message)
                and _looks_like_treatment_steps(decision.reply_he)
            ):
                if self.verbose:
                    print("[הגנה] תשובת טיפול עצמאית של אן הומרה לייעוץ צוות.")
                decision = AnneDecision(
                    action="consult",
                    consult_query_he=decision.consult_query_he or user_message,
                    topic_hint=decision.topic_hint,
                )
            else:
                self._commit(user_message, decision.reply_he)
                return _finish(TurnResult(reply_he=decision.reply_he))

        # הגנת קוד (באג מאומת): ברכה/שיחת חולין בלבד שנותבה בטעות לייעוץ —
        # מוחזרת תשובת פתיחה קבועה במקום "טיפול" בהודעה ללא תוכן רפואי.
        if _is_smalltalk_only(user_message):
            self._commit(user_message, SMALLTALK_REPLY_HE)
            return _finish(TurnResult(reply_he=SMALLTALK_REPLY_HE))

        # רשת ביטחון לניתוב: רמז חסר (None) או "other" מושלם דטרמיניסטית
        # כשמילות המפתח מצביעות על תחום יחיד; רמז מפורש לאחד מארבעת
        # התחומים לא נדרס לעולם (ראה הרציונל ליד _TOPIC_HINT_KEYWORDS).
        if decision.topic_hint in (None, "other"):
            inferred = _infer_topic_hint(
                f"{user_message}\n{decision.consult_query_he or ''}"
            )
            if inferred:
                decision.topic_hint = inferred
                if self.verbose:
                    print(f"[ניתוב] topic_hint הושלם דטרמיניסטית: {inferred}")

        # הזרקת מזג אוויר דטרמיניסטית (באותה פילוסופיה של הזרקת השעה):
        # כשאן חילצה יישוב והתחום עשוי להיות רגיש למזג אוויר — הנתונים
        # מובאים בקוד ומוזרקים לפרומפט (ראה _weather_context_he). מדולג
        # רק כשהתחום ודאי לא רלוונטי (wounds/anxiety בניתוב הישיר).
        weather_context = None
        locality = (decision.locality_he or "").strip()
        if locality and decision.topic_hint not in {"wounds", "anxiety"}:
            weather_context = _weather_context_he(locality)
        _diag("הקשר מזג אוויר",
              f"יישוב מהתור={locality or '—'} · תחום={decision.topic_hint} · "
              f"תוצאה={weather_context or 'לא נבדק/נכשל'}")

        # 3. ייעוץ מומחה: ניתוב ישיר כש-topic_hint מזוהה (המסלול המהיר);
        #    ה-crew ההיררכי רק כשהרמז חסר או other (fallback לניתוב).
        _notify(on_progress, {"type": "stage", "stage": "consult"})
        if decision.topic_hint in SPECIALISTS:
            advice = _timed(
                "consult_direct",
                self._consult_direct,
                decision.topic_hint, decision, user_message, weather_context,
                image_context,
            )
        else:
            advice = _timed(
                "consult_crew", self._consult, decision, user_message,
                weather_context, image_context,
            )
        # מקורות שנפסלו בסינון הסכמה (מומצאים/לא במאגר) — נאספים לדיווח.
        filtered_sources = pop_filtered_sources()
        if filtered_sources and self.verbose:
            print(f"[מקורות] סוננו מקורות שאינם במאגר: {filtered_sources}")

        if advice is None:
            self._commit(user_message, FAILSAFE_REPLY_HE)
            return _finish(TurnResult(reply_he=FAILSAFE_REPLY_HE))

        # האיור של התור: fallback דטרמיניסטי כשהרופא החזיר null, ומניעת
        # חזרה על איור שכבר הוצג בשיחה (ראה _pick_illustration).
        illustration_repeated = self._pick_illustration(advice)

        # 4. אן מנסחת את התשובה הסופית בקולה (מקבלת גם את הקשר מזג
        #    האוויר שנבדק — האזכור בתשובה לא תלוי בכך שהרופא שימר אותו).
        #    זה השלב היחיד שמוזרם למשתמש תוך כדי כתיבה.
        _notify(on_progress, {"type": "stage", "stage": "compose"})
        reply = _timed(
            "compose", self._compose, user_message, advice, weather_context,
            on_progress, image_context,
        )
        self._commit(user_message, reply)
        return _finish(TurnResult(
            reply_he=reply,
            image_used=bool(image_context),
            topic=advice.topic,
            illustration_id=advice.illustration_id,
            illustration=(
                get_illustration(advice.illustration_id)
                if advice.illustration_id else None
            ),
            illustration_repeated=illustration_repeated,
            sources=list(advice.sources),
            filtered_sources=filtered_sources,
            consulted=True,
        ))
