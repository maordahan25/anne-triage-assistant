"""
אימון מודלי החיזוי (הסתברות להפניה למיון) — נקודת הכניסה של המודול.

⚠ הדגמת יכולת ML לימודית בלבד (דאטה סינתטי, מדגם קטן) — לא כלי קליני.

העיבוד המקדים זהה לכל המודלים: Pipeline של scikit-learn — one-hot ל-topic,
אימפוטציה (חציון) ותקנון למספריים. מה שמתחלף הוא המסווג בסוף הצינור,
לפי הרשימה הסגורה ב-ml/models.py: רגרסיה לוגיסטית (ברירת המחדל), יער
אקראי, הגבהת גרדיאנט, ומודל בסיס שאינו לומד (קו ייחוס).

**כל המודלים מאומנים על אותו פיצול בדיוק** (train_all_models מפצל פעם
אחת ומעביר את אותם אינדקסים לכולם) — אחרת ההשוואה ביניהם חסרת משמעות.

ה-bundle הנשמר עם joblib תואם-לאחור: pipeline/features/target/metrics/
sklearn_version הם של מודל ברירת המחדל, ובנוסף יש models עם כל המודלים
ומדדיהם. כך קוד שמכיר רק את המפתחות הישנים ממשיך לעבוד ללא שינוי.

הרצה (חינם, ללא LLM):
    python -m ml.train                        # כל המודלים על הדאטה הסינתטי
    python -m ml.train --db anne_log.db       # במפורש על הלוג האמיתי
    python -m ml.train --model random_forest  # מודל בודד כברירת המחדל ב-bundle
    python -m ml.train --seed 3 --test-size 0.3 --out /tmp/model.joblib
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import joblib
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .dataset import (
    CATEGORICAL_FEATURES,
    DEFAULT_TRAIN_DB,
    FEATURES,
    NUMERIC_FEATURES,
    TARGET,
    build_features,
    load_dataset,
)
from .models import (
    DEFAULT_MODEL_KEY,
    MODEL_ORDER,
    MODEL_SPECS,
    feature_contributions,
    fit_kwargs_for,
)

# תוצר האימון — לא בבקרת גרסאות (ml/models/ ב-.gitignore); בנייה מחדש
# בכל עת עם python -m ml.train.
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "er_referral.joblib"
# עקיפת נתיב המודל במשתנה סביבה — לבדיקות ולסביבות נפרדות (כמו ANNE_LOG_DB).
ENV_MODEL_VAR = "ANNE_ML_MODEL"


def resolve_model_path(model_path: str | Path | None = None) -> Path:
    """נתיב המודל: פרמטר מפורש > משתנה סביבה ANNE_ML_MODEL > ברירת המחדל."""
    if model_path is not None:
        return Path(model_path)
    env_path = os.getenv(ENV_MODEL_VAR, "").strip()
    return Path(env_path) if env_path else DEFAULT_MODEL_PATH


def build_preprocessor() -> ColumnTransformer:
    """העיבוד המקדים — זהה לכל המודלים (וזה מה שהופך את ההשוואה להוגנת)."""
    return ColumnTransformer([
        ("topic", OneHotEncoder(handle_unknown="ignore"),
         list(CATEGORICAL_FEATURES)),
        ("numeric", Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]), list(NUMERIC_FEATURES)),
    ])


def build_model(seed: int = 42, model_key: str = DEFAULT_MODEL_KEY) -> Pipeline:
    """צינור האימון: עיבוד מקדים אחיד + המסווג של המודל המבוקש."""
    if model_key not in MODEL_SPECS:
        raise ValueError(
            f"מודל '{model_key}' אינו מוכר. בחרו אחד מ: "
            f"{', '.join(MODEL_SPECS)}."
        )
    return Pipeline([
        ("preprocess", build_preprocessor()),
        ("classify", MODEL_SPECS[model_key].builder(seed)),
    ])


def _prepare(db_path: str | Path | None, test_size: float, seed: int):
    """טעינה, בניית features ופיצול מוחזק אחד — משותף לכל המודלים."""
    df = load_dataset(db_path)
    if df.empty:
        raise ValueError("הלוג ריק — אין רשומות לאימון. "
                         "הריצו קודם: python -m storage.synthetic")
    X, y = build_features(df)
    if y is None or y.nunique() < 2:
        raise ValueError("בלוג יש מחלקה אחת בלבד (אין גם חירום וגם שגרה) — "
                         "אי אפשר לאמן מסווג בינארי.")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, stratify=y, random_state=seed,
    )
    return df, X, y, (X_train, X_test, y_train, y_test)


def _fit_and_score(
    model_key: str, split, *, rows: int, positives: int,
    test_size: float, seed: int,
) -> tuple[Pipeline, dict]:
    """אימון מודל בודד על פיצול נתון + חישוב כל המדדים על המדגם המוחזק."""
    X_train, X_test, y_train, y_test = split
    spec = MODEL_SPECS[model_key]
    model = build_model(seed, model_key)
    model.fit(X_train, y_train, **fit_kwargs_for(spec, y_train))

    proba = model.predict_proba(X_test)[:, 1]
    predicted = proba >= 0.5
    tn, fp, fn, tp = confusion_matrix(y_test, predicted, labels=[0, 1]).ravel()
    # מודל הבסיס מחזיר ציון זהה לכולם -> ROC-AUC אינו מוגדר היטב מבחינת
    # sklearn (הוא מחזיר 0.5, וזה בדיוק הערך הנכון פדגוגית).
    metrics = {
        "model_key": model_key,
        "model_name_he": spec.name_he,
        "rows": rows,
        "positives": positives,
        "test_rows": int(len(y_test)),
        "test_positives": int(y_test.sum()),
        "roc_auc": round(float(roc_auc_score(y_test, proba)), 4),
        "average_precision": round(
            float(average_precision_score(y_test, proba)), 4,
        ),
        "brier": round(float(brier_score_loss(y_test, proba)), 4),
        "recall": round(float(recall_score(y_test, predicted)), 4),
        "precision": round(
            float(precision_score(y_test, predicted, zero_division=0)), 4,
        ),
        "confusion": {"tn": int(tn), "fp": int(fp),
                      "fn": int(fn), "tp": int(tp)},
        "test_size": test_size,
        "seed": seed,
    }
    return model, metrics


def encoded_feature_names(model: Pipeline) -> list[str]:
    """
    שמות התכונות *כפי שהמודל ראה אותן* (אחרי one-hot), בעברית קריאה.

    כשל בשליפה (גרסת sklearn אחרת) -> שמות גנריים; זו תצוגה בלבד ולעולם
    לא סיבה להפיל אימון או חיזוי.
    """
    pretty = {
        "turn_index": "מספר התור בשיחה",
        "user_message_chars": "אורך ההודעה",
        "hour_sin": "שעה (סינוס)",
        "hour_cos": "שעה (קוסינוס)",
    }
    topics = {
        "wounds": "פצעים וחתכים", "anxiety": "חרדה",
        "dehydration": "התייבשות", "cold": "הצטננות",
        "other": "אחר", "unknown": "ללא תחום",
    }
    try:
        raw_names = list(
            model.named_steps["preprocess"].get_feature_names_out()
        )
    except Exception:
        classifier = model.named_steps.get("classify")
        width = getattr(classifier, "n_features_in_", 0)
        return [f"תכונה {i + 1}" for i in range(width)]

    names = []
    for raw in raw_names:
        name = raw.split("__", 1)[-1]
        if name.startswith("topic_"):
            value = name[len("topic_"):]
            names.append(f"תחום: {topics.get(value, value)}")
        else:
            names.append(pretty.get(name, name))
    return names


def train_and_evaluate(
    db_path: str | Path | None = None,
    *,
    test_size: float = 0.25,
    seed: int = 42,
    model_key: str = DEFAULT_MODEL_KEY,
) -> tuple[Pipeline, dict]:
    """
    אימון מודל אחד והערכה על פיצול מוחזק (stratified) — מחזיר
    (pipeline מאומן, מילון מדדים). זורק ValueError בעברית על לוג ריק או
    לוג עם מחלקה אחת בלבד (אי אפשר לאמן מסווג בינארי).
    """
    df, X, y, split = _prepare(db_path, test_size, seed)
    return _fit_and_score(
        model_key, split, rows=int(len(df)), positives=int(y.sum()),
        test_size=test_size, seed=seed,
    )


def train_all_models(
    db_path: str | Path | None = None,
    *,
    test_size: float = 0.25,
    seed: int = 42,
) -> dict[str, dict]:
    """
    אימון *כל* המודלים על אותו פיצול בדיוק — התנאי להשוואה הוגנת ביניהם.

    מחזיר {model_key: {"pipeline": ..., "metrics": ..., "feature_names": ...,
    "contributions": ...}}. מודל שנכשל באימון (מצב קצה בנתונים) מדולג עם
    הודעה במקום להפיל את כל האימון — אלא אם זה מודל ברירת המחדל.
    """
    df, X, y, split = _prepare(db_path, test_size, seed)
    rows, positives = int(len(df)), int(y.sum())
    results: dict[str, dict] = {}
    for model_key in MODEL_ORDER:
        try:
            model, metrics = _fit_and_score(
                model_key, split, rows=rows, positives=positives,
                test_size=test_size, seed=seed,
            )
        except Exception as exc:  # pragma: no cover - מצב קצה בנתונים
            if model_key == DEFAULT_MODEL_KEY:
                raise
            print(f"[אזהרה] אימון '{model_key}' נכשל ודולג: {exc}")
            continue
        feature_names = encoded_feature_names(model)
        results[model_key] = {
            "pipeline": model,
            "metrics": metrics,
            "feature_names": feature_names,
            "contributions": feature_contributions(model, feature_names),
        }
    return results


def save_model(
    model: Pipeline,
    metrics: dict,
    model_path: str | Path | None = None,
    *,
    models: dict[str, dict] | None = None,
    default_key: str = DEFAULT_MODEL_KEY,
) -> Path:
    """
    שמירת ה-bundle המלא (מודל + הקשר) עם joblib. מחזיר את הנתיב.

    תואם-לאחור בכוונה: pipeline/features/target/metrics הם של מודל ברירת
    המחדל, ו-models (אם סופק) מוסיף את כל המודלים שאומנו יחד. קוד שמכיר
    רק את המפתחות הישנים אינו מושפע.
    """
    path = resolve_model_path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "pipeline": model,
        "features": list(FEATURES),
        "target": TARGET,
        "metrics": metrics,
        "sklearn_version": sklearn.__version__,
        "model_key": default_key,
    }
    if models:
        bundle["models"] = models
    joblib.dump(bundle, path)
    return path


def save_all_models(
    results: dict[str, dict],
    model_path: str | Path | None = None,
    *,
    default_key: str = DEFAULT_MODEL_KEY,
) -> Path:
    """שמירת כל המודלים שאומנו יחד, כשמודל ברירת המחדל הוא הראשי ב-bundle."""
    if not results:
        raise ValueError("לא אומן אף מודל — אין מה לשמור.")
    key = default_key if default_key in results else next(iter(results))
    return save_model(
        results[key]["pipeline"], results[key]["metrics"], model_path,
        models=results, default_key=key,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="אימון מודל חיזוי הפניה למיון מעל לוג השיחות "
                    "(הדגמה לימודית — חינם, ללא LLM).",
    )
    parser.add_argument("--db", default=str(DEFAULT_TRAIN_DB),
                        help="נתיב קובץ הלוג (ברירת מחדל: הדאטה הסינתטי)")
    parser.add_argument("--out", default=None,
                        help="נתיב שמירת המודל (ברירת מחדל: ANNE_ML_MODEL "
                             "אם הוגדר, אחרת ml/models/er_referral.joblib)")
    parser.add_argument("--seed", type=int, default=42,
                        help="seed לפיצול ולאימון — שחזוריות מלאה")
    parser.add_argument("--test-size", type=float, default=0.25,
                        help="חלק המדגם המוחזק להערכה (ברירת מחדל: 0.25)")
    parser.add_argument("--model", default=DEFAULT_MODEL_KEY,
                        choices=list(MODEL_SPECS),
                        help="איזה מודל יהיה ברירת המחדל ב-bundle "
                             "(כל המודלים מאומנים ונשמרים בכל מקרה)")
    args = parser.parse_args(argv)

    results = train_all_models(
        args.db, test_size=args.test_size, seed=args.seed,
    )
    path = save_all_models(results, args.out, default_key=args.model)
    reference = results[next(iter(results))]["metrics"]

    print("=" * 74)
    print("אימון מודלי חיזוי הפניה למיון (emergency) — הדגמה לימודית")
    print("=" * 74)
    print(f"דאטה: {args.db}")
    print(f"  רשומות: {reference['rows']} (חירום: {reference['positives']}) | "
          f"מדגם הערכה: {reference['test_rows']} "
          f"(חירום: {reference['test_positives']}) | "
          f"אותו פיצול לכל המודלים (seed={args.seed})")
    print("-" * 74)
    print(f"{'מודל':<22}{'ROC-AUC':>9}{'AvgPrec':>9}{'Brier':>8}"
          f"{'Recall':>8}{'Precis':>8}{'TP/FP/FN':>12}")
    for model_key, result in results.items():
        metrics = result["metrics"]
        confusion = metrics["confusion"]
        marker = " ←" if model_key == args.model else ""
        counts = "{tp}/{fp}/{fn}".format(**confusion)
        print(f"{metrics['model_name_he']:<22}"
              f"{metrics['roc_auc']:>9}{metrics['average_precision']:>9}"
              f"{metrics['brier']:>8}{metrics['recall']:>8}"
              f"{metrics['precision']:>8}{counts:>12}{marker}")
    print("-" * 74)
    print(f"נשמרו {len(results)} מודלים אל: {path}")
    print(f"מודל ברירת המחדל ב-bundle: "
          f"{MODEL_SPECS[args.model].name_he} ({args.model})")
    print("-" * 74)
    print("קריאת הטבלה: 'בסיס' אינו לומד — ROC-AUC שלו 0.5 והוא קו הייחוס; "
          "מודל ששווה משהו חייב להיות מעליו.")
    print("⚠ הדגמת יכולת ML בלבד: דאטה סינתטי ומעט מקרי חירום במדגם — "
          "המדדים אינם מעידים על דיוק קליני, וזה אינו כלי רפואי.")


if __name__ == "__main__":
    main()
