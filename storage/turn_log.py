"""
שכבת לוג השיחות האנונימית של "אן" — SQLite מקומי או Postgres של Supabase.

כל תור-שיחה נרשם כרשומה מובנית אחת בטבלת turns — בסיס לניתוח נתונים,
לדשבורד עתידי ולמודל חיזוי. פרטיות מובנית (privacy by design) בשלוש שכבות:

1. **הסכמה עצמה** — אין אף עמודת טקסט חופשי: הודעת המשתמש ותשובת אן
   מצטמצמות לאורכים בלבד (user_message_chars / reply_chars), דגלים אדומים
   ומקורות למונים בלבד, ומוני הכלים ממופים לעמודות קבועות (שם כלי לא מוכר
   נספר ב-tools_other בלי שהשם נשמר). עמודות ה-TEXT היחידות הן מזהים
   בתבנית קשיחה או אוצר-מילים סגור: ts_utc, session_id, consult_path,
   topic, illustration_id. תמונה שצורפה לתור מצטמצמת לדגל 0/1
   (image_attached) — בלי ממדים, בלי מדידות ובלי תיאור.
2. **scrub_record** — שכבת ביטחון לפני כל כתיבה: כל ערך מאומת מול ולידטור
   פר-עמודה. טקסט חופשי בשדה סגור (למשל עברית בשדה topic) מוחלף בברירת
   המחדל הבטוחה; שדה זהות פסול (ts_utc/session_id/turn_index) דוחה את
   הרשומה כולה; מפתחות שאינם בסכמה נזרקים — אי אפשר "להגניב" שדה חדש.
3. **אילוצי CHECK ב-SQL** — גם כתיבה ישירה שעוקפת את הקוד נחסמת על ידי
   בסיס הנתונים עצמו (IntegrityError על טקסט חופשי בעמודות enum/מזהה).

session_id הוא uuid4 אקראי שנוצר פר-ChatSession (ראה crew/pipeline.py) —
מקבץ את תורי השיחה בלי שום קשר לזהות המשתמש.

API:
    init_db()                  יצירת הקובץ/הטבלה + השלמת עמודות חסרות
                               (אידמפוטנטי; ראה _migrate)
    log_turn(result, ...)      רישום TurnResult — best-effort, לעולם לא זורק
    write_record(record, ...)  כתיבת רשומה גולמית — קפדני (זורק), תמיד דרך scrub
    write_records(records, ...) אותו דבר לרשומות רבות, בטרנזקציה אחת
    reset_log()                מחיקת כל הרשומות (כפתור המנהל בדשבורד)
    fetch_turns()              קריאת רשומות (לבדיקות ולדשבורד)

**שני backends, ממשק אחד.** מאז חיבור Supabase יש לסכמה הזו שני מימושים:
SQLite מקומי (ברירת המחדל, ספריית התקן בלבד) ו-Postgres של Supabase. שום
חתימה כאן לא השתנתה: הבחירה יושבת *מתחת* לפונקציות, ב-storage/backend.py
(המתג ANNE_LOG_BACKEND) וב-storage/supabase_backend.py (החיבור). לכל
פונקציה יש נקודת פענוח אחת — ``_target(db_path)`` — ומשם והלאה או SQLite
או Supabase. הגדרות חסרות, חבילה חסרה או חיבור שנכשל **אינם מפילים דבר**:
הלוג חוזר ל-SQLite המקומי עם אזהרה אחת ללוג (ראה fallback_to_sqlite).

הפרמטר ``db_path`` הוא "איזה דאטה", לא בהכרח "איזה קובץ": נתיב קובץ
(SQLite) או שם טבלה מהרשימה הסגורה turns / turns_synthetic (Supabase).
קובץ ששמו מכיל synthetic ממופה לטבלה הסינתטית ולהפך, כך שאותה קריאה
עובדת בשני ה-backends. נתיב ברירת המחדל: anne_log.db בשורש הפרויקט (לא
בבקרת גרסאות), עם עקיפה ב-db_path או ב-ANNE_LOG_DB.
"""
from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .backend import (  # שכבת המתג: קונפיגורציה טהורה, בלי sqlalchemy ובלי רשת
    BACKEND_SQLITE,
    BACKEND_SUPABASE,
    BACKENDS,
    DEFAULT_DB_PATH,
    ENV_BACKEND_VAR,
    ENV_DB_VAR,
    ENV_TABLE_VAR,
    LIVE_TABLE,
    PROJECT_ROOT,
    SYNTHETIC_DB_PATH,
    SYNTHETIC_TABLE,
    TABLES,
    Target,
    active_backend,
    describe_target,
    fallback_to_sqlite,
    resolve_target,
    sqlite_path_for,
)

