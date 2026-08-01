"""
עטיפות CrewAI לכלים של "אן".

הפונקציות הנקיות עצמן חיות ב-tools/ (שעון, מיקום, מזג אוויר) וב-rag/ (שליפה
סמנטית). כאן הן נעטפות ככלי CrewAI כך שסוכן יוכל להפעיל אותן בזמן ריצה:

    search_first_aid_knowledge - שליפה סמנטית מהמאגר, נעולה מראש על topic
                                 (לכל רופא מומחה כלי משלו, בתחום שלו בלבד).
    get_current_time           - שעה/תאריך/יום בשבוע (להפניה לפי שעה).
    locate_place               - שם מקום -> קואורדינטות (להפניה לפי מיקום).
    get_weather                - מזג אוויר לפי קואורדינטות (הקשר אבחוני).

עקרונות (בהתאם ל-crewai 1.6.1 המותקן):
  * כלי מחזיר תמיד מחרוזת (json.dumps) — crewai ממיר כל ערך אחר עם str()
    ל-repr פייתוני שאינו JSON תקין.
  * כלי לעולם לא זורק חריגה — crewai מריץ מחדש כלי שנכשל עד 3 פעמים;
    עדיף להחזיר הודעת שגיאה מבוקרת בעברית.
  * שעון ומזג אוויר אינם נכנסים ל-cache הכלים (cache_function=False) —
    ערכיהם משתנים בין קריאות; ה-cache של crewai דלוק כברירת מחדל.
"""
from __future__ import annotations

import json
import threading

from crewai.tools import BaseTool, tool
from pydantic import BaseModel, Field

from rag.config import DEFAULT_TOP_K
from tools.clock import get_current_time as _get_current_time
from tools.location import geocode_location as _geocode_location
from tools.weather import get_weather as _get_weather

# שמות התחומים בעברית — לתיאורי הכלים ולפרומפטים.
TOPIC_HE = {
    "wounds": "פצעים וחתכים",
    "anxiety": "חרדה",
    "dehydration": "התייבשות",
    "cold": "הצטננות וצינון",
}


# ── מוני שימוש בכלים (observability, שקף 17) ────────────────────────────
# ספירת הפעלות לכל כלי בתור-השיחה הנוכחי: שם כלי -> מספר הפעלות.
# ה-pipeline מאפס בתחילת כל תור וקורא את התוצאה ל-TurnResult.tool_usage.
# הנעילה נדרשת כי שער הבטיחות וה-triage רצים במקביל ושניהם עשויים להפעיל כלים.
_TOOL_USAGE: dict[str, int] = {}
_USAGE_LOCK = threading.Lock()


def record_tool_use(tool_name: str) -> None:
    """רישום הפעלה אחת של כלי (thread-safe). נקרא מתוך כל _run של כלי."""
    with _USAGE_LOCK:
        _TOOL_USAGE[tool_name] = _TOOL_USAGE.get(tool_name, 0) + 1


def reset_tool_usage() -> None:
    """איפוס המונים — בתחילת כל תור-שיחה (pipeline.run_turn)."""
    with _USAGE_LOCK:
        _TOOL_USAGE.clear()


def get_tool_usage() -> dict[str, int]:
    """העתק של מוני התור הנוכחי: שם כלי -> מספר הפעלות."""
    with _USAGE_LOCK:
        return dict(_TOOL_USAGE)


# ── שליפה סמנטית (RAG) ──────────────────────────────────────────────────
# מודל ה-embedding (e5, ~2GB בזיכרון) ולקוח Chroma נטענים פעם אחת לכל
# התהליך — לא בכל חיפוש ולא בזמן import. הנעילה מבטיחה טעינה יחידה גם
# כשחימום-רקע (warm_up_rag מ-thread) וקריאת RAG ראשונה רצים במקביל:
# מי שמגיע שני ממתין על הנעילה במקום לטעון את המודל פעם נוספת.
_EMBEDDER = None
_STORE = None
_RAG_LOCK = threading.Lock()


def warm_up_rag() -> None:
    """
    טעינה מוקדמת של מודל ה-embedding ולקוח Chroma (חימום).

    נקראת מ-thread רקע בבניית ChatSession, כדי שקריאת ה-RAG הראשונה בשיחה
    לא תשלם את מחיר טעינת המודל (~2GB). בטוחה לקריאה חוזרת; חריגות נבלעות —
    כשל חימום יתגלה (ויטופל) בקריאת החיפוש עצמה.
    """
    global _EMBEDDER, _STORE
    try:
        with _RAG_LOCK:
            if _EMBEDDER is None or _STORE is None:
                from rag.embedding_store import Embedder, VectorStore
                _EMBEDDER = Embedder()
                _STORE = VectorStore()
    except Exception:
        pass


