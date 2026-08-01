"""
שכבת הנתונים של מודול החיזוי — טעינת רשומות הלוג והכנתן לאימון/חיזוי.

⚠ הדגמת יכולת Machine Learning לימודית בלבד: הדאטה סינתטי והמדגם קטן —
המודל אינו כלי קליני ואינו מנבא חירום רפואי אמיתי. המטרה היא להדגים את
המסלול המלא לוג -> features -> אימון -> חיזוי מעל הסכמה האנונימית הקיימת.

היעד (target): עמודת emergency — פסיקת החירום של שער הבטיחות (Dr. Dexter),
שמשמעה הפניה מיידית למיון/מוקד (referred_to_er). אין בסכמה עמודה בשם
referred_to_er — זהו שמו המושגי של אותו דגל.

בחירת ה-features — רק שדות הידועים בתחילת התור, לפני שהמערכת הכריעה:
topic, turn_index, user_message_chars, והשעה הנגזרת מ-ts_utc (בקידוד
מחזורי sin/cos, כי 23:00 ו-00:00 שעות סמוכות). כל שאר עמודות הלוג הן
*תוצרים* של אותה הכרעה (red_flags_count נגזר מפסיקת החירום עצמה;
consult_path/consulted, התזמונים ומוני הכלים נקבעים אחריה) — אימון עליהן
היה מלמד את המודל "לנבא" את התשובה מתוך התשובה (target leakage), ולכן הן
מוחרגות במפורש (LEAKY_COLUMNS). קבוצה רביעית — NON_FEATURE_COLUMNS — היא
עמודות שידועות בתחילת התור אך הוחלט *במודע* לא להשתמש בהן (כרגע:
image_attached, דגל שכבת הראייה). בדיקת האופליין אוכפת שכל עמודה בסכמה
מסווגת לקבוצה אחת בדיוק — עמודה חדשה בלוג תחייב הכרעה מודעת גם כאן.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from storage.turn_log import PROJECT_ROOT, fetch_turns

# ברירת המחדל לאימון היא הדאטה הסינתטי — לא הלוג האמיתי — בכוונה:
# ההדגמה לימודית, והלוג האמיתי קטן מכדי לאמן עליו (עקפו עם --db).
#
# הנתיב הזה משמעותי בשני ה-backends: כשה-backend הוא Supabase, שכבת
# ה-storage ממפה קובץ ששמו מכיל synthetic לטבלה turns_synthetic (ראה
# storage/backend.py). כלומר `python -m ml.train` מתאמן על הדאטה הסינתטי
# של המקור הפעיל, בלי פרמטר נוסף ובלי שהמודול הזה יידע מי המקור.
DEFAULT_TRAIN_DB = PROJECT_ROOT / "anne_log_synthetic.db"

TARGET = "emergency"

# עמודות הלוג הגולמיות שמהן נגזרים ה-features (ts_utc -> שעה מחזורית).
RAW_FEATURE_COLUMNS = ("topic", "turn_index", "user_message_chars", "ts_utc")

# עמודות זהות/גרסה — לא feature ולא target.
IDENTITY_COLUMNS = ("schema_version", "session_id")

# עמודות "דולפות": תוצרי התור שנקבעים יחד עם פסיקת החירום או אחריה —
# אסורות כ-features (ראו הסבר ה-leakage בראש הקובץ).
LEAKY_COLUMNS = (
    "red_flags_count", "consulted", "consult_path", "illustration_id",
    "sources_count", "filtered_sources_count", "reply_chars", "llm_calls",
    "t_safety_gate", "t_triage", "t_consult", "t_compose", "t_total",
    "tool_rag_search", "tool_locate_place", "tool_get_weather",
    "tool_get_current_time", "tools_other",
)

# עמודות שידועות בתחילת התור אך אינן features — **בכוונה, לא בהיסח הדעת**.
#
# image_attached (דגל שכבת הראייה: האם המשתמש צירף תמונה) הוא המקרה
# היחיד כרגע, והוא אינו דולף: הוא נקבע ברגע שההודעה נשלחה, לפני שדקסטר
# פסק. מבחינה מתודולוגית מותר היה לצרף אותו — אבל בדאטה שעליו ההדגמה
# מתאמנת (anne_log_synthetic.db) הוא קבוע 0, ולכן היה נכנס למודל כעמודה
# מתה: מקדם אפס בגרף הפרשנות, בקר חמישי חסר-משמעות במסך ה"מה-אם",
# ושורה בטבלת החשיבות שאינה מלמדת דבר. עמודה כזו מבלבלת יותר משהיא
# מוסיפה בהדגמה לימודית.
#
# **מתי לקדם אותה ל-RAW_FEATURE_COLUMNS**: כשיצטבר דאטה אמיתי שבו חלק
# מהתורים כוללים תמונה. אז הופכים אותה ל-feature מספרי (0/1) בשלוש
# שורות: להעביר את השם לכאן מלמעלה, להוסיף ל-NUMERIC_FEATURES, ולגזור
# אותה ב-build_features עם _column(df, "image_attached"). כדאי גם לשאול
# אז את שאלת ה-leakage מחדש: אם משתמשים מצרפים תמונה בעיקר כשהמצב נראה
# רע, הדגל מקודד חומרה — ומקביל למלכודת "ללא תחום" שכבר מתועדת בעמוד.
NON_FEATURE_COLUMNS = ("image_attached",)

# מטריצת ה-features שהמודל רואה בפועל (אחרי הגזירה).
CATEGORICAL_FEATURES = ("topic",)
NUMERIC_FEATURES = ("turn_index", "user_message_chars", "hour_sin", "hour_cos")
FEATURES = (*CATEGORICAL_FEATURES, *NUMERIC_FEATURES)


def load_dataset(db_path: str | Path | None = None) -> pd.DataFrame:
    """רשומות הלוג כ-DataFrame גולמי (ברירת מחדל: הדאטה הסינתטי)."""
    rows = fetch_turns(db_path=db_path or DEFAULT_TRAIN_DB)
    return pd.DataFrame(rows)


def _column(df: pd.DataFrame, name: str) -> pd.Series:
    """עמודה מה-DataFrame, או סדרת None אם חסרה (רשומת חיזוי חלקית)."""
    if name in df.columns:
        return df[name]
    return pd.Series([None] * len(df), index=df.index)


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series | None]:
    """
    גזירת מטריצת ה-features (X) ווקטור היעד (y) מרשומות גולמיות.

    עובד גם על רשומה חלקית בזמן חיזוי: עמודה חסרה מקבלת ערך ניטרלי —
    topic חסר הופך ל-'unknown' (קטגוריה לגיטימית: גם בלוג האמיתי תורי
    ברכה/חירום נרשמים בלי topic), ומספר חסר הופך ל-NaN שה-imputer של
    ה-pipeline משלים. y מוחזר None כשעמודת היעד חסרה (מצב חיזוי).
    """
    X = pd.DataFrame(index=df.index)
    X["topic"] = _column(df, "topic").fillna("unknown").astype(str)
    X["turn_index"] = pd.to_numeric(_column(df, "turn_index"), errors="coerce")
    X["user_message_chars"] = pd.to_numeric(
        _column(df, "user_message_chars"), errors="coerce",
    )
    ts = pd.to_datetime(_column(df, "ts_utc"), utc=True, errors="coerce")
    hour = ts.dt.hour
    X["hour_sin"] = np.sin(hour * (2 * np.pi / 24))
    X["hour_cos"] = np.cos(hour * (2 * np.pi / 24))
    X = X[list(FEATURES)]

    y = df[TARGET].astype(int) if TARGET in df.columns else None
    return X, y


def features_from_record(record: dict) -> pd.DataFrame:
    """שורת features בודדת מרשומת-לוג (או רשומה חלקית) — לחיזוי."""
    X, _ = build_features(pd.DataFrame([record]))
    return X