# PROJECT_ROOT / DEFAULT_DB_PATH / ENV_DB_VAR הוגדרו כאן לפני פיצול שכבת
# ה-backend, ונשארים מיוצאים מכאן כי dashboard/, ml/ והבדיקות מייבאים
# אותם מ-storage.turn_log; מקור האמת שלהם עבר ל-backend.py.
__all__ = [
    # הסכמה ואוצר המילים
    "COLUMNS", "COLUMN_NAMES", "SCHEMA_VERSION", "TOPICS", "TOOL_COLUMNS",
    "CONSULT_PATHS", "Column",
    # ה-API של הלוג
    "init_db", "log_turn", "write_record", "write_records", "reset_log",
    "fetch_turns", "record_from_turn", "scrub_record",
    # שכבת ה-backend (מיוצאת מכאן לנוחות הקוראים הקיימים)
    "PROJECT_ROOT", "DEFAULT_DB_PATH", "SYNTHETIC_DB_PATH", "ENV_DB_VAR",
    "ENV_BACKEND_VAR", "ENV_TABLE_VAR", "LIVE_TABLE", "SYNTHETIC_TABLE",
    "TABLES", "BACKENDS", "BACKEND_SQLITE", "BACKEND_SUPABASE",
    "Target", "active_backend", "describe_target", "resolve_target",
]

# 1 -> 2: נוספה עמודת image_attached (דגל 0/1 — האם המשתמש צירף תמונה
# לתור). רשומות ישנות נשארות בגרסה 1 וערכן בעמודה 0, וזה נכון עובדתית:
# בתורים ההם לא הייתה תמונה. המספר נשמר *ברשומה*, כך שאפשר להבחין בין
# "לא צורפה תמונה" לבין "נרשם לפני שהעמודה קיימת".
SCHEMA_VERSION = 2

# אוצר המילים הסגור של העמודות הקטגוריות — תואם ל-Topic שב-crew/schemas.py
# (לא מיובא משם בכוונה: storage תלוי אך ורק בספריית התקן, בלי crewai).
TOPICS = ("wounds", "anxiety", "dehydration", "cold", "other")
CONSULT_PATHS = ("none", "direct", "crew")

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SESSION_RE = re.compile(r"^[0-9a-f]{32}$")
_SLUG_RE = re.compile(r"^[a-z0-9_]{1,64}$")

# מיפוי שמות מוני הכלים (crew/tools.py) לעמודות קבועות — רשימה סגורה;
# מונה בשם אחר מצטבר ל-tools_other בלי שהשם נשמר (אין טקסט חופשי).
TOOL_COLUMNS = {
    "search_first_aid_knowledge": "tool_rag_search",
    "locate_place": "tool_locate_place",
    "get_weather": "tool_get_weather",
    "get_current_time": "tool_get_current_time",
}

_REJECT = object()  # סימון "שדה זהות": ערך פסול דוחה את הרשומה כולה


@dataclass(frozen=True)
class Column:
    name: str
    sql: str                     # הגדרת העמודה ב-DDL, כולל אילוץ ה-CHECK
    scrub: Callable[[Any], Any]  # מאמת/מנקה ערך; זורק ValueError על פסול
    on_invalid: Any = _REJECT    # התחליף לערך פסול, או _REJECT לדחייה