def _search_index(query: str, topic: str) -> str:
    """שליפה סמנטית מהאינדקס הקיים (chroma_db/), מסוננת לפי topic."""
    global _EMBEDDER, _STORE
    try:
        with _RAG_LOCK:
            if _EMBEDDER is None or _STORE is None:
                # import כבד (torch/sentence-transformers) — רק בשימוש ראשון.
                from rag.embedding_store import Embedder, VectorStore
                _EMBEDDER = Embedder()
                _STORE = VectorStore()

        results = _STORE.query(
            _EMBEDDER.embed_query(query), top_k=DEFAULT_TOP_K, topic=topic,
        )
    except Exception as exc:  # לעולם לא מפילים את הסוכן על כשל תשתית
        return (
            f"שגיאה בגישה למאגר הידע: {exc}. "
            "ודא ש-chroma_db/ קיים (python build_index.py)."
        )

    if not results:
        return (
            f"לא נמצא מידע רלוונטי בתחום '{TOPIC_HE.get(topic, topic)}'. "
            "אם המאגר ריק — יש להריץ python build_index.py."
        )

    blocks = []
    for i, r in enumerate(results, start=1):
        meta = r.get("metadata", {})
        blocks.append(
            f"[קטע {i} | סעיף: {meta.get('section', '')} | "
            f"מקור: {meta.get('source', '')} | דמיון: {r.get('similarity', 0):.2f}]\n"
            f"{r.get('text', '')}"
        )
    return "\n\n".join(blocks)


def deterministic_rag_context(topic: str, query: str) -> str:
    """
    שליפת RAG דטרמיניסטית עבור ה-pipeline (המסלול הישיר): אותה שליפה
    בדיוק כמו כלי החיפוש של הרופא, אבל מופעלת בקוד — כך חובת ה-RAG-first
    נאכפת בקוד ולא תלויה בלולאת ה-ReAct של המודל (שנצפתה מדלגת על החיפוש
    או מתקעת במיצוי איטרציות). ההפעלה נרשמת במוני הכלים כרגיל.
    """
    record_tool_use("search_first_aid_knowledge")
    return _search_index(query, topic)


class SearchQueryInput(BaseModel):
    """סכמת הקלט של כלי החיפוש."""
    query: str = Field(
        description="שאילתת חיפוש בעברית: התסמינים או פעולת הטיפול המבוקשת"
    )


class FirstAidSearchTool(BaseTool):
    """כלי שליפה סמנטית הנעול על תחום (topic) אחד — כלי אחד לכל רופא מומחה."""

    name: str = "search_first_aid_knowledge"
    description: str = ""  # נקבע לפי התחום בעת היצירה (make_rag_tool)
    args_schema: type[BaseModel] = SearchQueryInput
    topic: str

    def _run(self, query: str, **kwargs) -> str:
        record_tool_use(self.name)
        return _search_index(query, self.topic)


def make_rag_tool(topic: str) -> FirstAidSearchTool:
    """בניית כלי חיפוש הנעול על תחום נתון (wounds/anxiety/dehydration/cold)."""
    topic_he = TOPIC_HE.get(topic, topic)
    return FirstAidSearchTool(
        topic=topic,
        description=(
            f"חיפוש סמנטי במאגר העזרה הראשונה, בתחום {topic_he} בלבד. "
            "קלט: query בעברית (תסמינים או טיפול). "
            "פלט: קטעי ידע ממקורות רפואיים, כולל שם המקור של כל קטע. "
            "חובה לחפש כאן לפני מתן המלצת טיפול."
        ),
    )


# ── כלי הקשר: שעה, מיקום, מזג אוויר ─────────────────────────────────────
@tool("get_current_time")
def get_current_time_tool() -> str:
    """מחזיר את השעה, התאריך והיום בשבוע הנוכחיים בישראל (אזור זמן Asia/Jerusalem). ללא פרמטרים."""
    record_tool_use("get_current_time")
    return json.dumps(_get_current_time(), ensure_ascii=False)


@tool("locate_place")
def locate_place_tool(place_name: str) -> str:
    """גיאוקודינג: מקבל שם יישוב/מקום בעברית או באנגלית ומחזיר קואורדינטות (latitude/longitude), שם מנורמל ומדינה."""
    record_tool_use("locate_place")
    return json.dumps(_geocode_location(place_name), ensure_ascii=False)


@tool("get_weather")
def get_weather_tool(latitude: float, longitude: float) -> str:
    """מזג אוויר נוכחי לפי קואורדינטות: טמפרטורה, לחות, תיאור, ומקסימום/מינימום יומי. את הקואורדינטות אפשר להשיג עם locate_place."""
    record_tool_use("get_weather")
    return json.dumps(_get_weather(latitude, longitude), ensure_ascii=False)


# שעה ומזג אוויר משתנים בין קריאות — לא נכנסים ל-cache הכלים של crewai.
get_current_time_tool.cache_function = lambda args, result: False
get_weather_tool.cache_function = lambda args, result: False


def context_tools() -> list:
    """שלושת כלי ההקשר (שעה, מיקום, מזג אוויר) — לרופאים המומחים."""
    return [get_current_time_tool, locate_place_tool, get_weather_tool]


def referral_tools() -> list:
    """
    כלי ההפניה של סוכן הבטיחות — השעון בלבד.

    locate_place הוסר בכוונה: מאז שיעדי החירום נבנים מהמאגר המקומי
    (crew/emergency_referral.py) אין לו למי לשרת, והשארתו הייתה מאפשרת
    קריאת רשת בתוך תור-שיחה — בדיוק מה שההפניה החדשה מונעת. גם השעה
    ממילא מוזרקת לפרומפט דטרמיניסטית (pipeline._time_context_he);
    הכלי נשאר כגיבוי זול (בלי רשת) אם דקסטר יבקש שעה מפורשות.
    """
    return [get_current_time_tool]
