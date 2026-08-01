"""
בניית בלוק יעדי החירום של Dr. Dexter — לפי מיקום ולפי שעה, מקוד ולא ממודל.

למה בקוד: הפניית חירום היא המקום היחיד במערכת שבו שגיאה עולה יותר מאשר
תשובה חלשה. שם של בית חולים, מספר טלפון או "פתוח עכשיו" שהמודל המציא הם
נזק ממשי, ולכן ההפניה *אינה* נשענת על ניסוח של LLM: Dexter כותב את
הפסקה האנושית (מה זוהה, מה לא לעשות), והבלוק שמתחתיה נבנה כאן —
דטרמיניסטית, מ-data/emergency_locations.json בלבד. אותה פילוסופיה של
הזרקת השעה, מזג האוויר וה-RAG ב-pipeline, במקום שבו היא הכי חשובה.

**אין קריאות רשת בזמן שיחה.** הקובץ סטטי; הקואורדינטות הושלמו מראש
בסקריפט חד-פעמי (geocode_emergency_locations.py). מה שאין בקובץ פשוט לא
מוצג — לעולם לא מושלם מהאוויר.

שתי רמות הפניה, וההבדל ביניהן הוא כל העניין:
  * critical    — חשד לאירוע לבבי/שבץ/קוצר נשימה משמעותי וכל דגל אדום
                  מסכן חיים: 101 בראש, בולט; בתי חולים אחריו; מוקדי
                  רפואה דחופה מוצגים *עם* אזהרה מפורשת שהם אינם היעד
                  למצב הזה. אסור שההצגה תיצור רושם שאפשר לנסוע למוקד
                  במקום להתקשר.
  * urgent_care — נדרש רופא אך לא חירום מסכן חיים (חתך שדורש תפרים, חום
                  גבוה): מוקד רפואה דחופה הוא היעד המתאים, המיון הוא
                  הגיבוי.
הרמה מגיעה מ-Dexter (SafetyVerdict.referral_level), אבל אף פעם לא רק
ממנו: escalate_level() מעלה ל-critical לפי לקסיקון דגלים קריטיים בקוד,
ולעולם לא מוריד. ברירת המחדל בספק היא critical.

שלוש הכותרות (בתי חולים · ביקור רופא · טרם) מוצגות תמיד, גם כשאין מה
להציג תחתן — כדי שיהיה גלוי שכל האפשרויות נבדקו ולא נשכחו.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "emergency_locations.json"
TIMEZONE = "Asia/Jerusalem"

# ── כמה להציג ומאיזה מרחק ────────────────────────────────────────────────
# רזולוציית הקואורדינטות היא יישוב (ראה geocode_emergency_locations.py),
# ולכן הרדיוסים נדיבים בכוונה: הם מסננים "אחר לגמרי" ולא מתיימרים לדייק
# בקילומטרים. מעבר לרדיוס מוצג ה-empty_text — "לא נמצא באזור" — וזו
# אמירה נכונה יותר מלשלוח מישהו למוקד במרחק שעתיים.
MAX_HOSPITALS = 3
MAX_BRANCHES_PER_CHAIN = 2
HOSPITAL_RADIUS_KM = 70.0
URGENT_CARE_RADIUS_KM = 40.0

DAY_KEYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")

# לקסיקון הסלמה: כל אחד מאלה מכריח critical, גם אם המודל אמר אחרת.
# שמרני בכוונה — כאן עדיף false positive (הפניה למיון) על false negative.
_CRITICAL_PATTERNS = (
    "כאב בחזה", "כאבים בחזה", "לחץ בחזה", "כאב חזה", "התקף לב", "אוטם",
    "שבץ", "אירוע מוחי", "חולשת צד", "שיתוק", "דיבור לא ברור", "דיבור משובש",
    "עיוות פנים", "אובדן הכרה", "איבוד הכרה", "לא מגיב", "התעלף", "עילפון",
    "קוצר נשימה", "קושי בנשימה", "קשיי נשימה", "לא מצליח לנשום", "חנק",
    "פרכוס", "עווית", "דימום מסיבי", "דימום שאינו נפסק", "דימום בלתי נשלט",
    "אנפילקסי", "נפיחות בגרון", "נפיחות בפנים", "הרעלה", "בלע חומר",
    "מכת חום", "חום גוף גבוה מאוד", "מחשבות אובדניות", "פגיעה עצמית",
    "אובדנות", "טראומת ראש", "פגיעת ראש",
)

Level = str  # "critical" | "urgent_care"
CRITICAL, URGENT_CARE = "critical", "urgent_care"


# ── טעינת המאגר ──────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def load_locations(path: str | None = None) -> dict:
    """
    קריאת מאגר יעדי החירום. קובץ חסר/פגום -> מילון ריק, לא חריגה:
    ההפניה הארצית הקבועה עדיין תוצג, ושיחת חירום לא תישבר בגלל קובץ.
    """
    try:
        target = Path(path) if path else DATA_FILE
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── התאמת יישוב (בלי רשת: רק מה שכתוב בקובץ) ─────────────────────────────
_PREFIX = re.compile(r"^(?:ב|מ|ל|ה)(?=[א-ת]{3})")


def normalize_city(name: str) -> str:
    """נרמול שם יישוב להשוואה: גרשיים, מקפים, 'קרית'/'קריית' ותחיליות."""
    text = " ".join((name or "").split())
    text = text.replace("״", '"').replace("׳", "'").replace("-", " ")
    text = text.replace("קרית", "קריית").replace("  ", " ")
    text = _PREFIX.sub("", text)
    return text.strip(" ,.'\"")


@lru_cache(maxsize=1)
def known_cities(path: str | None = None) -> tuple[str, ...]:
    """כל שמות הערים שמופיעים במאגר (בתי חולים + מוקדים), ללא כפילויות."""
    document = load_locations(path)
    cities = {
        record.get("city")
        for record in [*document.get("hospitals", []),
                       *document.get("urgent_care_branches", [])]
        if record.get("city")
    }
    return tuple(sorted(cities, key=len, reverse=True))


def detect_locality(text: str) -> str | None:
    """
    איתור יישוב בתוך טקסט חופשי — רשת ביטחון דטרמיניסטית לצד השדה
    locality_he של אן: בתור חירום ה-triage נזרק, ולפעמים גם לא זיהה.
    מוחזר שם היישוב *כפי שהוא במאגר*, או None.
    """
    normalized = normalize_city(text or "")
    for city in known_cities():
        if normalize_city(city) in normalized:
            return city
    return None


def resolve_position(locality: str | None) -> tuple[float, float] | None:
    """
    מיקום המשתמש מתוך הקובץ בלבד: אם היישוב שהוזכר מוכר למאגר, הקואורדינטות
    שלו הן נקודת הייחוס לחישוב מרחקים. יישוב שאינו במאגר -> None, וההפניה
    נופלת לנוסח הארצי הקבוע (בלי לנחש מיקום ובלי לפנות לרשת).
    """
    if not locality:
        return None
    target = normalize_city(locality)
    document = load_locations()
    records = [*document.get("hospitals", []),
               *document.get("urgent_care_branches", [])]
    for record in records:
        city = normalize_city(record.get("city") or "")
        if not city or record.get("lat") is None:
            continue
        if city == target or city in target or target in city:
            return float(record["lat"]), float(record["lon"])
    return None


def city_matches(record: dict, locality: str | None) -> bool:
    """האם הרשומה נמצאת ביישוב שהמשתמש ציין (השוואת שמות מנורמלת)."""
    if not locality:
        return False
    city = normalize_city(record.get("city") or "")
    target = normalize_city(locality)
    return bool(city) and (city == target or city in target or target in city)


def distance_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    """מרחק אווירי (haversine) בקילומטרים."""
    lat1, lon1 = math.radians(first[0]), math.radians(first[1])
    lat2, lon2 = math.radians(second[0]), math.radians(second[1])
    inner = (math.sin((lat2 - lat1) / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(inner))


# ── שעות פתיחה ───────────────────────────────────────────────────────────
def _minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def is_open_at(hours: dict | None, when: datetime) -> bool | None:
    """
    האם המוקד פתוח ברגע נתון. מחזיר True/False, או **None כשלא ידוע** —
    הבחנה שחייבת להישמר: "לא פורסמו שעות" אינו "סגור" ואינו "פתוח", והוא
    מוצג למשתמש כ"שעות לא מאומתות" במקום להיעלם או להתחזות לפתוח.

    משמרת לילה נתמכת: טווח שסגירתו קטנה מפתיחתו (17:00-08:00) ממשיך
    למחרת, ולכן נבדק גם היום הקודם.
    """
    if not hours:
        return None
    by_day = hours.get("by_day") or {}
    index = (when.weekday() + 1) % 7          # Monday=0 -> ראשון=0
    today = by_day.get(DAY_KEYS[index], None)
    yesterday = by_day.get(DAY_KEYS[(index - 1) % 7], None)
    now = when.hour * 60 + when.minute

    if isinstance(today, dict) and today.get("open"):
        start, end = _minutes(today["open"]), _minutes(today["close"])
        if start < end and start <= now < end:
            return True
        if start > end and now >= start:      # נמשך אל תוך הלילה
            return True
    # משמרת של אמש שעדיין רצה יכולה רק *להוסיף* "פתוח" — היא לעולם לא
    # מלמדת על היום הנוכחי, ולכן היא אינה משפיעה על "ידוע/לא ידוע".
    if isinstance(yesterday, dict) and yesterday.get("open"):
        start, end = _minutes(yesterday["open"]), _minutes(yesterday["close"])
        if start > end and now < end:
            return True
    # "לא ידוע" נקבע לפי היום הנוכחי בלבד: רשומת יום חסרה (null) היא
    # חוסר מידע, ולא "סגור".
    return False if isinstance(today, dict) else None


def now_in_israel() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


# ── רמת ההפניה ───────────────────────────────────────────────────────────
def escalate_level(level: str | None, red_flags: list[str] | None,
                   user_message: str = "") -> Level:
    """
    רמת ההפניה הסופית. הכלל: הקוד רשאי רק *להחמיר*.
    ספק (רמה חסרה/לא מוכרת) -> critical; ביטוי קריטי בטקסט -> critical.
    """
    haystack = " ".join([*(red_flags or []), user_message or ""])
    if any(pattern in haystack for pattern in _CRITICAL_PATTERNS):
        return CRITICAL
    return URGENT_CARE if level == URGENT_CARE else CRITICAL


# ── בחירת היעדים ─────────────────────────────────────────────────────────
def _with_distance(records: list[dict], position: tuple[float, float],
                   radius_km: float) -> list[tuple[float, dict]]:
    scored = []
    for record in records:
        if record.get("lat") is None or record.get("lon") is None:
            continue
        away = distance_km(position, (float(record["lat"]), float(record["lon"])))
        if away <= radius_km:
            scored.append((away, record))
    return sorted(scored, key=lambda item: item[0])


def nearest_hospitals(position: tuple[float, float] | None,
                      limit: int = MAX_HOSPITALS, path: str | None = None,
                      locality: str | None = None,
                      ) -> list[tuple[float | None, dict]]:
    """
    בתי החולים הקרובים. בלי קואורדינטות למשתמש (יישוב שאינו במאגר
    הגיאוקודינג) נבחרים בתי החולים *באותו יישוב* בלבד, והמרחק מוחזר
    None — עדיף להציג את מה שידוע בוודאות מאשר לא להציג כלום.
    """
    hospitals = [record for record in load_locations(path).get("hospitals", [])
                 if record.get("has_er")]
    if position is None:
        return [(None, record) for record in hospitals
                if city_matches(record, locality)][:limit]
    return _with_distance(hospitals, position, HOSPITAL_RADIUS_KM)[:limit]


def nearest_branches(chain: str, position: tuple[float, float] | None,
                     when: datetime, limit: int = MAX_BRANCHES_PER_CHAIN,
                     path: str | None = None, locality: str | None = None,
                     ) -> list[tuple[float | None, dict, bool | None]]:
    """
    המוקדים הקרובים של רשת אחת, ממוינים לפי מרחק. מוחזרים רק מוקדים
    שפתוחים כעת (True) או ששעותיהם אינן ידועות (None) — מוקד שידוע
    שסגור אינו יעד. סדר: הפתוחים תחילה, ואחריהם הלא-ידועים.
    בלי קואורדינטות — התאמה לפי שם היישוב בלבד (ראה nearest_hospitals).
    """
    branches = [record for record in load_locations(path).get("urgent_care_branches", [])
                if record.get("chain") == chain]
    if position is None:
        scored: list[tuple[float | None, dict]] = [
            (None, record) for record in branches
            if city_matches(record, locality)
        ]
    else:
        scored = list(_with_distance(branches, position, URGENT_CARE_RADIUS_KM))
    candidates = []
    for away, record in scored:
        state = is_open_at(record.get("hours"), when)
        if state is False:
            continue
        candidates.append((away, record, state))
    candidates.sort(key=lambda item: (item[2] is None, item[0] or 0.0))
    return candidates[:limit]


# ── ניסוח ────────────────────────────────────────────────────────────────
def _distance_he(away: float | None) -> str:
    """
    ניסוח המרחק. הקואורדינטות הן ברזולוציית יישוב, ולכן "כ-0 ק\"מ" הוא
    מדויק-לכאורה ומטעה: באותו יישוב נאמר זאת במילים. away=None פירושו
    שאין קואורדינטות (ההתאמה נעשתה לפי שם היישוב) — ואז לא נאמר מרחק
    בכלל, במקום להמציא אחד.
    """
    if away is None:
        return "ביישוב שלך"
    return "ביישוב שלך" if away < 1.0 else f"כ-{away:.0f} ק\"מ"


def _hospital_line(away: float | None, record: dict) -> str:
    parts = [f"• {record['name']}"]
    if record.get("city"):
        parts.append(f"({record['city']}, {_distance_he(away)})")
    line = " ".join(parts)
    if record.get("er_phone"):
        line += f" — מיון: {record['er_phone']}"
    return line


def _branch_line(away: float | None, record: dict, state: bool | None) -> str:
    line = f"• {record['name']}"
    if record.get("address"):
        line += f" — {record['address']}"
    elif record.get("city"):
        line += f" — {record['city']}"
    line += f" ({_distance_he(away)})"
    if record.get("phone"):
        suffix = " (מוקד ארצי)" if record.get("phone_is_central") else ""
        line += f", טלפון: {record['phone']}{suffix}"
    if state is None:
        line += " — שעות הפעילות אינן מאומתות, התקשרו לפני הגעה"
    return line


def _health_funds_line(document: dict) -> str:
    template = document.get("referral_template", {})
    funds = document.get("national", {}).get("health_funds", [])
    listed = " · ".join(
        f"{fund['name']} {fund['emergency_phone']}"
        for fund in funds if fund.get("emergency_phone")
    )
    label = template.get("health_fund_line", "מוקד קופת החולים:")
    return f"{label} {listed}" if listed else label


def build_referral_block(
    locality: str | None,
    level: Level = CRITICAL,
    when: datetime | None = None,
    path: str | None = None,
) -> str | None:
    """
    בלוק היעדים בעברית, או None כשאי אפשר לבנות אותו (אין יישוב מוכר /
    אין קובץ) — ואז ה-pipeline נשאר עם הנוסח הארצי הקבוע.

    המבנה קבוע ומגיע מהקובץ (referral_template): קידומת 101 בחירום
    קריטי, שלוש הכותרות תמיד, מוקד קופות החולים והערת הסיום תמיד.
    """
    document = load_locations(path)
    template = document.get("referral_template")
    if not template:
        return None
    position = resolve_position(locality)
    when = when or now_in_israel()

    hospitals = nearest_hospitals(position, path=path, locality=locality)
    by_chain = {
        "bikur_rofe": nearest_branches("ביקור רופא", position, when, path=path,
                                       locality=locality),
        "terem": nearest_branches("טרם", position, when, path=path,
                                  locality=locality),
    }
    # בלי קואורדינטות למשתמש נשארת רק התאמה לפי שם היישוב; אם גם היא לא
    # מצאה דבר, אין מה להציג — וההפניה נשארת הנוסח הארצי הקבוע.
    if position is None and not (hospitals or any(by_chain.values())):
        return None

    lines: list[str] = []
    if level == CRITICAL and template.get("critical_prefix"):
        lines.append(template["critical_prefix"])
        lines.append("")
    elif level == URGENT_CARE:
        lines.append(
            "המצב שתיארת מצריך בדיקה של רופא/ה היום, אך אינו מחייב מיון: "
            "מוקד רפואה דחופה הוא היעד המתאים, והמיון הוא הגיבוי אם אין "
            "מוקד זמין או אם המצב מחמיר."
        )
        lines.append("")

    for section in template.get("sections", []):
        key = section.get("key")
        lines.append(section.get("title", ""))
        if key == "hospitals":
            rendered = [_hospital_line(away, record) for away, record in hospitals]
        else:
            rendered = [_branch_line(away, record, state)
                        for away, record, state in by_chain.get(key, [])]
        if rendered:
            lines.extend(rendered)
            if key != "hospitals" and level == CRITICAL:
                note = template.get("urgent_care_not_suitable_note")
                if note:
                    lines.append(f"⚠ {note}")
        else:
            lines.append(section.get("empty_text", "לא נמצאו יעדים באזור."))
        lines.append("")

    lines.append(_health_funds_line(document))
    footer = template.get("footer_note")
    if footer:
        lines.append(footer)
    return "\n".join(line for line in lines).strip()
