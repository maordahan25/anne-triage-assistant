"""
שכבה (ג) — תיאור מילולי מהתמונה, ממודל הראייה של OpenAI.

**מתאר בלבד.** ההנחיה למודל אוסרת עליו מפורשות לאבחן, לתת שם למחלה או
להמליץ על טיפול; מה שהוא מחזיר הוא מה שרואים — מיקום, גודל יחסי, צבע,
שוליים, הפרשה, העור סביב. ההכרעה הרפואית נשארת אצל הרופא המומחה ואצל
Dr. Dexter, שמקבלים את התיאור כהקשר נוסף לתשאול.

שלוש החלטות שנשמרות כאן:
  * **נפילה חיננית.** אין מפתח, אין רשת, המודל החזיר שגיאה או שהתשובה
    ריקה -> `DescriptionResult(ok=False)` ותו לא. המדידות משכבה (ב)
    עדיין נשלחות לתשאול והשיחה ממשיכה כרגיל — שכבת הראייה היא תוספת,
    לא תלות.
  * **detail="low"** — לתיאור כללי של פצע אין צורך ב-tiles ברזולוציה
    גבוהה, וזה מה שהופך את הקריאה לזולה (ראה עלות ב-README).
  * **ייבוא עצל של openai** — כדי שהמודול ייטען (ויימדד בבדיקות) בסביבה
    בלי הספרייה ובלי רשת.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass

# מודל הראייה: ברירת מחדל בדרגה הבינונית (אותה דרגה של אן), ניתן לעקיפה.
# משתמש באותו OPENAI_API_KEY מ-.env כמו שאר המערכת.
VISION_MODEL_ENV = "ANNE_VISION_MODEL"
DEFAULT_VISION_MODEL = "gpt-4o-mini"
REQUEST_TIMEOUT_S = 25.0
MAX_OUTPUT_TOKENS = 220

# ההנחיה — היא הגבול בין "הקשר לתשאול" לבין "אבחון". כל שינוי כאן הוא
# שינוי במדיניות הבטיחות של הפרויקט, לא ניסוח.
SYSTEM_PROMPT_HE = (
    "אתה עוזר תיאור חזותי בצוות רפואי, ואתה מתאר תמונות בעברית.\n"
    "מותר לך אך ורק לתאר מה נראה בתמונה. אסור לך, בכל מצב:\n"
    "• לאבחן או להעריך מהו המצב הרפואי;\n"
    "• לתת שם למחלה, לזיהום או לסוג פציעה ('כוויה מדרגה שנייה', "
    "'צלוליטיס', 'אבצס') — תאר מראה, לא אבחנה;\n"
    "• להמליץ על טיפול, על תרופה או על פנייה לגורם כלשהו;\n"
    "• להעריך חומרה ('קל', 'חמור', 'דחוף').\n"
    "מה כן: 2-4 משפטים קצרים בעברית פשוטה, ובהם — איזה חלק גוף נראה (אם "
    "אפשר לזהות), גודל האזור ביחס לסביבתו, צבעים, צורת השוליים, האם "
    "נראית הפרשה או קרום, ומה מצב העור סביב. אם התמונה אינה מציגה גוף "
    "אדם — אמור זאת במשפט אחד. אם משהו אינו ברור — אמור 'לא ניתן לראות "
    "בבירור' במקום לנחש."
)

USER_PROMPT_HE = (
    "תאר את התמונה לפי ההנחיות. תיאור בלבד, בלי אבחנה, בלי שם למצב "
    "רפואי ובלי המלצת טיפול."
)


@dataclass
class DescriptionResult:
    """תוצאת קריאת מודל הראייה — או הסיבה שלא הייתה."""

    ok: bool
    text_he: str | None = None
    model: str | None = None
    error_he: str | None = None

    def as_dict(self) -> dict:
        return {"ok": self.ok, "text_he": self.text_he, "model": self.model,
                "error_he": self.error_he}


def vision_model_name() -> str:
    return os.getenv(VISION_MODEL_ENV, DEFAULT_VISION_MODEL).strip() \
        or DEFAULT_VISION_MODEL


def vision_enabled() -> bool:
    """
    האם בכלל אפשר לקרוא למודל הראייה: מפתח קיים והשכבה לא כובתה במפורש.
    ANNE_VISION=0 מכבה את הקריאה (הדגמה חינמית, בדיקות, סביבה בלי רשת) —
    המדידות הדטרמיניסטיות ממשיכות לעבוד.
    """
    if os.getenv("ANNE_VISION", "1").strip().lower() in {"0", "false", "no"}:
        return False
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def describe_image(jpeg_bytes: bytes) -> DescriptionResult:
    """
    תיאור טקסטואלי קצר של התמונה. לעולם לא זורק — כל כשל מוחזר כערך.
    """
    if not vision_enabled():
        return DescriptionResult(
            ok=False,
            error_he="מודל הראייה אינו זמין (אין מפתח API או שהשכבה כובתה).",
        )
    if not jpeg_bytes:
        return DescriptionResult(ok=False, error_he="אין תמונה לשליחה.")

    model = vision_model_name()
    try:
        from openai import OpenAI   # ייבוא עצל: אין תלות בזמן import

        client = OpenAI(timeout=REQUEST_TIMEOUT_S)
        encoded = base64.b64encode(jpeg_bytes).decode("ascii")
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_HE},
                {"role": "user", "content": [
                    {"type": "text", "text": USER_PROMPT_HE},
                    {"type": "image_url", "image_url": {
                        # detail=low: מספיק לתיאור כללי, ומוזיל את הקריאה
                        "url": f"data:image/jpeg;base64,{encoded}",
                        "detail": "low",
                    }},
                ]},
            ],
        )
        text = (response.choices[0].message.content or "").strip()
    except Exception as exc:                      # רשת/מכסה/מפתח/שינוי API
        return DescriptionResult(
            ok=False, model=model,
            error_he=f"קריאת מודל הראייה נכשלה ({type(exc).__name__}).",
        )

    if not text:
        return DescriptionResult(ok=False, model=model,
                                 error_he="מודל הראייה החזיר תשובה ריקה.")
    return DescriptionResult(ok=True, text_he=text, model=model)
