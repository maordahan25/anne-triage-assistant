"""
שכבת הראייה של "אן" — תמונה שמעשירה את האנמנזה, ולא מאבחנת.

המשתמש מצרף תמונה להודעה (למשל של חתך), והמערכת מפיקה ממנה *הקשר*
לתשאול: האם התמונה בכלל שמישה, מה אפשר למדוד ממנה, ומה נראה בה. ההכרעה
הרפואית נשארת בדיוק במקום שבו הייתה — אצל הרופא המומחה ואצל Dr. Dexter.
אין כאן סוכן חדש ואין תפקיד חדש: התוצר מוזרק לפרומפטים הקיימים כמו
הקשר השעה ומזג האוויר.

שלוש שכבות (Pillow + numpy בלבד — בלי OpenCV, ראה llm_requirements.txt):
    ingest.py    אבטחה: סוג לפי תוכן, מגבלות גודל/ממדים, הסרת EXIF, הקטנה
    quality.py   (א) האם התמונה שמישה — חדות (שונות לפלסיאן) וחשיפה
    features.py  (ב) מדידות דטרמיניסטיות — אדמומיות, ריכוז, בהירות
    describe.py  (ג) תיאור מילולי ממודל הראייה — מתאר בלבד, לא מאבחן
    scope.py     גבול הסקופ: תיאור שחורג מארבעת התחומים אוסר טיפול
    analyze.py   המנצח: analyze_image(bytes) -> ImageAnalysis

פרטיות: התמונה מעובדת בזיכרון ואינה נשמרת בשום מקום; ה-EXIF (ובו GPS
ודגם מכשיר) מוסר לפני כל עיבוד; לוג השיחות לא מקבל מהתמונה שום נתון.

הייבוא עצל (PEP 562) כמו ב-ml/: מודול הראייה לא נטען עד שמישהו באמת
מעלה תמונה, ולכן import של השרת אינו גורר Pillow/numpy מיותרים.
"""
from __future__ import annotations

_EXPORTS = {
    "ImageAnalysis": "analyze", "analyze_image": "analyze",
    "ingest_image": "ingest", "strip_exif": "ingest",
    "to_jpeg_bytes": "ingest", "IngestResult": "ingest",
    "MAX_FILE_BYTES": "ingest", "ALLOWED_FORMATS": "ingest",
    "assess_quality": "quality", "laplacian_variance": "quality",
    "QualityReport": "quality",
    "extract_features": "features", "FeatureReport": "features",
    "red_mask": "features",
    "describe_image": "describe", "vision_enabled": "describe",
    "vision_model_name": "describe", "DescriptionResult": "describe",
    "find_out_of_scope": "scope", "is_not_a_body_image": "scope",
    "OUT_OF_SCOPE_INSTRUCTION_HE": "scope", "OUT_OF_SCOPE_MARKERS": "scope",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name in _EXPORTS:
        from importlib import import_module

        return getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
