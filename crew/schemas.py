"""
סכמות הפלט המובנה (Pydantic) של צוות הסוכנים.

שני חוזים מרכזיים:
  * SafetyVerdict    — פסיקת סוכן הבטיחות (Dr. Dexter) על כל תור-שיחה.
  * SpecialistAdvice — המלצת הרופא המומחה, כולל illustration_id מהרשימה הסגורה.

הסכמות הן "שכבת ההגנה" בין טקסט חופשי של LLM לבין הקוד: illustration_id
שאינו ברשימה הסגורה מאולץ ל-None, הפניית חירום ריקה מוחלפת בנוסח בטוח קבוע,
ומקור שאינו תואם לאף שורת 'מקור:' ממסמכי data/ מסונן החוצה — כך שהבטיחות
והשקיפות אינן תלויות בניסוח מוצלח של המודל.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from rag.config import DATA_DIR

from .illustrations import validate_illustration_id


# ── אימות מקורות מול המאגר (הגנת קוד לסעיף השקיפות) ─────────────────────
# באג מאומת מריצה אמיתית: בפניות topic=other הוחזרו "מקורות" שאינם קיימים
# במאגר ("המרפאה לרפואת שיניים", "מאמרים רפואיים"). אמת המידה: שורות
# 'מקור:' של כל מסמכי data/ — מקור שלא תואם לאף אחת מהן לא מגיע למשתמש.

# תווי מקף נפוצים מנורמלים לצורה אחת — מודל שמצטט עם "–" (en dash) במקום
# "—" (em dash) עדיין מציין מקור אמיתי, והסינון לא אמור להפיל אותו.
_DASHES = re.compile(r"[-–—־]+")


def _normalize_source(text: str) -> str:
    """נרמול להשוואת מקורות: רווחים, סוגי מקפים ורישיות לטינית."""
    collapsed = " ".join((text or "").split())
    return _DASHES.sub("-", collapsed).casefold()


@lru_cache(maxsize=1)
def known_source_lines() -> tuple[str, ...]:
    """כל שורות 'מקור:' ממסמכי data/ (כל התחומים), מנורמלות-רווחים."""
    lines: list[str] = []
    for md in sorted(DATA_DIR.glob("*/*.md")):
        for line in md.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("מקור:"):
                lines.append(" ".join(stripped[len("מקור:"):].split()))
    return tuple(lines)


def source_is_known(source: str) -> bool:
    """
    האם מקור שציטט רופא תואם לשורת 'מקור:' כלשהי במאגר. ההתאמה סלחנית
    בכוונה (אחרי נרמול מקפים/רווחים/רישיות) — מקור אמיתי שנוסח בקיצור
    עובר, מקור מומצא לא:
      * ה-URL של השורה מופיע בציטוט, או
      * חלק-השם של השורה (לפני ה-URL) מוכל בציטוט, או
      * הציטוט כולו מוכל בשורה (ניסוח חלקי של שם המקור).
    """
    normalized = _normalize_source(source)
    if not normalized:
        return False
    for known in known_source_lines():
        url = next((tok for tok in known.split() if tok.startswith("http")), None)
        title = known.split(" — http")[0].strip()
        known_n = _normalize_source(known)
        if url and _normalize_source(url) in normalized:
            return True
        title_n = _normalize_source(title)
        if title_n and (title_n in normalized or normalized in known_n):
            return True
    return False


# observability לסינון: המקורות שנפסלו בוולידציה האחרונה נשמרים כאן, כדי
# שה-pipeline ידווח אותם (ANNE_VERBOSE) והבדיקות יוכלו להציגם — בלעדיו
# "מקורות: ללא" אינו מבחין בין רופא שלא ציטט לסינון של ציטוט שגוי.
_FILTERED_SOURCES: list[str] = []


def pop_filtered_sources() -> list[str]:
    """המקורות שסוננו מאז הקריאה הקודמת (מרוקן את הרשימה)."""
    global _FILTERED_SOURCES
    dropped, _FILTERED_SOURCES = _FILTERED_SOURCES, []
    return dropped

# נוסח חירום קבוע (fallback): מוצג אם סוכן הבטיחות פסק חירום אך לא ניסח הפניה.
DEFAULT_EMERGENCY_REFERRAL_HE = (
    "אני עוצרת כאן את השיחה, כי התסמינים שתיארת מחייבים בדיקה רפואית דחופה. "
    "אנא פנה/י עכשיו למיון הקרוב, ואם המצב מחמיר — חייג/י מיד למד\"א 101. "
    "אם עולות מחשבות על פגיעה עצמית, ער\"ן זמינים 24/7 בטלפון 1201. "
    "אני לא יכולה לטפל במצב כזה מרחוק — הדבר הבטוח ביותר הוא בדיקה מקצועית מיידית."
)

Topic = Literal["wounds", "anxiety", "dehydration", "cold", "other"]


class AnneDecision(BaseModel):
    """החלטת אן בתחילת תור: להשיב/לתשאל ישירות, או לבקש ייעוץ מהצוות."""

    action: Literal["reply", "consult"] = Field(
        description=(
            "reply — תשובה ישירה למשתמש (פתיחה, שיחה, שאלות אנמנזה); "
            "consult — יש די מידע והמקרה מועבר לצוות הרופאים"
        )
    )
    reply_he: Optional[str] = Field(
        default=None,
        description="כש-action=reply: התשובה המלאה למשתמש בקולה של אן; אחרת None",
    )
    consult_query_he: Optional[str] = Field(
        default=None,
        description=(
            "כש-action=consult: סיכום מקרה תמציתי בעברית לרופאים — תסמינים, "
            "משך, נסיבות, גיל ומיקום אם ידועים; אחרת None"
        ),
    )
    topic_hint: Optional[Topic] = Field(
        default=None,
        description="כש-action=consult: התחום המשוער, כרמז לניתוב; אחרת None",
    )
    locality_he: Optional[str] = Field(
        default=None,
        description=(
            "שם היישוב/העיר שהמשתמש הזכיר, כלשונו וללא תוספות (למשל "
            "'רעננה') — משמש להקשר מזג אוויר ולהפניה לפי מיקום; None אם "
            "לא הוזכר יישוב"
        ),
    )


class SafetyVerdict(BaseModel):
    """פסיקת הבטיחות של Dr. Dexter על תור-שיחה בודד."""

    is_emergency: bool = Field(
        description="האם זוהה דגל אדום המחייב עצירה מיידית והפניה לעזרה מקצועית"
    )
    red_flags: list[str] = Field(
        default_factory=list,
        description="הדגלים האדומים שזוהו, בעברית (למשל: כאב חזה, קוצר נשימה); ריק אם אין",
    )
    reasoning_he: str = Field(
        description="נימוק קצר בעברית לפסיקה (לתיעוד פנימי, לא מוצג למשתמש)"
    )
    referral_he: Optional[str] = Field(
        default=None,
        description=(
            "הודעת ההפניה למשתמש בקולה של אן — חובה כשיש חירום: מה זוהה, "
            "לאן לפנות עכשיו (מיון / מד\"א 101 / ער\"ן 1201) ומה לא לעשות "
            "בינתיים. אל תכתוב כאן שמות של בתי חולים או מוקדים ואל תמציא "
            "כתובות/טלפונים — רשימת היעדים לפי מיקום ושעה נוספת אוטומטית "
            "מתוך מאגר מאומת. None כשאין חירום."
        ),
    )
    referral_level: Optional[Literal["critical", "urgent_care"]] = Field(
        default=None,
        description=(
            "רמת ההפניה, רק כשיש חירום: critical — חשד למצב מסכן חיים "
            "(כאב/לחץ בחזה, חשד לשבץ, קוצר נשימה משמעותי, אובדן הכרה, "
            "פרכוס, דימום בלתי נשלט, תגובה אלרגית חמורה, הרעלה, מכת חום, "
            "מחשבות אובדניות) — 101 ומיון; urgent_care — נדרשת בדיקת "
            "רופא/ה היום אך לא מיון (חתך שדורש תפרים, חום גבוה מתמשך, "
            "חשד לשבר קל). בכל ספק — critical. None כשאין חירום."
        ),
    )

    @model_validator(mode="after")
    def _ensure_referral_on_emergency(self) -> "SafetyVerdict":
        # חירום בלי נוסח הפניה -> נוסח בטוח קבוע. לעולם לא חירום "שקט".
        if self.is_emergency and not (self.referral_he and self.referral_he.strip()):
            self.referral_he = DEFAULT_EMERGENCY_REFERRAL_HE
        # רמה חסרה בחירום -> critical. ברירת המחדל בספק היא תמיד המחמירה;
        # הורדת רמה יכולה להגיע רק מהמודל *ובמפורש*, והקוד עוד עשוי
        # להעלות אותה בחזרה (crew/emergency_referral.escalate_level).
        if self.is_emergency and self.referral_level not in {"critical",
                                                             "urgent_care"}:
            self.referral_level = "critical"
        return self


class SpecialistAdvice(BaseModel):
    """המלצת הרופא המומחה שאליו נותב תור-השיחה."""

    topic: Topic = Field(
        description=(
            "התחום שאליו סווגה הפנייה: wounds / anxiety / dehydration / cold, "
            "או other אם הנושא מחוץ לארבעת התחומים"
        )
    )
    advice_he: str = Field(
        description="עיקרי הטיפול הביתי הבטוח בעברית, מבוסס אך ורק על הידע שנשלף מהמאגר"
    )
    follow_up_questions_he: list[str] = Field(
        default_factory=list,
        description="שאלות אנמנזה קצרות שכדאי שאן תשאל אם חסר מידע חיוני; ריק אם אין",
    )
    illustration_id: Optional[str] = Field(
        default=None,
        description=(
            "מזהה איור מתוך הרשימה הסגורה שסופקה בהנחיה, רק בהתאמה ודאית "
            "לטיפול המומלץ; אחרת None"
        ),
    )
    sources: list[str] = Field(
        default_factory=list,
        description="שמות המקורות שעליהם מבוססת ההמלצה, כפי שהופיעו בקטעים שנשלפו",
    )

    @field_validator("illustration_id", mode="before")
    @classmethod
    def _validate_illustration(cls, value):
        # אימות מול הרשימה הסגורה: מזהה לא מוכר -> None (בלי איור, בלי חריגה).
        return validate_illustration_id(value)

    @model_validator(mode="after")
    def _filter_sources(self) -> "SpecialistAdvice":
        # הגנת קוד (באג מאומת): מקור מומצא לעולם לא מגיע למשתמש.
        # ב-topic=other אין שליפה רלוונטית — sources חייב להיות ריק;
        # בשאר התחומים נשמרים רק מקורות שתואמים לשורת 'מקור:' במאגר
        # (התאמה סלחנית — ראה source_is_known). הנפסלים נרשמים לדיווח.
        # ניקוי קוסמטי לפני הסינון: מודלים לפעמים מעתיקים גם את הקידומת
        # "מקור:" מהקטע — מוסרת כדי שלא תוכפל בתצוגה ("מקור: מקור: ...").
        cleaned: list[str] = []
        for source in self.sources:
            normalized = " ".join((source or "").split())
            if normalized.startswith("מקור:"):
                normalized = normalized[len("מקור:"):].strip()
            if normalized:
                cleaned.append(normalized)
        if self.topic == "other":
            kept, dropped = [], cleaned
        else:
            kept = [s for s in cleaned if source_is_known(s)]
            dropped = [s for s in cleaned if not source_is_known(s)]
        if dropped:
            _FILTERED_SOURCES.extend(dropped)
        self.sources = kept
        return self
