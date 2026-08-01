"""
מתג ה-backend של לוג השיחות: SQLite מקומי או Postgres של Supabase.

זו שכבה **מתחת** ל-API הקיים ולא לצידו: turn_log.py ממשיך לחשוף את אותן
פונקציות עם אותן חתימות (init_db / log_turn / write_record / fetch_turns /
reset_log), והמודול הזה קובע רק *לאן* הן כותבות וקוראות. אין כאן שום
sqlalchemy ואין שום קריאת רשת — המודול הוא קונפיגורציה טהורה (ולכן גם
עלה בגרף הייבוא: turn_log מייבא אותו, והוא אינו מייבא כלום מהפרויקט).

**המתג** (משתני סביבה, נטענים מ-.env):
    ANNE_LOG_BACKEND=sqlite|supabase   ברירת מחדל: sqlite
    ANNE_LOG_TABLE=turns|turns_synthetic   הטבלה כשלא נמסר יעד מפורש
    SUPABASE_DB_URL                    מחרוזת החיבור (Postgres) — חובה
    SUPABASE_DB_URL_POOLER             אופציונלי: pooler כגיבוי לישיר
    SUPABASE_URL / SUPABASE_SERVICE_KEY  זהות הפרויקט (לא בשימוש בשכבה
                                       הזו, שמתחברת ישירות ב-Postgres)

**נפילה חיננית — העיקרון המרכזי כאן.** הגדרות חסרות, חבילה חסרה או חיבור
שנכשל לעולם אינם מפילים את הצ'אט: הם רק מחזירים את הלוג ל-SQLite המקומי,
עם אזהרה אחת ללוג (`logging`, ולא print — כדי שהיא לא תיפול לתוך תשובת
אן בטרמינל). הנפילה **דביקה לכל התהליך** בכוונה: תור שמחכה 5 שניות
לטיים-אאוט בכל הודעה גרוע יותר מלוג מקומי מוצהר, ועליית התהליך הבאה
מנסה את Supabase מחדש. `describe_target` מדווח את המצב *בפועל*, כך
שהדשבורד לא יכול להציג "Supabase" בזמן שהנתונים נקראים מקובץ מקומי.

**היעד (Target) הוא "איזה דאטה", לא "איזה קובץ".** אותו פרמטר db_path
שהיה נתיב קובץ מקבל כאן משמעות רחבה יותר: נתיב (SQLite) *או* שם טבלה
מהרשימה הסגורה (Supabase). כך המתג "חי / סינתטי" בדשבורד בוחר טבלה בלי
להחליף חיבור, ובלי לשנות אף חתימה: קובץ ששמו מכיל synthetic ממופה
ל-turns_synthetic, ולהפך — שם טבלה שנמסר במצב SQLite ממופה לקובץ
ברירת המחדל של אותו מצב. שם טבלה מחוץ לרשימה הסגורה נדחה (הוא נכנס
ל-SQL כמזהה, שאי אפשר לפרמטר) וחוזרים לברירת המחדל, עם אזהרה.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── נתיבי ה-SQLite (מקור אמת אחד; turn_log ו-synthetic מייבאים מכאן) ─────
DEFAULT_DB_PATH = PROJECT_ROOT / "anne_log.db"
SYNTHETIC_DB_PATH = PROJECT_ROOT / "anne_log_synthetic.db"

# ── שמות משתני הסביבה ────────────────────────────────────────────────────
ENV_DB_VAR = "ANNE_LOG_DB"                 # עקיפת נתיב קובץ ה-SQLite
ENV_BACKEND_VAR = "ANNE_LOG_BACKEND"
ENV_TABLE_VAR = "ANNE_LOG_TABLE"
ENV_DB_URL_VAR = "SUPABASE_DB_URL"
ENV_POOLER_URL_VAR = "SUPABASE_DB_URL_POOLER"
ENV_PROJECT_URL_VAR = "SUPABASE_URL"
ENV_SERVICE_KEY_VAR = "SUPABASE_SERVICE_KEY"

# ── ה-backends ואוצר המילים הסגור של הטבלאות ─────────────────────────────
BACKEND_SQLITE = "sqlite"
BACKEND_SUPABASE = "supabase"
BACKENDS = (BACKEND_SQLITE, BACKEND_SUPABASE)
DEFAULT_BACKEND = BACKEND_SQLITE

LIVE_TABLE = "turns"
SYNTHETIC_TABLE = "turns_synthetic"
TABLES = (LIVE_TABLE, SYNTHETIC_TABLE)

# הטבלה המקבילה לכל קובץ SQLite ולהפך — שני המצבים ממופים אחד לאחד, כדי
# שאותו db_path יעבוד בשני ה-backends בלי שהקורא יידע באיזה מהם הוא רץ.
_TABLE_TO_PATH = {LIVE_TABLE: DEFAULT_DB_PATH, SYNTHETIC_TABLE: SYNTHETIC_DB_PATH}

logger = logging.getLogger("anne.storage")

# מצב הנפילה החיננית: הסיבה (עברית) אם התהליך הזה חזר ל-SQLite, אחרת None.
_fallback_reason: str | None = None
_warned: set[str] = set()


def _load_env_file() -> None:
    """
    טעינת .env — כדי שהמתג יעבוד גם בהרצות שאינן טוענות אותו בעצמן.

    השרת ושכבת ה-LLM קוראות ל-load_dotenv, אבל `streamlit run` ו-
    `python -m storage.synthetic` לא — ובלי זה ANNE_LOG_BACKEND שב-.env
    לא היה נראה שם כלל. python-dotenv כבר תלות מוצהרת של הפרויקט;
    בהיעדרו פשוט מסתמכים על משתני הסביבה עצמם (ולכן try/except ולא ייבוא
    קשיח — שכבת ה-SQLite חייבת להמשיך לעבוד עם ספריית התקן לבדה).
    load_dotenv אינו דורס משתנה שכבר קיים בסביבה, ולכן הרצה שמקבעת
    ANNE_LOG_BACKEND=sqlite (סוללת הבדיקות) גוברת על הקובץ.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:
        pass