# ── ולידטורים פר-סוג ─────────────────────────────────────────────────────
def _flag(value: Any) -> int:
    """דגל בוליאני -> 0/1 בלבד."""
    if isinstance(value, bool):
        return int(value)
    if value in (0, 1):
        return int(value)
    raise ValueError("לא דגל 0/1")


def _count(value: Any) -> int:
    """מונה: שלם אי-שלילי בלבד (לא bool, לא float, לא מחרוזת)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("לא מונה שלם אי-שלילי")
    return value


def _positive(value: Any) -> int:
    """שלם חיובי (turn_index מתחיל ב-1)."""
    count = _count(value)
    if count < 1:
        raise ValueError("נדרש שלם חיובי")
    return count


def _count_or_none(value: Any) -> int | None:
    return None if value is None else _count(value)


def _seconds_or_none(value: Any) -> float | None:
    """משך בשניות: מספר סופי אי-שלילי, מעוגל ל-3 ספרות; או None."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("לא משך בשניות")
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("משך שלילי או לא סופי")
    return round(seconds, 3)


def _pattern(regex: re.Pattern, *, optional: bool = False) -> Callable:
    """מחרוזת שחייבת להתאים במלואה לתבנית קשיחה (מזהים, חותם זמן)."""
    def check(value: Any):
        if value is None and optional:
            return None
        if isinstance(value, str) and regex.fullmatch(value):
            return value
        raise ValueError("ערך מחוץ לתבנית הקשיחה")
    return check


def _enum(allowed: tuple[str, ...], *, optional: bool = False) -> Callable:
    """מחרוזת מתוך אוצר-מילים סגור בלבד."""
    def check(value: Any):
        if value is None and optional:
            return None
        if isinstance(value, str) and value in allowed:
            return value
        raise ValueError("ערך מחוץ לאוצר המילים הסגור")
    return check


