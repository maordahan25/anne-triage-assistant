"""
שכבת הקליטה של תמונה — הגבול בין קלט לא-מהימן לבין הקוד של אן.

העלאת קובץ היא משטח תקיפה, ולכן כאן נעשות *כל* הבדיקות לפני שמישהו נוגע
בפיקסלים:

1. **סוג לפי תוכן, לא לפי סיומת.** שם קובץ ו-Content-Type מגיעים מהלקוח
   ואפשר לשקר בהם; Pillow מזהה את הפורמט מהבייטים עצמם, ורק JPEG/PNG/WebP
   מתקבלים. "shell.php.jpg" ייפול כאן.
2. **מגבלת גודל ומגבלת ממדים.** קובץ ענק או תמונה של 30,000×30,000 הם
   decompression bomb קלאסי (זיכרון מתפוצץ לפני שהעיבוד מתחיל) — הגודל
   נבדק על הבייטים, והממדים נבדקים מה-header לפני `load()`, כלומר לפני
   שהתמונה מפוענחת לזיכרון.
3. **הסרת EXIF.** מטא-דאטה של תמונה מכילה לעיתים קרובות קואורדינטות GPS
   ודגם מכשיר — מידע מזהה, בדיוק מה ששכבת הפרטיות של אן קיימת כדי שלא
   יישמר. התמונה נבנית מחדש מהפיקסלים בלבד: לאובייקט החדש אין `info`
   ואין EXIF, וזה קורה *לפני* כל עיבוד ולפני כל שליחה החוצה.
4. **הקטנה.** לעיבוד ולשליחה למודל הראייה מספיקה תמונה של עד 1024px
   בצלע הארוכה — פחות זיכרון, פחות טוקנים, אותה מסקנה.

הפונקציה לעולם לא זורקת על קלט פסול: היא מחזירה `IngestResult` עם
`ok=False` והודעה בעברית, כדי שהשרת יחזיר 400 מסודר ולא 500.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image, ImageOps, UnidentifiedImageError

# Pillow עצמה מגבילה מספר פיקסלים (DecompressionBombWarning); מקטינים
# את התקרה לערך שפוי לשימוש הזה — תמונה של פצע מהטלפון.
Image.MAX_IMAGE_PIXELS = 50_000_000

ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")
MAX_FILE_BYTES = 6 * 1024 * 1024        # 6MB — תמונת טלפון רגילה קטנה מזה
MAX_SOURCE_PIXELS = 40_000_000          # ~40MP: מעבר לזה זו לא תמונת פצע
MAX_EDGE_PX = 1024                      # הצלע הארוכה אחרי ההקטנה
MIN_EDGE_PX = 64                        # קטן מזה — אין מה למדוד


@dataclass
class IngestResult:
    """תוצאת הקליטה: תמונה נקייה ומוקטנת, או סירוב עם סיבה בעברית."""

    ok: bool
    image: "Image.Image | None" = None
    error_he: str | None = None
    meta: dict = field(default_factory=dict)


def _reject(message: str) -> IngestResult:
    return IngestResult(ok=False, error_he=message)


def strip_exif(image: "Image.Image") -> "Image.Image":
    """
    תמונה חדשה מהפיקסלים בלבד — בלי EXIF, בלי ICC, בלי שום מטא-דאטה.

    `Image.new` + `putdata` היה יקר; `image.copy()` שומר את `info`. הדרך
    הנקייה היא לבנות מהנתונים הגולמיים: לאובייקט שנוצר כך אין `info`.
    """
    data = list(image.getdata())
    clean = Image.new(image.mode, image.size)
    clean.putdata(data)
    return clean


def ingest_image(data: bytes) -> IngestResult:
    """
    בייטים גולמיים -> תמונת RGB נקייה, מוקטנת ובלי מטא-דאטה.

    מחזיר IngestResult; ok=False עם error_he לכל קלט שאינו עומד בכללים.
    """
    if not data:
        return _reject("לא התקבלה תמונה.")
    if len(data) > MAX_FILE_BYTES:
        return _reject(
            f"הקובץ גדול מדי ({len(data) / 1024 / 1024:.1f}MB). "
            f"הגודל המרבי הוא {MAX_FILE_BYTES // (1024 * 1024)}MB."
        )

    try:
        probe = Image.open(io.BytesIO(data))   # קורא header בלבד
        image_format = (probe.format or "").upper()
        width, height = probe.size
    except UnidentifiedImageError:
        return _reject("הקובץ אינו תמונה תקינה (JPEG, PNG או WebP).")
    except Exception:
        return _reject("לא הצלחתי לקרוא את הקובץ כתמונה.")

    if image_format not in ALLOWED_FORMATS:
        return _reject(
            f"סוג התמונה ({image_format or 'לא מזוהה'}) אינו נתמך — "
            "יש להעלות JPEG, PNG או WebP."
        )
    if width * height > MAX_SOURCE_PIXELS:
        return _reject("התמונה גדולה מדי במידותיה. נסו תמונה קטנה יותר.")
    if min(width, height) < MIN_EDGE_PX:
        return _reject("התמונה קטנה מדי מכדי ללמוד ממנה משהו.")

    try:
        # exif_transpose לפני ההסרה: סיבוב שנרשם ב-EXIF חייב "להיצרב"
        # בפיקסלים, אחרת התמונה תגיע הפוכה אחרי שנמחק את המטא-דאטה.
        oriented = ImageOps.exif_transpose(probe)
        rgb = oriented.convert("RGB")
        rgb.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.Resampling.LANCZOS)
        clean = strip_exif(rgb)
    except Exception:
        return _reject("לא הצלחתי לעבד את התמונה. נסו תמונה אחרת.")

    return IngestResult(
        ok=True,
        image=clean,
        meta={
            "format": image_format,
            "source_width": width,
            "source_height": height,
            "width": clean.width,
            "height": clean.height,
            "bytes": len(data),
            "resized": (clean.width, clean.height) != (width, height),
            "exif_removed": True,
        },
    )


def to_jpeg_bytes(image: "Image.Image", quality: int = 85) -> bytes:
    """קידוד לשליחה החוצה (מודל הראייה) — מהתמונה הנקייה בלבד."""
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