_load_env_file()


@dataclass(frozen=True)
class Target:
    """
    יעד הכתיבה/הקריאה של תור: איזה backend, איזו טבלה, ואיזה קובץ.

    path מאוכלס ב-SQLite בלבד; table מאוכלס תמיד (ב-SQLite הטבלה היא
    turns בכל קובץ — ההפרדה בין "חי" ל"סינתטי" שם היא בין *קבצים*).
    """

    backend: str
    table: str
    path: Path | None = None

    @property
    def is_supabase(self) -> bool:
        return self.backend == BACKEND_SUPABASE

    @property
    def is_synthetic(self) -> bool:
        """האם זה הדאטה הסינתטי (טבלה סינתטית או קובץ ששמו מכיל synthetic)."""
        if self.is_supabase:
            return self.table == SYNTHETIC_TABLE
        return is_synthetic_name(self.path or "")

    @property
    def label(self) -> str:
        """תווית קצרה לתצוגה: שם הקובץ או שם הטבלה."""
        return self.table if self.is_supabase else Path(self.path or "").name


def is_synthetic_name(target: str | Path) -> bool:
    """האם היעד (קובץ או טבלה) הוא הדאטה הסינתטי — לפי שמו."""
    return "synthetic" in Path(str(target)).name.lower()


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def requested_backend() -> str:
    """
    ה-backend שהתבקש ב-.env (ולא בהכרח זה שרץ בפועל — ראה active_backend).

    ערך לא מוכר אינו שגיאה שמפילה כלום: הוא נרשם כאזהרה וחוזרים ל-sqlite.
    """
    raw = _env(ENV_BACKEND_VAR).lower()
    if not raw:
        return DEFAULT_BACKEND
    if raw in BACKENDS:
        return raw
    warn_once(
        f"בחירת backend לא מוכרת ללוג: {ENV_BACKEND_VAR}={raw!r}. "
        f"האפשרויות הן {' / '.join(BACKENDS)} — ממשיכים עם {DEFAULT_BACKEND}."
    )
    return DEFAULT_BACKEND