# ── הסכמה: כל עמודה עם אילוץ ה-SQL שלה והוולידטור המקביל בפייתון ────────
COLUMNS: tuple[Column, ...] = (
    Column("schema_version",
           "schema_version INTEGER NOT NULL CHECK (schema_version >= 1)",
           _positive, SCHEMA_VERSION),
    Column("ts_utc",
           "ts_utc TEXT NOT NULL CHECK (ts_utc GLOB "
           "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T"
           "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')",
           _pattern(_TS_RE)),
    Column("session_id",
           "session_id TEXT NOT NULL CHECK (length(session_id) = 32 "
           "AND session_id NOT GLOB '*[^0-9a-f]*')",
           _pattern(_SESSION_RE)),
    Column("turn_index",
           "turn_index INTEGER NOT NULL CHECK (turn_index >= 1)",
           _positive),
    Column("emergency",
           "emergency INTEGER NOT NULL CHECK (emergency IN (0, 1))",
           _flag, 0),
    Column("red_flags_count",
           "red_flags_count INTEGER NOT NULL CHECK (red_flags_count >= 0)",
           _count, 0),
    Column("consulted",
           "consulted INTEGER NOT NULL CHECK (consulted IN (0, 1))",
           _flag, 0),
    Column("consult_path",
           "consult_path TEXT NOT NULL "
           "CHECK (consult_path IN ('none', 'direct', 'crew'))",
           _enum(CONSULT_PATHS), "none"),
    Column("topic",
           "topic TEXT CHECK (topic IS NULL OR topic IN "
           "('wounds', 'anxiety', 'dehydration', 'cold', 'other'))",
           _enum(TOPICS, optional=True), None),
    Column("illustration_id",
           "illustration_id TEXT CHECK (illustration_id IS NULL OR "
           "(length(illustration_id) BETWEEN 1 AND 64 "
           "AND illustration_id NOT GLOB '*[^a-z0-9_]*'))",
           _pattern(_SLUG_RE, optional=True), None),
    Column("sources_count",
           "sources_count INTEGER NOT NULL CHECK (sources_count >= 0)",
           _count, 0),
    Column("filtered_sources_count",
           "filtered_sources_count INTEGER NOT NULL "
           "CHECK (filtered_sources_count >= 0)",
           _count, 0),
    Column("user_message_chars",
           "user_message_chars INTEGER CHECK (user_message_chars IS NULL "
           "OR user_message_chars >= 0)",
           _count_or_none, None),
    Column("reply_chars",
           "reply_chars INTEGER NOT NULL CHECK (reply_chars >= 0)",
           _count, 0),
    Column("llm_calls",
           "llm_calls INTEGER NOT NULL CHECK (llm_calls >= 0)",
           _count, 0),
    Column("t_safety_gate",
           "t_safety_gate REAL CHECK (t_safety_gate IS NULL OR t_safety_gate >= 0)",
           _seconds_or_none, None),
    Column("t_triage",
           "t_triage REAL CHECK (t_triage IS NULL OR t_triage >= 0)",
           _seconds_or_none, None),
    Column("t_consult",
           "t_consult REAL CHECK (t_consult IS NULL OR t_consult >= 0)",
           _seconds_or_none, None),
    Column("t_compose",
           "t_compose REAL CHECK (t_compose IS NULL OR t_compose >= 0)",
           _seconds_or_none, None),
    Column("t_total",
           "t_total REAL CHECK (t_total IS NULL OR t_total >= 0)",
           _seconds_or_none, None),
    Column("tool_rag_search",
           "tool_rag_search INTEGER NOT NULL CHECK (tool_rag_search >= 0)",
           _count, 0),
    Column("tool_locate_place",
           "tool_locate_place INTEGER NOT NULL CHECK (tool_locate_place >= 0)",
           _count, 0),
    Column("tool_get_weather",
           "tool_get_weather INTEGER NOT NULL CHECK (tool_get_weather >= 0)",
           _count, 0),
    Column("tool_get_current_time",
           "tool_get_current_time INTEGER NOT NULL "
           "CHECK (tool_get_current_time >= 0)",
           _count, 0),
    Column("tools_other",
           "tools_other INTEGER NOT NULL CHECK (tools_other >= 0)",
           _count, 0),
    # דגל שכבת הראייה: האם התור כלל תמונה שצורפה ע"י המשתמש. **דגל
    # בלבד** — אין כאן שום נתון מהתמונה עצמה (לא ממדים, לא מדידות, לא
    # תיאור), בדיוק כמו ששאר הטקסטים מצטמצמים לאורכים. הפרטיות נשמרת:
    # מהערך 1 אי אפשר ללמוד דבר על התמונה או על מי שצילם אותה.
    # מוגדר אחרון בכוונה: ALTER TABLE ADD COLUMN מוסיף בסוף, וכך הסדר
    # בקובץ שעבר מיגרציה זהה לסדר בקובץ שנוצר מאפס.
    # DEFAULT 0 הוא גם דרישה של SQLite ל-ADD COLUMN עם NOT NULL.
    Column("image_attached",
           "image_attached INTEGER NOT NULL DEFAULT 0 "
           "CHECK (image_attached IN (0, 1))",
           _flag, 0),
)

COLUMN_NAMES: tuple[str, ...] = tuple(column.name for column in COLUMNS)

_CREATE_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS turns (\n"
    "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n    "
    + ",\n    ".join(column.sql for column in COLUMNS)
    + "\n)"
)
_CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_turns_ts ON turns (ts_utc)",
    "CREATE INDEX IF NOT EXISTS idx_turns_session ON turns (session_id)",
)
_INSERT_SQL = "INSERT INTO turns ({}) VALUES ({})".format(
    ", ".join(COLUMN_NAMES), ", ".join("?" for _ in COLUMN_NAMES),
)


def _resolve_db_path(db_path: str | Path | None = None) -> Path:
    """
    נתיב קובץ ה-SQLite: פרמטר מפורש > ANNE_LOG_DB > ברירת המחדל.

    נשאר כאן כשם מקומי (וכנקודת עיגון לקוראים ותיקים) אחרי שהמימוש עבר
    ל-backend.sqlite_path_for — שם הוא משותף גם לפענוח היעד וגם לנפילה
    החיננית, כדי שלא יהיו שתי דרכים שונות לבחור את אותו קובץ.
    """
    return sqlite_path_for(db_path)


