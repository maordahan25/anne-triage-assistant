"""
חיזוי עם המודל השמור — טעינת ה-bundle והחזרת הסתברות להפניה למיון.

⚠ הדגמת יכולת ML לימודית בלבד (דאטה סינתטי, מדגם קטן) — לא כלי קליני.

ה-API פונקציונלי בכוונה: predict_er_probability(record) מקבלת רשומת-לוג
(או רשומה חלקית — שדות חסרים מקבלים ערך ניטרלי, ראו dataset.build_features)
ומחזירה הסתברות אחת בטווח [0,1]. טענו את ה-bundle פעם אחת עם load_model
והעבירו אותו כשקוראים בלולאה — במקום טעינת דיסק בכל קריאה.

הרצה (דמו על רשומות דוגמה, חינם, ללא LLM):
    python -m ml.predict
"""
from __future__ import annotations

from pathlib import Path

import joblib

from .dataset import build_features, features_from_record
from .models import MODEL_SPECS
from .train import resolve_model_path

_BUNDLE_KEYS = {"pipeline", "features", "target", "metrics", "sklearn_version"}

# רשומות הדמו של python -m ml.predict — פרופילים שונים מהתפלגות הלוג.
DEMO_RECORDS = (
    ("תור ברכה (הודעה קצרה, תחילת שיחה)",
     {"topic": None, "turn_index": 1, "user_message_chars": 9,
      "ts_utc": "2026-07-19T08:30:00Z"}),
    ("תור ייעוץ שגרתי (חתך, אמצע שיחה)",
     {"topic": "wounds", "turn_index": 2, "user_message_chars": 120,
      "ts_utc": "2026-07-19T21:10:00Z"}),
    ("הודעה ארוכה בלי תחום מזוהה, אמצע שיחה",
     {"topic": None, "turn_index": 3, "user_message_chars": 150,
      "ts_utc": "2026-07-19T02:45:00Z"}),
)


def load_model(model_path: str | Path | None = None) -> dict:
    """
    טעינת ה-bundle השמור (joblib). זורק FileNotFoundError בעברית אם המודל
    טרם אומן, ו-ValueError אם הקובץ אינו bundle תקין של המודול הזה.
    נתיב המודל: פרמטר > משתנה סביבה ANNE_ML_MODEL > ברירת המחדל.
    """
    path = resolve_model_path(model_path)
    if not path.exists():
        raise FileNotFoundError(
            f"קובץ המודל לא נמצא: {path} — אמנו קודם עם: python -m ml.train"
        )
    bundle = joblib.load(path)
    if not isinstance(bundle, dict) or not _BUNDLE_KEYS <= set(bundle):
        raise ValueError(f"קובץ המודל אינו bundle תקין של ml/: {path}")
    return bundle


def available_models(bundle: dict) -> list[dict]:
    """
    המודלים שב-bundle, לפי סדר המפרט: [{key, name_he, metrics, ...}].

    ב-bundle ישן (מודל אחד, בלי המפתח models) מוחזר מודל ברירת המחדל
    היחיד — כך שכל הקוראים עובדים על שני הפורמטים.
    """
    models = bundle.get("models")
    if not models:
        key = bundle.get("model_key", "logistic")
        spec = MODEL_SPECS.get(key)
        return [{
            "key": key,
            "name_he": spec.name_he if spec else key,
            "metrics": bundle.get("metrics", {}),
            "feature_names": [],
            "contributions": None,
        }]
    return [
        {
            "key": key,
            "name_he": MODEL_SPECS[key].name_he if key in MODEL_SPECS else key,
            "metrics": entry.get("metrics", {}),
            "feature_names": entry.get("feature_names", []),
            "contributions": entry.get("contributions"),
        }
        for key, entry in models.items()
    ]


def _pipeline_for(bundle: dict, model_key: str | None):
    """
    ה-pipeline המבוקש מתוך ה-bundle.

    model_key=None -> מודל ברירת המחדל (המפתח pipeline; תואם-לאחור).
    מפתח שאינו קיים ב-bundle -> ValueError בעברית, ולא נפילה עמומה.
    """
    if model_key is None:
        return bundle["pipeline"]
    models = bundle.get("models") or {}
    if model_key in models:
        return models[model_key]["pipeline"]
    if model_key == bundle.get("model_key"):
        return bundle["pipeline"]
    raise ValueError(
        f"המודל '{model_key}' אינו נמצא ב-bundle. זמינים: "
        f"{', '.join(models) or bundle.get('model_key', '—')}."
    )


def predict_er_probability(
    record: dict,
    *,
    bundle: dict | None = None,
    model_path: str | Path | None = None,
    model_key: str | None = None,
) -> float:
    """
    ההסתברות שהתור המתואר ברשומה יסתיים בהפניה למיון (emergency=1).

    record — רשומת לוג מלאה או חלקית (topic / turn_index /
    user_message_chars / ts_utc; השאר מיותר לחיזוי). model_key בוחר מודל
    מתוך ה-bundle (ברירת מחדל: המודל הראשי). מוחזר float בטווח [0,1] —
    מובטח על ידי predict_proba של המסווג.
    """
    if bundle is None:
        bundle = load_model(model_path)
    X = features_from_record(record)
    return float(_pipeline_for(bundle, model_key).predict_proba(X)[0, 1])


def predict_frame(df, *, bundle: dict | None = None,
                  model_path: str | Path | None = None,
                  model_key: str | None = None):
    """
    חיזוי אצווה: הסתברות [0,1] לכל שורה ב-DataFrame של רשומות לוג גולמיות
    (למשל פלט dataset.load_dataset או הנתונים המסוננים בדשבורד).
    מחזיר ndarray באורך ה-DataFrame, מיושר פוזיציונית לשורותיו.
    """
    if bundle is None:
        bundle = load_model(model_path)
    X, _ = build_features(df)
    return _pipeline_for(bundle, model_key).predict_proba(X)[:, 1]


def main() -> None:
    try:
        bundle = load_model()
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"שגיאה: {exc}")

    metrics = bundle["metrics"]
    models = available_models(bundle)
    print("=" * 78)
    print("דמו חיזוי — הסתברות להפניה למיון (הדגמה לימודית)")
    print("=" * 78)
    print(f"קובץ: {resolve_model_path().name} | אומן על {metrics['rows']} "
          f"רשומות | {len(models)} מודלים ב-bundle")
    header = "".join(f"{model['name_he']:>18}" for model in models)
    print(f"{'מקרה':<42}{header}")
    for label, record in DEMO_RECORDS:
        cells = "".join(
            f"{predict_er_probability(record, bundle=bundle, model_key=model['key']):>17.1%} "
            for model in models
        )
        print(f"{label:<42}{cells}")
    print("-" * 78)
    print("ROC-AUC (מדגם מוחזק): " + " | ".join(
        f"{model['name_he']}: {model['metrics'].get('roc_auc', '—')}"
        for model in models
    ))
    print("-" * 78)
    print("קריאת הטבלה: השוו את *הסדר* בין המקרים, לא את הערך המוחלט — "
          "איזון המחלקות (חירום נדיר) מנפח את ההסתברויות.")
    print("⚠ הדגמת יכולת ML בלבד: המודלים אומנו על דאטה סינתטי — "
          "ההסתברויות אינן הערכה רפואית.")


if __name__ == "__main__":
    main()
