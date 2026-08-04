"""
שער הפעולות המנהליות של אפליקציות ה-Streamlit (איפוס הלוג, אימון מודל).

הרקע: שתי האפליקציות נפרסות כאפליקציות **ציבוריות** — כל מי שיש לו את
הקישור פותח אותן, בלי התחברות. לכן כל פעולה שכותבת, מוחקת או מאמנת
חייבת שער. הכפתור "מחיקת כל הרשומות" קורא ל-storage.reset_log, ובמצב
Supabase הוא מוחק את הטבלה **בענן** — כלומר בלי שער, מבקר אנונימי היה
יכול למחוק את כל נתוני הפרויקט מהדפדפן.

העיקרון: **נעול כברירת מחדל.** אין כאן זיהוי סביבה שמנסה לנחש "האם אני
רץ מקומית", מפני שניחוש כזה נכשל *פתוח* ביום שבו הסימן שעליו הוא נשען
משתנה או חסר — וכשל פתוח בפעולה מוחקת הוא בדיוק מה שאסור. גם כותרת
Host אינה קובעת כאן דבר: היא נשלחת מהדפדפן וניתנת לזיוף.

במקום זה ההרשאה נשענת על דבר אחד שקיים מקומית ולא קיים בענן: קוד מנהל
ב-.env, שאינו בבקרת גרסאות ולכן פשוט אינו קיים בקונטיינר הציבורי. אין
קוד מוגדר -> הפעולה **אינה קיימת בממשק** (לא כפתור, לא תיבת אישור וגם
לא הכרטיס שעוטף אותם) — לא "מוסתרת" ולא "מנוטרלת".

זו אותה החלטת תכנון של אזור המנהל בשרת (ADMIN_EMAIL / ADMIN_PASSWORD
ב-.env, בלי ברירת מחדל שמאפשרת כניסה): מקור סודות אחד, בהיקף אחד.

הערה על Streamlit Cloud: סודות שמוזנים במסך ההגדרות זמינים כמשתני סביבה
**רק ברמת השורש** של secrets.toml (מפתח בתוך [section] אינו הופך למשתנה
סביבה). המודול קורא os.getenv בלבד ולכן אינו מייבא streamlit — וגם אין
בו st.secrets. כך שכבת המדיניות נבדקת ישירות בסוללה, בלי שרת ובלי דפדפן.

הציור יושב ב-dashboard/ui.py :: admin_gate — כאן רק ההחלטה.
"""
from __future__ import annotations

import logging
import os
import secrets
import unicodedata
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── משתני הסביבה ─────────────────────────────────────────────────────────
ENV_CODE_VAR = "ANNE_DASHBOARD_ADMIN_CODE"   # הקוד עצמו; אין ברירת מחדל
ENV_PUBLIC_VAR = "ANNE_PUBLIC_DEPLOY"        # הצהרת המפעיל: זו פריסה ציבורית

# אורך מינימלי לקוד. קוד בן שני תווים על אפליקציה ציבורית אינו הגנה, ולכן
# קוד קצר מדי נחשב **תקלת הגדרה** ולא "קוד שגוי": הפעולה אינה מוצגת, ובריצה
# מקומית מוצגת הודעה שאומרת בדיוק מה לתקן (אותו שיעור כמו 503 "לא הוגדרו
# פרטי כניסה" בשרת — למי שמקליד עדיף להבין שלא הוגדר קוד מלנחש סיסמה).
MIN_CODE_LENGTH = 8

# סימני פריסה ציבורית. זו **חגורה שיכולה רק לסגור** ולעולם לא לפתוח: גם אם
# קוד כן הוגדר בטעות בסודות של הענן, פעולה מוחקת לא תופיע על כתובת ציבורית.
# /mount/src הוא שורש ה-checkout של Streamlit Community Cloud.
CLOUD_PATH_MARKERS = ("/mount/src",)
_TRUTHY = {"1", "true", "yes", "on", "כן"}

logger = logging.getLogger("anne.dashboard")
_warned: set[str] = set()