def _target(db_path: str | Path | None = None) -> Target:
    """
    היעד בפועל לפעולה הזו — נקודת הפענוח **היחידה** של כל הפונקציות כאן.

    במצב Supabase נבדק כאן גם שהחיבור והטבלה מוכנים (פעם אחת בתהליך);
    כשל בהגדרות, בחבילות או בחיבור מוחזר כיעד SQLite עם אזהרה אחת ללוג —
    כך שאף קורא לא צריך לדעת על שני ה-backends, ותקלה בענן אינה יכולה
    להפיל שיחה. הייבוא של supabase_backend עצל בכוונה: הוא גורר את
    SQLAlchemy, ו-`import storage` חייב לעבוד גם בלעדיו.
    """
    target = resolve_target(db_path)
    if not target.is_supabase:
        return target
    try:
        from . import supabase_backend

        supabase_backend.ensure_ready(target)
        return target
    except Exception as exc:
        return fallback_to_sqlite(f"{type(exc).__name__}: {exc}",
                                  db_path=db_path, table=target.table)


def _sqlite_conn(path: Path) -> sqlite3.Connection:
    """חיבור SQLite לקובץ נתון (אחרי שהטבלה כבר הוקמה)."""
    return sqlite3.connect(path, timeout=5.0)


def _migrate(conn: sqlite3.Connection) -> list[str]:
    """
    השלמת עמודות שנוספו לסכמה אחרי שהקובץ כבר נוצר.

    CREATE TABLE IF NOT EXISTS אינו נוגע בטבלה קיימת, ולכן בלי המעבר הזה
    קובץ לוג ותיק היה נשבר בכתיבה הראשונה אחרי הוספת עמודה ("no such
    column"). כאן משווים את הסכמה בפועל להצהרה ומוסיפים את החסר — פעולה
    אידמפוטנטית וזולה (PRAGMA + ALTER רק כשצריך). כל עמודה חדשה חייבת
    לכלול DEFAULT כשהיא NOT NULL — מגבלת ALTER TABLE של SQLite.
    מחזיר את שמות העמודות שנוספו (לדיווח/בדיקה).
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(turns)")}
    if not existing:
        return []
    added = []
    for column in COLUMNS:
        if column.name in existing:
            continue
        conn.execute(f"ALTER TABLE turns ADD COLUMN {column.sql}")
        added.append(column.name)
    return added


def _init_sqlite(path: Path) -> Path:
    """יצירת קובץ ה-SQLite, הטבלה והאינדקסים אם אינם קיימים."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _sqlite_conn(path)
    try:
        with conn:
            conn.execute(_CREATE_TABLE_SQL)
            _migrate(conn)          # קובץ קיים מגרסה קודמת של הסכמה
            for statement in _CREATE_INDEX_SQL:
                conn.execute(statement)
    finally:
        conn.close()
    return path


def init_db(db_path: str | Path | None = None) -> Path | str:
    """
    יצירת הלוג אם אינו קיים (אידמפוטנטי). מחזיר את זהות היעד בפועל.

    ב-SQLite זהו נתיב הקובץ (כמו קודם); ב-Supabase שם הטבלה — ולכן
    ``Path | str``. מי שצריך את היעד המלא (backend + טבלה + נתיב) יקרא
    ל-resolve_target/describe_target.
    """
    target = _target(db_path)
    if target.is_supabase:
        return target.table
    return _init_sqlite(target.path)


def scrub_record(record: dict) -> dict:
    """
    שכבת הביטחון שלפני הכתיבה: כל עמודה עוברת את הוולידטור שלה.

    ערך פסול בעמודת תוכן -> ברירת המחדל הבטוחה שלה (None/0/'none');
    ערך פסול בשדה זהות (ts_utc / session_id / turn_index) -> ValueError
    והרשומה כולה נדחית. מפתחות שאינם בסכמה נזרקים — טקסט חופשי לא יכול
    להיכנס גם דרך מפתח "חדש" ברשומה.
    """
    clean: dict[str, Any] = {}
    for column in COLUMNS:
        raw = record.get(column.name)
        try:
            clean[column.name] = column.scrub(raw)
        except ValueError:
            if column.on_invalid is _REJECT:
                raise ValueError(f"שדה חובה פסול בלוג: {column.name}") from None
            clean[column.name] = column.on_invalid
    return clean


