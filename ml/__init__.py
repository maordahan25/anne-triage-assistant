"""
מודול החיזוי של "אן" — הדגמת Machine Learning מעל לוג השיחות האנונימי.

⚠ הדגמת יכולת לימודית בלבד: המודל מאומן על דאטה סינתטי ומדגם קטן —
הוא אינו כלי קליני ואין להציגו כמנבא חירום רפואי אמיתי.

המשימה: מתוך שדות רשומת-הלוג הידועים בתחילת התור (תחום, אינדקס תור,
אורך ההודעה, שעה) — לנבא את ההסתברות שהתור יסתיים בהפניה למיון
(referred_to_er; בסכמה: עמודת emergency, פסיקת שער הבטיחות).

מבנה (scikit-learn + joblib, חינם, ללא LLM):
    dataset.py  טעינה והכנה — features, target, והחרגת עמודות דולפות
    models.py   הרשימה הסגורה של המודלים + ההסבר הלימודי והנוסחאות
    train.py    אימון, הערכה ושמירה — python -m ml.train
    predict.py  טעינת המודל וחיזוי — python -m ml.predict (דמו)

ארבעה מודלים על אותה משימה ואותו פיצול, כדי שיהיה מה להשוות: רגרסיה
לוגיסטית (ברירת המחדל, השקופה), יער אקראי, הגבהת גרדיאנט, ומודל בסיס
שאינו לומד (קו ייחוס — ROC-AUC 0.5).

הייבוא כאן עצל (PEP 562) בכוונה: ייבוא אֶגֶרי של תת-המודולים מתנגש עם
הרצתם כנקודות כניסה (python -m ml.train מזהיר על כפל ב-sys.modules).
"""
from __future__ import annotations

_EXPORTS = {
    "FEATURES": "dataset", "TARGET": "dataset",
    "build_features": "dataset", "load_dataset": "dataset",
    "DEFAULT_MODEL_KEY": "models", "METRIC_GLOSSARY_HE": "models",
    "MODEL_ORDER": "models", "MODEL_SPECS": "models",
    "available_models": "predict", "load_model": "predict",
    "predict_er_probability": "predict", "predict_frame": "predict",
    "DEFAULT_MODEL_PATH": "train", "resolve_model_path": "train",
    "save_all_models": "train", "save_model": "train",
    "train_all_models": "train", "train_and_evaluate": "train",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name in _EXPORTS:
        from importlib import import_module

        return getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
