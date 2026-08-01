"""
המנצח על שלוש השכבות: קליטה בטוחה -> איכות -> מדידות -> תיאור.

התוצר היחיד שיוצא מהמודול החוצה הוא `ImageAnalysis`, ובתוכו `context_he`
— בלוק עברי קצר שמוזרק לפרומפטים של הסוכנים בדיוק כמו הקשר השעה ומזג
האוויר (crew/pipeline.py). זה מה ששומר על העיקרון: **התמונה מוסיפה הקשר
לתשאול, לא אבחון.** אין סוכן חדש, אין תפקיד חדש, ואין החלטה שעוברת
לשכבת הראייה — הרופא המומחה ו-Dr. Dexter מכריעים כמו קודם, עכשיו עם
מידע נוסף.

פרטיות: הבייטים של התמונה חיים כאן בזיכרון בלבד. שום דבר לא נכתב לדיסק,
ה-EXIF מוסר לפני כל עיבוד (vision/ingest.py), ולוג השיחות לא מקבל מהם
דבר — הסכמה שלו נשארה בדיוק כפי שהייתה, בלי טקסט חופשי ובלי שדה תמונה.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .describe import DescriptionResult, describe_image
from .features import FeatureReport, extract_features
from .ingest import ingest_image, to_jpeg_bytes
from .quality import QualityReport, assess_quality
from .scope import (
    NOT_A_BODY_INSTRUCTION_HE,
    OUT_OF_SCOPE_INSTRUCTION_HE,
    find_out_of_scope,
    is_not_a_body_image,
)

CONTEXT_HEADER_HE = (
    "[הקשר מתמונה שהמשתמש העלה — מדידות אוטומטיות ותיאור חזותי. "
    "זהו מידע לתשאול בלבד, לא אבחנה ולא תחליף לבדיקה.]"
)


@dataclass
class ImageAnalysis:
    """תוצאת הניתוח המלאה — מה שהשרת מחזיר ומה שה-pipeline מזריק."""

    ok: bool
    error_he: str | None = None
    quality: QualityReport | None = None
    features: FeatureReport | None = None
    description: DescriptionResult | None = None
    out_of_scope_markers: list[str] = field(default_factory=list)
    not_a_body: bool = False
    meta: dict = field(default_factory=dict)
    context_he: str = ""

    @property
    def outside_scope(self) -> bool:
        return bool(self.out_of_scope_markers) or self.not_a_body

    def as_dict(self) -> dict:
        """מטען לתצוגה בדפדפן (שקיפות למשתמש) ולכרטיס הסיכום של ההדגמה."""
        return {
            "ok": self.ok,
            "error_he": self.error_he,
            "quality": self.quality.as_dict() if self.quality else None,
            "features": self.features.as_dict() if self.features else None,
            "description_he": (self.description.text_he
                               if self.description and self.description.ok
                               else None),
            "description_error_he": (self.description.error_he
                                     if self.description and not self.description.ok
                                     else None),
            "outside_scope": self.outside_scope,
            "meta": dict(self.meta),
        }


def _build_context(analysis: ImageAnalysis) -> str:
    """בלוק ההקשר שמוזרק לסוכנים — קצר, עובדתי, ובלי שום מסקנה רפואית."""
    lines = [CONTEXT_HEADER_HE]
    if analysis.quality:
        lines.append(f"איכות התמונה: {analysis.quality.summary_he}")
    if analysis.features:
        lines.append(f"מדידות: {analysis.features.summary_he()}")
    if analysis.description and analysis.description.ok:
        lines.append(f"תיאור חזותי: {analysis.description.text_he}")
    elif analysis.description:
        lines.append("תיאור חזותי: לא זמין — יש להסתמך על המדידות ועל "
                     "מה שהמשתמש מספר.")
    if analysis.quality and not analysis.quality.usable:
        lines.append("התמונה אינה ברורה מספיק — מותר לבקש תמונה נוספת "
                     "טובה יותר, ואין להסיק ממנה מסקנות.")
    if analysis.not_a_body:
        lines.append(NOT_A_BODY_INSTRUCTION_HE)
    elif analysis.out_of_scope_markers:
        lines.append(OUT_OF_SCOPE_INSTRUCTION_HE)
    return "\n".join(lines)


def analyze_image(data: bytes, *, describe: bool = True) -> ImageAnalysis:
    """
    בייטים של תמונה -> ניתוח מלא. לעולם לא זורק.

    describe=False מדלג על מודל הראייה (בדיקות, הדגמה חינמית) — שאר
    השכבות עובדות כרגיל.
    """
    ingested = ingest_image(data)
    if not ingested.ok or ingested.image is None:
        return ImageAnalysis(ok=False, error_he=ingested.error_he)

    rgb = np.asarray(ingested.image, dtype=np.uint8)
    quality = assess_quality(rgb)
    features = extract_features(rgb)

    description: DescriptionResult | None = None
    if describe:
        if quality.usable:
            description = describe_image(to_jpeg_bytes(ingested.image))
        else:
            # תמונה שאינה שמישה — לא משלמים על תיאור שלה. המדידות
            # והבקשה לתמונה טובה יותר הן התוצר.
            description = DescriptionResult(
                ok=False,
                error_he="התמונה לא עברה את בדיקת האיכות — לא נשלחה לתיאור.",
            )

    text = description.text_he if (description and description.ok) else ""
    analysis = ImageAnalysis(
        ok=True,
        quality=quality,
        features=features,
        description=description,
        out_of_scope_markers=find_out_of_scope(text),
        not_a_body=is_not_a_body_image(text),
        meta=dict(ingested.meta),
    )
    analysis.context_he = _build_context(analysis)
    return analysis