def record_from_turn(
    result: Any,
    *,
    session_id: str,
    turn_index: int,
    user_message: str | None = None,
    ts_utc: str | None = None,
) -> dict:
    """
    גזירת רשומת לוג מובנית מ-TurnResult (crew/pipeline.py) — בלי טקסט חופשי:
    הטקסטים נגזרים לאורכים בלבד, הרשימות למונים, ומוני הכלים ממופים לעמודות
    הסגורות. הגישה duck-typed (getattr) בכוונה — עובדת גם על אובייקט דמה
    בבדיקות, בלי ש-storage ייבא את crew (שגורר את crewai).

    consult_path מתעד את מסלול הייעוץ שנוסה (לפי מפתחות ה-timings) גם כשהוא
    נכשל טכנית — יחד עם consulted (הצלחה בפועל) מבחינים בין "לא נועץ" לבין
    "נועץ ונפל ל-fallback". ts_utc ניתן לקיבוע (לדאטה סינתטי ולבדיקות).
    """
    timings = dict(getattr(result, "timings", None) or {})
    tool_usage = dict(getattr(result, "tool_usage", None) or {})

    if "consult_direct" in timings:
        consult_path, t_consult = "direct", timings.get("consult_direct")
    elif "consult_crew" in timings:
        consult_path, t_consult = "crew", timings.get("consult_crew")
    else:
        consult_path, t_consult = "none", None

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ts_utc": ts_utc
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": session_id,
        "turn_index": turn_index,
        "emergency": bool(getattr(result, "emergency", False)),
        "red_flags_count": len(getattr(result, "red_flags", None) or []),
        "consulted": bool(getattr(result, "consulted", False)),
        "consult_path": consult_path,
        "topic": getattr(result, "topic", None),
        "illustration_id": getattr(result, "illustration_id", None),
        "sources_count": len(getattr(result, "sources", None) or []),
        "filtered_sources_count": len(
            getattr(result, "filtered_sources", None) or []
        ),
        "user_message_chars": None if user_message is None else len(user_message),
        "reply_chars": len(getattr(result, "reply_he", None) or ""),
        "llm_calls": getattr(result, "llm_calls", 0),
        # שכבת הראייה: דגל בלבד (0/1), בלי שום נתון מהתמונה.
        "image_attached": bool(getattr(result, "image_used", False)),
        "t_safety_gate": timings.get("safety_gate"),
        "t_triage": timings.get("triage"),
        "t_consult": t_consult,
        "t_compose": timings.get("compose"),
        "t_total": timings.get("total"),
        "tools_other": 0,
    }
    for column_name in TOOL_COLUMNS.values():
        record[column_name] = 0
    for tool_name, calls in tool_usage.items():
        if isinstance(calls, bool) or not isinstance(calls, int) or calls <= 0:
            continue
        record[TOOL_COLUMNS.get(tool_name, "tools_other")] += calls
    return record


def write_record(record: dict, db_path: str | Path | None = None) -> None:
    """
    כתיבת רשומה בודדת ללוג — תמיד דרך scrub_record; אין מסלול כתיבה עוקף.

    קפדני בכוונה (זורק על שדה זהות פסול או כשל DB) — למחולל הדאטה הסינתטי
    ולבדיקות, שם כשל צריך להיות רועש. ה-pipeline משתמש ב-log_turn הסלחני.
    הכנת היעד בכל כתיבה זולה (CREATE IF NOT EXISTS ב-SQLite, ובדיקה
    מוטמעת בתהליך ב-Supabase) והופכת את הלוג ל"מרפא-עצמו" אם הקובץ נמחק
    תוך כדי ריצה.
    """
    write_records([record], db_path=db_path)


