"""
שכבה (ב) — מדידות דטרמיניסטיות מהפיקסלים.

מה שנמדד כאן הוא *עובדות על התמונה*, לא פרשנות: כמה מהתמונה אדמדמה,
כמה מרוכזת האדמומיות, מה טווח הבהירות. אלה בדיוק המספרים שאדם היה
אומר עליהם "יש כאן אזור אדום בערך בגודל של רבע מהתמונה" — הקשר לתשאול,
לא אבחנה. שום פונקציה כאן לא מחזירה שם של מצב רפואי.

היתרון על פני שליחה למודל: המדידות זהות בכל הרצה, חינמיות, עובדות גם
כשאין רשת, וניתן לבדוק אותן מול תמונה סינתטית עם כתם בגודל ידוע — וזה
מה שהבדיקות עושות.

הכול numpy טהור. OpenCV היה מוסיף ~60MB ותלות בינארית חוצת-פלטפורמות
בשביל פעולות שהן ממילא אריתמטיקה על מטריצה.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# סף האדמומיות המוחלטת: פיקסל נחשב אדמדם כשהערוץ האדום גבוה משמעותית
# משני האחרים *וגם* בהיר מספיק — כך שפינה חשוכה או אפור-חם לא נספרים.
RED_DOMINANCE = 25.0     # כמה R חייב לעלות על G ועל B
RED_MIN_LEVEL = 60.0     # מתחת לזה זה כהה מדי מכדי לקרוא לו אדום

# סף האדמומיות ה*בולטת*, והוא העיקרי. עור אנושי הוא ממילא חמים: במדידה
# על תמונת עור סינתטית 67% מהפיקסלים עברו את הסף המוחלט, כלומר "אדמומיות
# 67%" הייתה מדווחת על עור בריא לגמרי — מספר נכון טכנית וחסר ערך לתשאול.
# לכן הסף האמיתי הוא יחסי לתמונה עצמה: פיקסל בולט הוא כזה שהאדמומיות שלו
# גבוהה מהחציון של אותה תמונה במרווח קבוע. אזור אדום על עור נורמלי קופץ
# מיד; עור אחיד נותן ~0%.
RED_STANDOUT_MARGIN = 25.0


@dataclass
class FeatureReport:
    """המדידות שחולצו מהתמונה (כולן ניתנות לשחזור מהפיקסלים)."""

    width: int
    height: int
    red_ratio: float          # שיעור הפיקסלים האדומים ה*בולטים* (יחסי לתמונה)
    red_ratio_absolute: float  # שיעור הפיקסלים האדמדמים בסף מוחלט
    red_focus: float          # ריכוז: שיעור האדום בתוך התיבה החוסמת שלו
    red_bbox_ratio: float     # שטח התיבה החוסמת ביחס לתמונה
    redness_index: float      # עוצמת האדמומיות הממוצעת (0-255)
    brightness: float
    contrast: float

    def as_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "red_ratio": round(self.red_ratio, 4),
            "red_ratio_absolute": round(self.red_ratio_absolute, 4),
            "red_focus": round(self.red_focus, 4),
            "red_bbox_ratio": round(self.red_bbox_ratio, 4),
            "redness_index": round(self.redness_index, 2),
            "brightness": round(self.brightness, 1),
            "contrast": round(self.contrast, 1),
        }

    def summary_he(self) -> str:
        """שורת המדידות כפי שהיא מוזרקת לפרומפט ומוצגת למשתמש."""
        parts = [f"{self.width}×{self.height} פיקסלים"]
        if self.red_ratio >= 0.005:
            parts.append(
                f"אזור אדום בולט בכ-{self.red_ratio * 100:.1f}% משטח התמונה")
            parts.append("מרוכז באזור אחד" if self.red_focus >= 0.35
                         else "מפוזר על פני התמונה")
        elif self.red_ratio_absolute >= 0.6:
            # כל התמונה בגוון חם — לרוב תקריב על עור. אין "אזור בולט"
            # להצביע עליו, וזו אמירה שונה מ"אין אדמומיות".
            parts.append("הגוון החם אחיד בכל התמונה, בלי אזור אדום בולט")
        else:
            parts.append("לא נמדדה אדמומיות בולטת")
        parts.append(f"בהירות ממוצעת {self.brightness:.0f}/255")
        return " · ".join(parts)


def redness(rgb: np.ndarray) -> np.ndarray:
    """מפת האדמומיות: כמה הערוץ האדום גבוה מממוצע שני האחרים."""
    array = rgb.astype(np.float64)
    return array[:, :, 0] - (array[:, :, 1] + array[:, :, 2]) / 2.0


def red_mask(rgb: np.ndarray) -> np.ndarray:
    """מסכת הפיקסלים האדמדמים (bool) בסף מוחלט — כולל גוני עור חמים."""
    array = rgb.astype(np.float64)
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    return (
        (red > green + RED_DOMINANCE)
        & (red > blue + RED_DOMINANCE)
        & (red > RED_MIN_LEVEL)
    )


def standout_red_mask(rgb: np.ndarray) -> np.ndarray:
    """
    מסכת האדום ה*בולט*: אדמומיות גבוהה מהחציון של התמונה עצמה במרווח
    קבוע, ובנוסף אדמדמה בסף המוחלט (כדי שרעש בתמונה אפורה לא ייספר).
    זו המסכה שעליה מדווחים — ראה ההסבר ליד RED_STANDOUT_MARGIN.
    """
    values = redness(rgb)
    baseline = float(np.median(values))
    return (values > baseline + RED_STANDOUT_MARGIN) & red_mask(rgb)


def extract_features(rgb: np.ndarray) -> FeatureReport:
    """כל המדידות בקריאה אחת (הן חולקות את אותה מטריצה)."""
    height, width = rgb.shape[0], rgb.shape[1]
    array = rgb.astype(np.float64)
    mask = standout_red_mask(array)
    absolute_mask = red_mask(array)
    total = float(mask.size)
    red_pixels = float(mask.sum())
    red_ratio = red_pixels / total if total else 0.0

    # התיבה החוסמת של האדום: ריכוז גבוה = כתם אחד; ריכוז נמוך = פיזור
    # (למשל תאורה חמה על כל התמונה). זו הבחנה שעוזרת לתשאול ולא מאבחנת.
    red_focus, bbox_ratio = 0.0, 0.0
    if red_pixels:
        rows = np.where(mask.any(axis=1))[0]
        cols = np.where(mask.any(axis=0))[0]
        box_h = int(rows[-1] - rows[0] + 1)
        box_w = int(cols[-1] - cols[0] + 1)
        box_area = float(box_h * box_w)
        bbox_ratio = box_area / total if total else 0.0
        red_focus = red_pixels / box_area if box_area else 0.0

    gray = (0.299 * array[:, :, 0] + 0.587 * array[:, :, 1]
            + 0.114 * array[:, :, 2])
    return FeatureReport(
        width=width, height=height,
        red_ratio=red_ratio,
        red_ratio_absolute=float(absolute_mask.mean()) if total else 0.0,
        red_focus=red_focus, red_bbox_ratio=bbox_ratio,
        redness_index=float(np.clip(redness(array), 0, 255).mean()),
        brightness=float(gray.mean()), contrast=float(gray.std()),
    )
