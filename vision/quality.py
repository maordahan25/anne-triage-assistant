"""
שכבה (א) — האם התמונה בכלל שמישה.

לפני שמודדים משהו ולפני שמשלמים על מודל ראייה, שואלים שאלה זולה: אפשר
ללמוד מהתמונה הזו? תמונה מטושטשת או כהה מדי היא לא כישלון — היא סיבה
מצוינת לבקש מהמשתמש תמונה נוספת, וזה בדיוק תפקיד של שכבת אנמנזה.

הכול numpy על מטריצת הפיקסלים, בלי OpenCV:
  * **חדות** — שונות הלפלסיאן. הלפלסיאן הוא גזירה שנייה: בתמונה חדה יש
    בו ערכים גדולים (מעברים חדים), ובתמונה מטושטשת הוא שטוח וקרוב לאפס.
    המימוש הוא הפרשי שכנים ב-slicing (`4*p - שכנים`), כלומר קונבולוציה
    עם הגרעין הסטנדרטי — בלי scipy.
  * **חשיפה** — בהירות ממוצעת ואחוז הפיקסלים שנחתכו בקצוות (שחור מלא /
    לבן שרוף). ממוצע לבדו לא מספיק: תמונה עם חצי שרוף וחצי שחור נראית
    "תקינה" בממוצע.

הספים כויילו מול תמונות סינתטיות בבדיקות (חדה / מטושטשת / כהה / שרופה)
והם מוגדרים על תמונה מוקטנת ל-1024px — לכן הם יציבים בין מכשירים.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# ספים על תמונה בגווני אפור 0-255 (אחרי ההקטנה ב-ingest).
#
# שני מדדי חדות ולא אחד, וזו לא קוסמטיקה: שונות הלפלסיאן היא ממוצע על
# *כל* התמונה, ולכן תמונה נקייה בעלת מעט טקסטורה — עור חלק בתאורה
# אחידה עם פצע אחד — מקבלת שונות נמוכה בדיוק כמו תמונה מטושטשת. מדידה
# על תמונות סינתטיות: עור חלק חד = 64, עור חלק מטושטש = 0.1, כלומר
# הסף חייב לרדת מאוד — ואז תמונה מטושטשת ורועשת מתחמקת. עוצמת הקצה
# (אחוזון 99.5 של |לפלסיאן|) פותרת את זה: היא שואלת "יש בתמונה *איפשהו*
# מעבר חד?", ובה ההפרדה חדה — 37-547 בתמונות חדות מול 1.4-6.3
# במטושטשות. לכן: מטושטשת = שני המדדים נמוכים.
BLUR_VARIANCE_MIN = 25.0        # שונות לפלסיאן מתחת לזה — חשוד לטשטוש
EDGE_STRENGTH_MIN = 12.0        # ...ורק אם גם אין אף קצה חד — מטושטשת
SOFT_EDGE_MIN = 60.0            # קצה חלש יחסית — "רכה", עדיין שמישה
DARK_MEAN_MAX = 55.0            # ממוצע מתחת לזה — כהה מדי
BRIGHT_MEAN_MIN = 205.0         # ממוצע מעל לזה — שרופה
CLIPPED_DARK_MAX = 0.55         # יותר מ-55% פיקסלים שחורים לגמרי
CLIPPED_BRIGHT_MAX = 0.35       # יותר מ-35% פיקסלים לבנים שרופים


@dataclass
class QualityReport:
    """מדדי איכות + פסיקה קריאה לאדם."""

    sharpness: float             # שונות הלפלסיאן
    edge_strength: float         # אחוזון 99.5 של |לפלסיאן| — הקצה החד ביותר
    brightness: float            # ממוצע 0-255
    contrast: float              # סטיית תקן
    dark_ratio: float            # אחוז פיקסלים כהים מאוד
    bright_ratio: float          # אחוז פיקסלים בהירים מאוד
    usable: bool
    issues_he: list[str]
    summary_he: str

    def as_dict(self) -> dict:
        return {
            "sharpness": round(self.sharpness, 1),
            "edge_strength": round(self.edge_strength, 1),
            "brightness": round(self.brightness, 1),
            "contrast": round(self.contrast, 1),
            "dark_ratio": round(self.dark_ratio, 4),
            "bright_ratio": round(self.bright_ratio, 4),
            "usable": self.usable,
            "issues_he": list(self.issues_he),
            "summary_he": self.summary_he,
        }


def to_gray(rgb: np.ndarray) -> np.ndarray:
    """RGB (H,W,3) -> גווני אפור float (H,W), משקלי luminance סטנדרטיים."""
    array = rgb.astype(np.float64)
    return (0.299 * array[:, :, 0]
            + 0.587 * array[:, :, 1]
            + 0.114 * array[:, :, 2])


def _laplacian(gray: np.ndarray) -> np.ndarray:
    """
    לפלסיאן בקונבולוציה עם הגרעין [[0,1,0],[1,-4,1],[0,1,0]], ממומש
    כהפרשי שכנים ב-slicing (מהיר, בלי תלות ב-scipy/OpenCV).
    """
    center = gray[1:-1, 1:-1]
    return (gray[:-2, 1:-1] + gray[2:, 1:-1]
            + gray[1:-1, :-2] + gray[1:-1, 2:]
            - 4.0 * center)


def laplacian_variance(gray: np.ndarray) -> float:
    """שונות הלפלסיאן — מדד החדות הקלאסי (ממוצע על כל התמונה)."""
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    return float(_laplacian(gray).var())


def edge_strength(gray: np.ndarray) -> float:
    """
    עוצמת הקצה החד בתמונה — אחוזון 99.5 של |לפלסיאן|.

    למה אחוזון ולא מקסימום: פיקסל בודד רועש היה קובע את הציון. אחוזון
    99.5 שואל "האם יש בתמונה *אזור* של מעבר חד", וזו השאלה הנכונה
    כשמנסים להבחין בין עור חלק מצולם היטב לבין תמונה מרוחה.
    """
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    return float(np.percentile(np.abs(_laplacian(gray)), 99.5))


def assess_quality(rgb: np.ndarray) -> QualityReport:
    """מדדי איכות + פסיקה: שמישה או שכדאי לבקש תמונה טובה יותר."""
    gray = to_gray(rgb)
    sharpness = laplacian_variance(gray)
    edges = edge_strength(gray)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    dark_ratio = float((gray < 25).mean())
    bright_ratio = float((gray > 240).mean())

    issues: list[str] = []
    if sharpness < BLUR_VARIANCE_MIN and edges < EDGE_STRENGTH_MIN:
        issues.append("התמונה מטושטשת")
    if brightness < DARK_MEAN_MAX or dark_ratio > CLIPPED_DARK_MAX:
        issues.append("התמונה כהה מדי")
    if brightness > BRIGHT_MEAN_MIN or bright_ratio > CLIPPED_BRIGHT_MAX:
        issues.append("התמונה בהירה או מסונוורת מדי")

    usable = not issues
    if usable and edges < SOFT_EDGE_MIN:
        summary = "איכות סבירה — הפרטים מעט רכים"
    elif usable:
        summary = "איכות טובה — חדה ומוארת היטב"
    else:
        summary = " · ".join(issues)
    return QualityReport(
        sharpness=sharpness, edge_strength=edges, brightness=brightness,
        contrast=contrast, dark_ratio=dark_ratio, bright_ratio=bright_ratio,
        usable=usable, issues_he=issues, summary_he=summary,
    )
