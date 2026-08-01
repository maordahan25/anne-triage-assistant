"""
שכבת האיורים: טעינת הרשימה הסגורה ואימות illustration_id.

מקור האמת הוא illustrations/illustrations.json (ראה שקף 13 במצגת):
איורים שנבדקו מראש ושמורים במערכת. כשמזוהה התאמה ודאית בין הטיפול לאיור —
הוא מוצג; כשאין התאמה — לא מוצג שום איור, כדי לא ליצור הטעיה.

לכן העיקרון כאן: מזהה שאינו ברשימה הסגורה מתורגם ל-None (אין איור),
לעולם לא לחריגה — עדיף בלי איור מאשר איור שגוי.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from rag.config import PROJECT_ROOT

ILLUSTRATIONS_JSON = PROJECT_ROOT / "illustrations" / "illustrations.json"

# מיפוי תגית topic (שם תיקיית הדאטה) -> קטגוריית האיורים בעברית ב-JSON.
# הקטגוריה "כללי" (שטיפת ידיים, מדידת חום) רלוונטית לכל התחומים.
TOPIC_TO_CATEGORY = {
    "wounds": "פצעים וחתכים",
    "anxiety": "חרדה",
    "dehydration": "התייבשות",
    "cold": "הצטננות וצינון",
}
GENERAL_CATEGORY = "כללי"


@lru_cache(maxsize=1)
def load_illustrations() -> dict[str, dict]:
    """טעינת מאגד האיורים מה-JSON (פעם אחת). מזהה -> רשומת איור."""
    with open(ILLUSTRATIONS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return data["illustrations"]


def valid_ids() -> frozenset[str]:
    """קבוצת כל מזהי האיורים המאושרים (הרשימה הסגורה)."""
    return frozenset(load_illustrations())


def validate_illustration_id(illustration_id: str | None) -> str | None:
    """
    בדיקת מזהה מול הרשימה הסגורה: מזהה מאושר מוחזר כמות שהוא,
    כל ערך אחר (כולל ריק / "null" טקסטואלי) -> None.
    """
    if not illustration_id or not isinstance(illustration_id, str):
        return None
    candidate = illustration_id.strip()
    if candidate.lower() in {"", "null", "none"}:
        return None
    return candidate if candidate in load_illustrations() else None


def catalog_for_topic(topic: str) -> str:
    """
    תיאור טקסטואלי (לעברית, לפרומפט) של האיורים המותרים לתחום נתון:
    האיורים של קטגוריית התחום + הקטגוריה הכללית. משמש את הרופא המומחה
    כדי לבחור illustration_id אך ורק מתוך הרשימה הסגורה.

    לכל איור מצורף תקציר שלביו (מתוך steps) — כך המודל משווה את פעולת
    הטיפול שהמליץ עליה לתוכן האיור בפועל, ולא רק לשמו.
    """
    category = TOPIC_TO_CATEGORY.get(topic)
    lines: list[str] = []
    for iid, record in load_illustrations().items():
        if record.get("category") in {category, GENERAL_CATEGORY}:
            steps = "; ".join(record.get("steps", []))
            lines.append(f"- {iid}: {record.get('name', '')} (שלבים: {steps})")
    return "\n".join(lines)


# ── fallback דטרמיניסטי לבחירת איור (בלי LLM) ───────────────────────────
# באג מאומת בתחום cold: הרופא (המודל החסכוני) המליץ בדיוק על פעולות שיש
# להן איורים (שטיפת אף במי מלח, שאיפת אדים) אך החזיר illustration_id=null.
# כשזה קורה, ה-pipeline מפעיל התאמת מילות מפתח בין נוסח ההמלצה לשמות
# ולשלבי האיורים — של קטגוריית התחום בלבד (לא "כללי", כדי לא להציע
# שטיפת ידיים לכל דבר). מוחזר מזהה רק בהתאמה מובהקת; בספק — None.

# תחיליות שימוש נפוצות בעברית שמוסרות לפני ההשוואה (ו' החיבור, בכל"ם...).
_HEB_PREFIXES = "ובלמכשה"


def _variant_sets(text: str) -> list[set[str]]:
    """
    רצף המילים בטקסט, כל מילה כקבוצת גרסאות-גזע להשוואה: המילה כמות
    שהיא וגם בלי אות תחילית אפשרית, חתוכות ל-4 תווים ("שטיפת"/"ושטיפות"
    -> "שטיפ"). מספרים נשמרים כמות שהם ("הארקה 5-4-3-2-1"). מילים קצרות
    מדי מיוצגות כקבוצה ריקה (לא משתתפות בהתאמה).
    """
    sequence: list[set[str]] = []
    for word in re.findall(r"[א-ת]+|\d+", text or ""):
        variants: set[str] = set()
        if word.isdigit():
            variants.add(word)
        elif len(word) >= 3:
            variants.add(word[:4])
            if word[0] in _HEB_PREFIXES and len(word) >= 4:
                variants.add(word[1:][:4])
        sequence.append(variants)
    return sequence


def _unigram_hits(target: list[set[str]], advice_flat: set[str]) -> int:
    """כמה מילות-יעד שונות מופיעות בהמלצה (ספירה לפי מילים, לא גרסאות)."""
    seen: set[frozenset[str]] = set()
    for variants in target:
        if variants and variants & advice_flat:
            seen.add(frozenset(variants))
    return len(seen)


def _bigram_hits(target: list[set[str]], advice: list[set[str]]) -> int:
    """
    כמה צמדי מילים עוקבות מהיעד מופיעים כצמד עוקב גם בהמלצה ("שטיפת אף",
    "במי מלח") — הראיה החזקה ביותר לכך שההמלצה נוקבת בפעולה המאוירת.
    """
    advice_pairs = [(a, b) for a, b in zip(advice, advice[1:]) if a and b]
    hits = 0
    for t1, t2 in zip(target, target[1:]):
        if t1 and t2 and any((t1 & a1) and (t2 & a2) for a1, a2 in advice_pairs):
            hits += 1
    return hits


def suggest_illustration(
    topic: str, advice_he: str, exclude: "frozenset[str] | set[str] | tuple" = (),
) -> str | None:
    """
    בחירת איור דטרמיניסטית לפי נוסח ההמלצה — בלי LLM.

    שני שימושים ב-pipeline: (1) fallback כשהמודל החזיר null; (2) חיפוש
    *חלופה* לאיור שכבר הוצג בשיחה — ואז מועברים ב-exclude המזהים שהוצגו.

    כל איור בקטגוריית התחום מנוקד לפי חפיפה בין נוסח ההמלצה לשמו ולשלביו.
    "התאמה מובהקת" (תנאי סף) — אחד מאלה:
      * צמד מילים עוקבות מהשם מופיע בהמלצה (למשל "שאיפת אדים"), או
      * לפחות 2 מילות-שם שונות מופיעות בהמלצה, או
      * לפחות 2 צמדי מילים עוקבות מהשלבים מופיעים בהמלצה (המלצה
        שמנוסחת תפעולית, כמו "שתו מים בלגימות קטנות").
    בלי סף כזה — None: עדיף בלי איור מאשר ניחוש. לכן גם החיפוש עם
    exclude מחזיר None כשאין בקטגוריית התחום חלופה *מתאימה* — ולא איור
    שרירותי רק כדי לא לחזור על עצמנו.
    """
    category = TOPIC_TO_CATEGORY.get(topic)
    if not category:
        return None
    advice_seq = _variant_sets(advice_he)
    if not advice_seq:
        return None
    advice_flat: set[str] = set().union(*advice_seq)
    excluded = frozenset(exclude or ())

    best_id, best_score = None, 0
    for iid, record in load_illustrations().items():
        if record.get("category") != category or iid in excluded:
            continue
        name_seq = _variant_sets(record.get("name", ""))
        steps_seq: list[set[str]] = []
        for step in record.get("steps", []):
            steps_seq.extend(_variant_sets(step))
            steps_seq.append(set())  # מפריד — צמדים לא נמתחים בין שלבים
        name_bi = _bigram_hits(name_seq, advice_seq)
        name_uni = _unigram_hits(name_seq, advice_flat)
        step_bi = _bigram_hits(steps_seq, advice_seq)
        if not (name_bi >= 1 or name_uni >= 2 or step_bi >= 2):
            continue  # אין התאמה מובהקת — האיור לא מועמד
        step_uni = _unigram_hits(steps_seq, advice_flat)
        score = name_bi * 4 + name_uni * 2 + step_bi * 2 + step_uni
        if score > best_score:
            best_id, best_score = iid, score
    return best_id


def get_illustration(illustration_id: str) -> dict | None:
    """שליפת רשומת איור מלאה (שם, קובץ, שלבים) לפי מזהה מאושר; אחרת None."""
    validated = validate_illustration_id(illustration_id)
    if validated is None:
        return None
    return {"id": validated, **load_illustrations()[validated]}


if __name__ == "__main__":
    # הרצה ישירה: בדיקה ידנית של הטעינה והאימות (ללא LLM).
    ids = valid_ids()
    print(f"נטענו {len(ids)} איורים מאושרים.")
    print("בדיקות אימות:")
    print("  breathing_exercise ->", validate_illustration_id("breathing_exercise"))
    print("  לא-קיים            ->", validate_illustration_id("no_such_id"))
    print("  None               ->", validate_illustration_id(None))
    print("\nקטלוג לתחום anxiety:")
    print(catalog_for_topic("anxiety"))