def active_backend() -> str:
    """ה-backend שרץ בפועל: הבקשה מ-.env, אלא אם התהליך כבר נפל ל-SQLite."""
    if _fallback_reason is not None:
        return BACKEND_SQLITE
    return requested_backend()


def supabase_settings() -> dict[str, str]:
    """הגדרות Supabase מהסביבה (מחרוזות ריקות כשאינן מוגדרות)."""
    return {
        "db_url": _env(ENV_DB_URL_VAR),
        "pooler_url": _env(ENV_POOLER_URL_VAR),
        "project_url": _env(ENV_PROJECT_URL_VAR),
        "service_key": _env(ENV_SERVICE_KEY_VAR),
    }


def missing_supabase_settings() -> list[str]:
    """
    שמות המשתנים החסרים כדי להתחבר ל-Supabase — רשימה ריקה = הכול מוגדר.

    לחיבור עצמו נדרש SUPABASE_DB_URL בלבד: השכבה הזו מדברת Postgres ישר,
    ולא דרך ה-REST API. SUPABASE_URL ו-SUPABASE_SERVICE_KEY מוצהרים
    ב-.env כזהות הפרויקט (ולשלבים הבאים, כמו ניהול המשתמשים) ולכן אינם
    נדרשים כאן — הצהרה כזו עדיפה על העמדת פנים שהמפתח בשימוש.
    """
    settings = supabase_settings()
    return [ENV_DB_URL_VAR] if not settings["db_url"] else []


# ── פענוח היעד ───────────────────────────────────────────────────────────
def _table_from_env() -> str:
    """הטבלה שהוגדרה ב-ANNE_LOG_TABLE, או טבלת הלוג החי כברירת מחדל."""
    raw = _env(ENV_TABLE_VAR)
    if not raw:
        return LIVE_TABLE
    if raw in TABLES:
        return raw
    warn_once(
        f"שם טבלה לא מוכר בלוג: {ENV_TABLE_VAR}={raw!r}. "
        f"האפשרויות הן {' / '.join(TABLES)} — ממשיכים עם {LIVE_TABLE}."
    )
    return LIVE_TABLE


def table_for(target: str | Path | None) -> str:
    """
    שם הטבלה עבור יעד כלשהו — תמיד מתוך הרשימה הסגורה.

    None -> ANNE_LOG_TABLE (או turns); שם טבלה חוקי -> הוא עצמו; כל דבר
    אחר מטופל כנתיב קובץ, ושמו קובע: 'synthetic' -> turns_synthetic,
    אחרת turns. ערך חשוד (טקסט חופשי, נתיב לא-מזוהה עם שם טבלה) אינו
    נכנס ל-SQL: שם הטבלה הוא מזהה ואי אפשר לפרמטר אותו, ולכן הרשימה
    הסגורה כאן היא גם הגנת ההזרקה.
    """
    if target is None:
        return _table_from_env()
    raw = str(target).strip()
    if raw in TABLES:
        return raw
    return SYNTHETIC_TABLE if is_synthetic_name(raw) else LIVE_TABLE


