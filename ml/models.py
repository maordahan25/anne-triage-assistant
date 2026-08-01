"""
מפרט מודלי החיזוי — הרשימה הסגורה של המודלים + ההסבר הלימודי לכל אחד.

⚠ הדגמת יכולת ML לימודית בלבד (דאטה סינתטי, מדגם קטן) — לא כלי קליני.

למה מודול נפרד: הקובץ הזה הוא *מקור האמת* גם לקוד (איך בונים את המודל,
איך שולפים ממנו פרשנות) וגם לתצוגה (השם בעברית, ההסבר הנגיש, הנוסחאות).
כך אין הכפלה בין ml/ ל-dashboard/, והוספת מודל חדש נעשית במקום אחד.

כל ארבעת המודלים פותרים **בדיוק את אותה משימה** — לחזות את ההסתברות
שהתור יסתיים בהפניה למיון (עמודת emergency, פסיקת שער הבטיחות) מתוך
ארבע התכונות הידועות בתחילת התור. מה שמבדיל ביניהם הוא *השיטה*: מודל
לינארי שקוף, ממוצע של מאות עצים, עצים סדרתיים שמתקנים זה את זה, ומודל
ייחוס שאינו לומד כלל. ההשוואה ביניהם היא כל הפואנטה הלימודית.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.utils.class_weight import compute_sample_weight


@dataclass(frozen=True)
class ModelSpec:
    """מפרט מודל אחד: איך בונים אותו, ואיך מסבירים אותו למי שלומד."""

    key: str
    name_he: str
    family_he: str            # משפחת השיטה (לינארי / אנסמבל / ייחוס)
    summary_he: str           # שורה אחת: מה השיטה עושה
    explanation_he: str       # פסקה בעברית נגישה, בלי עגה
    math_intro_he: str        # מה הנוסחאות אומרות
    formulas: tuple[str, ...]  # LaTeX (מוצג ב-st.latex)
    math_notes_he: tuple[str, ...]  # פירוק כל נוסחה במילים
    interpretation: str       # "odds_ratio" | "importance" | "none"
    interpretation_he: str    # איך קוראים את גרף הפרשנות
    builder: Callable[[int], object] = field(repr=False)
    # משקולות לאיזון מחלקות בזמן fit, למודל שאינו תומך ב-class_weight.
    needs_sample_weight: bool = False


def _logistic(seed: int):
    # class_weight='balanced' — חירום נדיר (~4%); בלי איזון המודל לומד
    # לענות "לא" לכולם ומקבל דיוק גבוה שאינו שווה כלום.
    return LogisticRegression(
        class_weight="balanced", max_iter=1000, random_state=seed,
    )


def _random_forest(seed: int):
    # min_samples_leaf=2 — בלם overfitting על מדגם קטן; n_estimators=200
    # מספיק כדי שהממוצע יתייצב ועדיין מתאמן במילישניות.
    return RandomForestClassifier(
        n_estimators=200, min_samples_leaf=2, class_weight="balanced_subsample",
        random_state=seed, n_jobs=1,
    )


def _gradient_boosting(seed: int):
    # GradientBoostingClassifier אינו מקבל class_weight — האיזון נעשה
    # ב-sample_weight בזמן fit (ראה needs_sample_weight).
    return GradientBoostingClassifier(
        n_estimators=150, learning_rate=0.08, max_depth=2, random_state=seed,
    )


def _baseline(seed: int):  # noqa: ARG001 — חתימה אחידה
    # strategy="prior" — מחזיר לכולם את שכיחות החירום בנתוני האימון.
    return DummyClassifier(strategy="prior")


MODEL_SPECS: dict[str, ModelSpec] = {
    "logistic": ModelSpec(
        key="logistic",
        name_he="רגרסיה לוגיסטית",
        family_he="מודל לינארי",
        summary_he="נותן לכל תכונה משקל, מסכם לציון אחד ודוחס אותו להסתברות.",
        explanation_he=(
            "המודל הקלאסי לשאלות של \"כן או לא\". הוא נותן לכל תכונה משקל "
            "משלה (למשל: כמה אורך ההודעה מעלה או מוריד את הסיכוי), מחבר את "
            "כל המשקלים לציון אחד, ואז \"דוחס\" את הציון לטווח 0–1 — וזו "
            "ההסתברות. זה המודל השקוף מכולם: אפשר לפתוח אותו ולקרוא בדיוק "
            "כמה כל תכונה שוקלת ובאיזה כיוון. בגלל זה הוא ברירת המחדל כאן, "
            "גם כשמודל אחר מדויק ממנו במקצת."
        ),
        math_intro_he=(
            "שני צעדים: חיבור לינארי של התכונות, ואחריו פונקציית הסיגמואיד "
            "שממפה כל מספר ממשי לטווח (0,1)."
        ),
        formulas=(
            r"z = \beta_0 + \beta_1 x_1 + \beta_2 x_2 + \dots + \beta_k x_k",
            r"p = \sigma(z) = \frac{1}{1 + e^{-z}}",
            r"\ln\!\left(\frac{p}{1-p}\right) = z",
            r"\mathcal{L} = -\sum_{i=1}^{n}"
            r"\big[y_i \ln p_i + (1-y_i)\ln(1-p_i)\big]",
        ),
        math_notes_he=(
            "z הוא הציון הלינארי: כל תכונה xᵢ מוכפלת במשקל βᵢ שנלמד מהנתונים.",
            "הסיגמואיד σ הופך את הציון להסתברות — ציון 0 נותן בדיוק 50%.",
            "אם מבודדים את z מקבלים את הלוג של יחס הסיכויים; לכן e^βᵢ הוא "
            "\"יחס הסיכויים\" (odds ratio): פי כמה גדל הסיכוי כשהתכונה עולה "
            "ביחידה אחת. זה מה שמוצג בגרף הפרשנות.",
            "האימון מחפש את המשקולות שממזערות את ה-log-loss — פונקציה "
            "שמענישה בעיקר ביטחון גבוה בתשובה שגויה.",
        ),
        interpretation="odds_ratio",
        interpretation_he=(
            "יחס סיכויים גדול מ-1 = התכונה מעלה את ההסתברות; קטן מ-1 = "
            "מורידה אותה; בדיוק 1 = חסרת השפעה."
        ),
        builder=_logistic,
    ),
    "random_forest": ModelSpec(
        key="random_forest",
        name_he="יער אקראי",
        family_he="אנסמבל מקבילי (bagging)",
        summary_he="ממוצע של מאות עצי החלטה, כל אחד על מדגם ותכונות אחרים.",
        explanation_he=(
            "עץ החלטה הוא שרשרת שאלות כן/לא (\"האם ההודעה ארוכה מ-80 "
            "תווים?\", \"האם התחום הוא חרדה?\") שבסופה תשובה. עץ בודד קל "
            "להבין אבל לא יציב: שינוי קטן בנתונים משנה אותו לגמרי. יער "
            "אקראי מגדל מאות עצים — כל אחד על מדגם אקראי של השורות ועם "
            "תת-קבוצה אקראית של התכונות בכל פיצול — ומחשב את ממוצע "
            "התחזיות. הרעיון: העצים טועים, אבל לא באותו כיוון, והממוצע "
            "מבטל חלק גדול מהטעות."
        ),
        math_intro_he=(
            "העץ בוחר בכל צומת את הפיצול שמקטין הכי הרבה את \"אי-הטוהר\" "
            "של הקבוצה, והיער מחשב ממוצע על כל העצים."
        ),
        formulas=(
            r"G(S) = 1 - \sum_{k} p_k^2",
            r"\Delta G = G(S) - \frac{|S_L|}{|S|}G(S_L)"
            r" - \frac{|S_R|}{|S|}G(S_R)",
            r"\hat{p}(x) = \frac{1}{B}\sum_{b=1}^{B} p_b(x)",
            r"\operatorname{Var}\!\left(\hat{p}\right) ="
            r" \rho\sigma^2 + \frac{1-\rho}{B}\sigma^2",
        ),
        math_notes_he=(
            "G הוא מדד Gini לאי-טוהר: 0 כשכל הקבוצה מאותה מחלקה, ומקסימלי "
            "כשהיא מפוצלת שווה בשווה.",
            "בכל צומת נבחר הפיצול שמגדיל את ΔG — כלומר מפריד את החירום "
            "מהשגרה בצורה הטובה ביותר.",
            "התחזית הסופית היא ממוצע ההסתברויות של B העצים.",
            "זו הסיבה שהיער עובד: השונות של הממוצע קטנה פי B — אבל רק "
            "בחלק שאינו מתואם בין העצים (ρ הוא המתאם ביניהם). לכן דווקא "
            "ה\"אקראיות\" בבחירת השורות והתכונות היא שמשפרת את הדיוק."
        ),
        interpretation="importance",
        interpretation_he=(
            "\"חשיבות תכונה\" = כמה אי-הטוהר ירד בזכותה בכל היער. היא מודדת "
            "כמה המודל *נשען* על התכונה — ולא את כיוון ההשפעה."
        ),
        builder=_random_forest,
    ),
    "gradient_boosting": ModelSpec(
        key="gradient_boosting",
        name_he="הגבהת גרדיאנט",
        family_he="אנסמבל סדרתי (boosting)",
        summary_he="עצים קטנים בתור, כל אחד מתקן את הטעויות של קודמיו.",
        explanation_he=(
            "גם כאן מדובר בעצים, אבל הם לא גדלים במקביל אלא בתור: כל עץ "
            "חדש מסתכל על מה שהמודל עד כה טעה בו, ומוסיף תיקון קטן בכיוון "
            "הנכון. במקום להצביע (כמו ביער), התחזיות מצטברות זו על זו. "
            "בטבלאות נתונים זו לרוב השיטה המדויקת ביותר, אבל היא גם הרגישה "
            "ביותר לכיול-יתר: על מדגם קטן כמו שלנו היא יכולה \"לשנן\" את "
            "נתוני האימון ולהיראות טובה יותר ממה שהיא."
        ),
        math_intro_he=(
            "כל צעד מוסיף עץ שמנסה לחזות את *הטעות שנשארה*, מוכפל בקצב "
            "לימוד קטן שמונע צעדים גדולים מדי."
        ),
        formulas=(
            r"F_m(x) = F_{m-1}(x) + \nu \, h_m(x)",
            r"r_i = -\frac{\partial \mathcal{L}}{\partial F(x_i)}"
            r" = y_i - p_i",
            r"p = \sigma\big(F_M(x)\big)",
        ),
        math_notes_he=(
            "F_m היא התחזית המצטברת אחרי m עצים; ν (קצב הלימוד) קובע כמה "
            "מכל עץ נלקח — קטן יותר = לימוד איטי ויציב יותר.",
            "העץ הבא מאומן על השארית r — ובאיבוד log-loss השארית היא בדיוק "
            "\"אמת פחות תחזית\". זה מה שהופך את זה ל\"ירידת גרדיאנט "
            "בעצים\".",
            "בסוף התחזית המצטברת עוברת אותה סיגמואיד כדי לחזור להסתברות."
        ),
        interpretation="importance",
        interpretation_he=(
            "חשיבות התכונה כאן נמדדת לפי תרומתה להקטנת הטעות בכל העצים "
            "הסדרתיים — שוב, עוצמה ולא כיוון."
        ),
        builder=_gradient_boosting,
        needs_sample_weight=True,
    ),
    "baseline": ModelSpec(
        key="baseline",
        name_he="בסיס (שכיחות בלבד)",
        family_he="מודל ייחוס — אינו לומד",
        summary_he="מחזיר לכולם את אותה הסתברות: שכיחות החירום בנתונים.",
        explanation_he=(
            "מודל שלא לומד כלום, ובכוונה: הוא מחזיר לכל מקרה את אותה "
            "הסתברות — פשוט שיעור מקרי החירום שראה באימון. הוא קיים כדי "
            "לתת קו ייחוס. כל מודל אמיתי חייב להיות טוב ממנו, ואם הוא לא — "
            "סימן שהתכונות שבחרנו לא מכילות מידע. בלי קו ייחוס כזה אי אפשר "
            "לדעת אם 0.72 הוא הישג או כלום."
        ),
        math_intro_he="אין כאן אימון — רק חישוב שכיחות.",
        formulas=(
            r"\hat{p}(x) = \bar{y} = \frac{1}{n}\sum_{i=1}^{n} y_i",
            r"\text{ROC-AUC} = 0.5",
        ),
        math_notes_he=(
            "אותה הסתברות לכולם, ללא תלות ב-x.",
            "כשכל המקרים מקבלים ציון זהה אין שום דירוג — ולכן ROC-AUC הוא "
            "0.5 בדיוק, כמו הטלת מטבע. זה הרף שמודל אמיתי צריך לעבור."
        ),
        interpretation="none",
        interpretation_he="אין מה לפרש — המודל אינו מסתכל על התכונות.",
        builder=_baseline,
    ),
}

# ברירת המחדל: המודל השקוף. הוא זה שנשמר כ-pipeline הראשי ב-bundle,
# ולכן גם המודל שכל קוד קיים ממשיך לקבל בלי לבקש מודל במפורש.
DEFAULT_MODEL_KEY = "logistic"
MODEL_ORDER = ("logistic", "random_forest", "gradient_boosting", "baseline")


def fit_kwargs_for(spec: ModelSpec, y) -> dict:
    """
    ארגומנטים נוספים ל-fit של ה-Pipeline עבור מודל נתון.

    מודל שאינו תומך ב-class_weight מקבל sample_weight מאוזן — אותה כוונה
    בדיוק (לתת למקרי החירום הנדירים משקל שווה), רק בדרך אחרת.
    """
    if not spec.needs_sample_weight:
        return {}
    weights = compute_sample_weight(class_weight="balanced", y=y)
    return {"classify__sample_weight": weights}


def feature_contributions(pipeline, feature_names: list[str]) -> dict | None:
    """
    פרשנות המודל: מה הוא "מסתכל" עליו.

    מחזיר {"kind": "odds_ratio"|"importance", "values": {שם תכונה: ערך}}
    או None למודל שאין ממנו מה לשלוף (הבסיס). שמות התכונות הם אלה שיצאו
    מה-ColumnTransformer (אחרי one-hot), כדי שהגרף יתאר את מה שהמודל
    באמת ראה.
    """
    classifier = pipeline.named_steps.get("classify")
    if classifier is None:
        return None
    if hasattr(classifier, "coef_"):
        coefficients = np.asarray(classifier.coef_).ravel()
        return {
            "kind": "odds_ratio",
            "values": {
                name: float(np.exp(value))
                for name, value in zip(feature_names, coefficients)
            },
        }
    if hasattr(classifier, "feature_importances_"):
        importances = np.asarray(classifier.feature_importances_).ravel()
        return {
            "kind": "importance",
            "values": {
                name: float(value)
                for name, value in zip(feature_names, importances)
            },
        }
    return None


# ── מילון המדדים (לימודי) ─────────────────────────────────────────────────
# מוצג בעמוד ה-ML: מה כל מדד אומר, ולמה דיוק "רגיל" (accuracy) אינו מופיע
# כאן בכלל — כשחירום הוא 4% מהתורים, מודל שמנחש "לא" לכולם מגיע ל-96%.
METRIC_GLOSSARY_HE = (
    ("ROC-AUC",
     "ההסתברות שהמודל ייתן ציון גבוה יותר למקרה חירום אקראי מאשר למקרה "
     "שגרה אקראי. 0.5 = ניחוש, 1.0 = הפרדה מושלמת. מודד *דירוג*, לא כיול."),
    ("Average Precision",
     "שקלול של דיוק וכיסוי על פני כל הספים האפשריים. מתאים יותר מ-ROC-AUC "
     "כשהמקרה החיובי נדיר, כמו כאן."),
    ("Recall (רגישות)",
     "מבין מקרי החירום שהיו בפועל — איזה חלק המודל תפס. TP/(TP+FN). "
     "בהקשר רפואי זה המדד שהכי יקר לפספס בו."),
    ("Precision (דיוק)",
     "מבין המקרים שהמודל סימן כחירום — איזה חלק אכן היה חירום. TP/(TP+FP). "
     "יש כאן חילוף מול הרגישות: אפשר לתפוס יותר במחיר יותר אזעקות שווא."),
    ("Brier",
     "השגיאה הריבועית הממוצעת של ההסתברות עצמה — מודד *כיול* ולא רק דירוג. "
     "נמוך יותר = טוב יותר."),
)