def write_records(
    records: Iterable[dict], db_path: str | Path | None = None
) -> int:
    """
    כתיבת רשומות רבות בטרנזקציה אחת. מחזיר כמה נכתבו.

    כל הרשומות עוברות scrub_record **לפני** שנפתח חיבור: רשומה פסולה
    נכשלת רועש ולא משאירה כתיבה חלקית. במחולל הדאטה הסינתטי זה גם שיפור
    מהותי — קודם נפתח חיבור לכל רשומה, ומול Postgres מרוחק זה היה 500
    הלוך-חזור לזריעה אחת.
    """
    clean = [scrub_record(record) for record in records]
    if not clean:
        return 0
    target = _target(db_path)
    if target.is_supabase:
        try:
            from . import supabase_backend

            return supabase_backend.insert_records(target, clean)
        except Exception as exc:
            target = fallback_to_sqlite(f"{type(exc).__name__}: {exc}",
                                        db_path=db_path, table=target.table)
    path = _init_sqlite(target.path)
    conn = _sqlite_conn(path)
    try:
        with conn:
            conn.executemany(
                _INSERT_SQL,
                [tuple(row[name] for name in COLUMN_NAMES) for row in clean],
            )
    finally:
        conn.close()
    return len(clean)


def log_turn(
    result: Any,
    *,
    session_id: str,
    turn_index: int,
    user_message: str | None = None,
    ts_utc: str | None = None,
    db_path: str | Path | None = None,
) -> bool:
    """
    רישום תור-שיחה אחד מ-TurnResult — נקודת הכניסה של ה-pipeline.

    best-effort במוצהר: כל חריגה (רשומה פסולה, דיסק נעול, נתיב שבור,
    Supabase שאינו מגיב) נבלעת ומוחזר False — הלוג לעולם לא מפיל את
    השיחה. הצלחה -> True. שימו לב שכשל Supabase כבר טופל שכבה אחת
    למטה (נפילה חיננית ל-SQLite), ולכן False כאן מסמן בעיה ברשומה או
    בדיסק המקומי, לא בענן.
    """
    try:
        record = record_from_turn(
            result,
            session_id=session_id,
            turn_index=turn_index,
            user_message=user_message,
            ts_utc=ts_utc,
        )
        write_record(record, db_path=db_path)
        return True
    except Exception:
        return False


def reset_log(db_path: str | Path | None = None) -> int:
    """
    מחיקת כל הרשומות (כפתור המנהל בדשבורד). מחזיר כמה רשומות נמחקו.

    ב-SQLite מריצים VACUUM אחרי המחיקה — מכווץ את הקובץ, כלומר מחיקה
    פיזית ולא רק סימון עמודים פנויים. ב-Postgres אין מה לעשות מקבילית:
    autovacuum מטפל בשטח בעצמו, ו-VACUUM שם אינו נתמך בתוך טרנזקציה.
    """
    target = _target(db_path)
    if target.is_supabase:
        try:
            from . import supabase_backend

            return supabase_backend.delete_all(target)
        except Exception as exc:
            target = fallback_to_sqlite(f"{type(exc).__name__}: {exc}",
                                        db_path=db_path, table=target.table)
    path = _init_sqlite(target.path)
    conn = _sqlite_conn(path)
    try:
        with conn:
            (before,) = conn.execute("SELECT COUNT(*) FROM turns").fetchone()
            conn.execute("DELETE FROM turns")
        conn.execute("VACUUM")
        return int(before)
    finally:
        conn.close()


def fetch_turns(
    db_path: str | Path | None = None, limit: int | None = None
) -> list[dict]:
    """קריאת רשומות הלוג בסדר כרונולוגי (לבדיקות, לדשבורד ולמודל החיזוי)."""
    target = _target(db_path)
    if target.is_supabase:
        try:
            from . import supabase_backend

            return supabase_backend.fetch_records(target, limit)
        except Exception as exc:
            target = fallback_to_sqlite(f"{type(exc).__name__}: {exc}",
                                        db_path=db_path, table=target.table)
    path = _init_sqlite(target.path)
    conn = _sqlite_conn(path)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM turns ORDER BY id"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return [dict(row) for row in conn.execute(sql)]
    finally:
        conn.close()