def sqlite_path_for(target: str | Path | None) -> Path:
    """
    נתיב קובץ ה-SQLite עבור יעד כלשהו: פרמטר מפורש > ANNE_LOG_DB > ברירת מחדל.

    שם טבלה שנמסר במצב SQLite (למשל אחרי נפילה חיננית, או כשהמתג
    בדשבורד עבר לטבלה הסינתטית) ממופה לקובץ המקביל — כך אותו db_path
    משמעותי בשני ה-backends. ``turns`` (הלוג החי) מתפרש בדיוק כמו None,
    כלומר **מכבד את ANNE_LOG_DB**: אחרת נפילה חיננית הייתה כותבת לקובץ
    ברירת המחדל בזמן שהקריאה נעשית מהקובץ שהוגדר בסביבה, ושתי הפעולות
    היו סותרות זו את זו (בדיוק מה שקרה בבדיקה הראשונה).
    """
    if target is not None:
        raw = str(target).strip()
        if raw == SYNTHETIC_TABLE:
            return _TABLE_TO_PATH[SYNTHETIC_TABLE]
        if raw != LIVE_TABLE:
            return Path(target)
    env_path = _env(ENV_DB_VAR)
    return Path(env_path) if env_path else DEFAULT_DB_PATH


def resolve_target(db_path: str | Path | None = None) -> Target:
    """היעד בפועל עבור db_path — כולל נפילה חיננית שכבר קרתה בתהליך הזה."""
    if active_backend() == BACKEND_SUPABASE:
        return Target(BACKEND_SUPABASE, table_for(db_path))
    return Target(BACKEND_SQLITE, LIVE_TABLE, sqlite_path_for(db_path))


def describe_target(db_path: str | Path | None = None) -> str:
    """תיאור קריא של היעד בפועל — לדיווח למשתמש (CLI, כיתוב בדשבורד)."""
    target = resolve_target(db_path)
    if target.is_supabase:
        return f"Supabase (Postgres) · טבלה {target.table}"
    suffix = " (נפילה חיננית מ-Supabase)" if _fallback_reason else ""
    return f"SQLite · {target.label}{suffix}"


# ── אזהרות ונפילה חיננית ─────────────────────────────────────────────────
def warn_once(message: str) -> None:
    """אזהרה ללוג, פעם אחת לכל נוסח — כדי שתור אחרי תור לא יציף את המסך."""
    if message in _warned:
        return
    _warned.add(message)
    logger.warning(message)


def fallback_to_sqlite(
    reason: object,
    db_path: str | Path | None = None,
    table: str = LIVE_TABLE,
) -> Target:
    """
    מעבר ל-SQLite המקומי בעקבות כשל — עם אזהרה, בלי חריגה, ולכל התהליך.

    reason הוא הודעה או חריגה; היא נכנסת לאזהרה כפי שהיא. **אין כאן שום
    מחרוזת חיבור**: מי שמייצר את הסיבה אחראי להסתיר את הסיסמה
    (supabase_backend.safe_display_url) — סוד לא נכנס ללוג.

    הקובץ נבחר דרך sqlite_path_for — אותה פונקציה שמפענחת יעד רגיל, ולא
    מיפוי מקביל. זה לא ניקיון לשמו: בגרסה הראשונה הנפילה מיפתה טבלה
    לקובץ ברירת המחדל והתעלמה מ-ANNE_LOG_DB, כך שהתור הראשון אחרי הכשל
    נכתב לקובץ אחר מזה שממנו קראו — ושתי הקריאות סתרו זו את זו.
    """
    global _fallback_reason
    text = str(reason).strip() or "כשל לא מזוהה"
    if _fallback_reason is None:
        _fallback_reason = text
        warn_once(
            f"לוג השיחות חוזר ל-SQLite המקומי: {text}. "
            "השיחה נמשכת כרגיל והתורים נרשמים מקומית; "
            "לחזרה ל-Supabase תקנו את ההגדרות והריצו מחדש."
        )
    path = sqlite_path_for(db_path if db_path is not None else table)
    return Target(BACKEND_SQLITE, LIVE_TABLE, path)


def fallback_reason() -> str | None:
    """הסיבה שהתהליך חזר ל-SQLite, או None אם לא חזר."""
    return _fallback_reason


def reset_backend_state() -> None:
    """איפוס מצב הנפילה והאזהרות — לבדיקות בלבד (ולריצות ארוכות בכוונה)."""
    global _fallback_reason
    _fallback_reason = None
    _warned.clear()