def _load_env_file() -> None:
    """
    טעינת .env — `streamlit run` אינו טוען אותו בעצמו.

    אותו דפוס (ואותה סיבה) כמו ב-storage/backend.py: בלי זה הקוד שב-.env
    לא היה נראה לאפליקציה כלל. load_dotenv אינו דורס משתנה שכבר קיים
    בסביבה, ולכן ריצה שמקבעת ערך (סוללת הבדיקות) גוברת על הקובץ.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:
        pass


_load_env_file()


@dataclass(frozen=True)
class AdminAccess:
    """
    מצב השער עבור פעולה מנהלית אחת.

    available — האם לצייר את הפעולה **בכלל** (False = לא מצויר כלום).
    unlocked  — האם הפעולה מותרת עכשיו (גורר available).
    public    — האם זוהתה פריסה ציבורית (ואז אין מציגים אפילו אבחון).
    mode      — הסיבה, לצורכי בדיקה ואבחון.
    notice_he — מה להציג למפעיל בריצה שאינה ציבורית (ריק = אין מה להציג).
    """

    available: bool
    unlocked: bool
    public: bool
    mode: str
    notice_he: str = ""


def _normalize(value: str | None) -> str:
    """
    ניקוי הקוד לפני השוואה: רווחים בקצוות ותווי עיצוב סמויים.

    בדף RTL נדבקים להדבקה סימני כיווניות (RLM/LRM) ש-str.strip אינו מסיר,
    והם הפכו בעבר פרטי כניסה נכונים לכשל שנראה כמו "סיסמה שגויה"
    (ראה server/app.py :: _normalize_credential). כאן מוסרת כל קטגוריית
    Cf, ולא רק שני התווים שנתקלנו בהם.

    **הסדר קובע**: קודם מסירים את תווי ה-Cf ורק אחר כך strip. הדבקה
    אמיתית מייצרת "<RLM> <קוד> <LRM>" — סימן הכיווניות אינו whitespace
    ולכן strip נעצר עליו ומשאיר את הרווח שאחריו בתוך הערך. הסדר ההפוך
    נכתב כאן קודם, והבדיקה על ההדבקה הזו היא שתפסה אותו.
    """
    if not value:
        return ""
    cleaned = "".join(
        ch for ch in value if unicodedata.category(ch) != "Cf"
    )
    return cleaned.strip()


def admin_code() -> str:
    """הקוד המוגדר בסביבה (.env מקומי או סוד ברמת השורש), אחרי נרמול."""
    return _normalize(os.getenv(ENV_CODE_VAR))


def public_deployment() -> str:
    """
    הסיבה שזו פריסה ציבורית, או מחרוזת ריקה כשלא זוהתה כזו.

    שני סימנים: הצהרה מפורשת של המפעיל (ANNE_PUBLIC_DEPLOY=1 — שימושי
    גם לשרת פרטי כלשהו, לא רק ל-Streamlit Cloud), ונתיב ה-checkout של
    Streamlit Community Cloud. שים לב שהיעדר שניהם **אינו** מוכיח ריצה
    מקומית ואינו פותח דבר: הפתיחה תלויה בקוד בלבד.
    """
    if _normalize(os.getenv(ENV_PUBLIC_VAR)).lower() in _TRUTHY:
        return f"פריסה ציבורית לפי {ENV_PUBLIC_VAR}"
    here = str(PROJECT_ROOT)
    for marker in CLOUD_PATH_MARKERS:
        if here.startswith(marker):
            return "פריסה ציבורית (Streamlit Cloud)"
    return ""


def _warn_once(message: str) -> None:
    if message not in _warned:
        _warned.add(message)
        logger.warning(message)


def access_state(entered: str | None = None) -> AdminAccess:
    """
    ההחלטה כולה, במקום אחד: האם לצייר את הפעולה, והאם היא מותרת.

    סדר הבדיקות הוא סדר החומרה, וכל אחת מהן **סוגרת**:
      1. פריסה ציבורית -> לא זמין, גם אם הוגדר קוד (החגורה).
      2. אין קוד מוגדר -> לא זמין (זה המצב בענן, כי .env אינו שם).
      3. קוד קצר מ-MIN_CODE_LENGTH -> לא זמין, ובריצה מקומית עם הסבר.
      4. יש קוד -> זמין; מותר רק אם מה שהוקלד תואם.
    """
    public_reason = public_deployment()
    code = admin_code()

    if public_reason:
        if code:
            _warn_once(
                "קוד מנהל הוגדר בסביבה, אך זוהתה פריסה ציבורית — הפעולות "
                "המנהליות (איפוס הלוג, אימון מודל) חסומות. הסירו את "
                f"{ENV_CODE_VAR} מהסודות של הפריסה."
            )
        return AdminAccess(
            available=False, unlocked=False, public=True,
            mode="locked_public", notice_he="",
        )

    if not code:
        return AdminAccess(
            available=False, unlocked=False, public=False,
            mode="not_configured",
            notice_he=(
                "פעולות מנהליות (איפוס הלוג, אימון מודל) אינן זמינות: לא "
                f"הוגדר קוד מנהל. להפעלה מקומית הוסיפו {ENV_CODE_VAR} "
                "לקובץ .env (לפחות "
                f"{MIN_CODE_LENGTH} תווים) והפעילו מחדש."
            ),
        )

    if len(code) < MIN_CODE_LENGTH:
        _warn_once(
            f"{ENV_CODE_VAR} קצר מ-{MIN_CODE_LENGTH} תווים — הפעולות "
            "המנהליות נשארות חסומות."
        )
        return AdminAccess(
            available=False, unlocked=False, public=False,
            mode="code_too_short",
            notice_he=(
                f"קוד המנהל שהוגדר קצר מ-{MIN_CODE_LENGTH} תווים, ולכן "
                "הפעולות המנהליות חסומות. עדכנו את "
                f"{ENV_CODE_VAR} ב-.env."
            ),
        )

    return AdminAccess(
        available=True,
        unlocked=codes_match(entered, code),
        public=False,
        mode="code",
    )


def codes_match(entered: str | None, expected: str | None = None) -> bool:
    """
    השוואת הקוד שהוקלד לזה שבסביבה — בזמן קבוע, ועל bytes.

    compare_digest על str זורק TypeError על כל תו שאינו ASCII, ולכן קוד
    בעברית היה מפיל את העמוד במקום להיכשל כ"קוד שגוי" (בדיוק התקלה
    שאומתה בשער ההתחברות בשרת). שני הצדדים מנורמלים לפני ההשוואה.
    """
    target = _normalize(expected) if expected is not None else admin_code()
    candidate = _normalize(entered)
    if not target or not candidate:
        return False
    return secrets.compare_digest(
        candidate.encode("utf-8"), target.encode("utf-8"),
    )
