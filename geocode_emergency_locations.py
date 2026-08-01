"""
השלמת קואורדינטות ל-data/emergency_locations.json — סקריפט חד-פעמי.

    python geocode_emergency_locations.py            # השלמה בפועל
    python geocode_emergency_locations.py --dry-run  # הדפסה בלבד, בלי כתיבה
    python geocode_emergency_locations.py --force    # גם רשומות שכבר יש להן

**זה כלי build-time ולא חלק מהריצה של אן.** בזמן שיחה אין שום קריאת רשת
להפניית החירום: ההפניה נבנית מהקובץ המקומי בלבד (crew/emergency_referral.py).
הסקריפט הזה הוא הדרך היחידה שבה קואורדינטות נכנסות לקובץ, והוא משתמש
ב-tools/location.py — אותו כלי גיאוקודינג שכבר קיים בפרויקט (Open-Meteo,
חינמי, בלי מפתח) — כדי שלא ייווצר מקור נתונים שני.

עקרונות:
  * **לעולם לא לנחש.** קואורדינטה נכתבת רק כשהשירות החזיר תוצאה. יישוב
    שלא נמצא נשאר null, נספר בדוח הסיום, והרשומה נשארת שמישה (ההפניה
    עדיין תדע להציג אותה לפי התאמת שם היישוב — ראה crew/emergency_referral).
  * **רזולוציית יישוב, וזה נאמר במפורש.** שירות הגיאוקודינג של Open-Meteo
    הוא מאגר *יישובים* ולא מאגר כתובות: "המרכז הרפואי סוראסקי" או "אלי
    הורוביץ 12" אינם קיימים בו. לכן כל רשומה מקבלת את קואורדינטות
    היישוב שלה, ו-_meta.geocoding מתעד את זה. לדירוג "מה קרוב אליי"
    ברמת עיר זה מספיק; להנחיית נהיגה זה לא, ולכן הכתובת המלאה מוצגת
    כטקסט מהאתר הרשמי.
  * **שאילתה אחת ליישוב.** 64 רשומות יושבות על ~40 יישובים; התוצאה
    נשמרת ב-cache מקומי כדי לא להעמיס על השירות החינמי.
  * **תיעוד מקור.** לכל רשומה נשמר coords_query — המחרוזת שבאמת החזירה
    את התוצאה, כך שאפשר לשחזר ולבדוק כל קואורדינטה.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tools.location import geocode_location

PROJECT_ROOT = Path(__file__).resolve().parent
LOCATIONS_FILE = PROJECT_ROOT / "data" / "emergency_locations.json"

# יישובים שהכתיב העברי שלהם אינו נמצא במאגר של Open-Meteo. הטבלה מכילה
# *שאילתות חלופיות* בלבד — הקואורדינטות עצמן תמיד מגיעות מהשירות, אף פעם
# לא מכאן. סדר הניסיון: השם כפי שהוא, ואז החלופות.
CITY_QUERY_ALIASES = {
    "ראש העין": ["Rosh HaAyin"],
    "קרית ביאליק": ["קריית ביאליק", "Kiryat Bialik"],
    "קריית ביאליק": ["Kiryat Bialik"],
    "קרית שמונה": ["קריית שמונה", "Kiryat Shmona"],
    "קריית אונו": ["Kiryat Ono"],
    "קריית מלאכי": ["Kiryat Malakhi"],
    "קריית גת": ["Kiryat Gat"],
    "מודיעין": ["Modi'in-Maccabim-Re'ut", "Modiin"],
    "מודיעין עילית": ["Modi'in Illit"],
    "ביתר עילית": ["Beitar Illit"],
    "מעלה אדומים": ["Ma'ale Adumim"],
    "בית שמש": ["Beit Shemesh"],
    "מבשרת ציון": ["Mevaseret Zion"],
    "באר יעקב": ["Be'er Ya'akov"],
    "פתח תקווה": ["Petah Tikva"],
    "ראשון לציון": ["Rishon LeZiyyon"],
    "תל אביב": ["תל אביב-יפו", "Tel Aviv"],
    "רמת גן": ["Ramat Gan"],
    "באר שבע": ["Be'er Sheva"],
    "נהריה": ["Nahariya"],
    "כרמיאל": ["Karmiel"],
    "טבריה": ["Tiberias"],
    "עפולה": ["Afula"],
    "חדרה": ["Hadera"],
    "אשקלון": ["Ashkelon"],
    "אשדוד": ["Ashdod"],
    "רחובות": ["Rehovot"],
    "שדרות": ["Sderot"],
    "יבנה": ["Yavne"],
    "לוד": ["Lod"],
    "אריאל": ["Ariel"],
    "חולון": ["Holon"],
    "אילת": ["Eilat"],
    "מצפה רמון": ["Mitzpe Ramon"],
    "קצרין": ["Katzrin", "Qatzrin", "Qasrin"],
    "בני ברק": ["Bnei Brak"],
    "כפר סבא": ["Kfar Saba"],
    "נתניה": ["Netanya"],
    "ירושלים": ["Jerusalem"],
    "חיפה": ["Haifa"],
}


def _is_hebrew(text: str) -> bool:
    return any("א" <= char <= "ת" for char in text)


def geocode_city(city: str, cache: dict[str, dict]) -> dict:
    """
    קואורדינטות ליישוב אחד, עם ניסיון חלופות. מחזיר:
        {"ok": True, "lat": .., "lon": .., "query": ".."} או {"ok": False}
    """
    if city in cache:
        return cache[city]
    for query in [city, *CITY_QUERY_ALIASES.get(city, [])]:
        result = geocode_location(
            query, language="he" if _is_hebrew(query) else "en",
        )
        time.sleep(0.3)   # נימוס כלפי שירות חינמי
        if result.get("ok"):
            resolved = {"ok": True, "lat": result["latitude"],
                        "lon": result["longitude"], "query": query,
                        "resolved_name": result.get("name")}
            cache[city] = resolved
            return resolved
    cache[city] = {"ok": False}
    return cache[city]


def run(dry_run: bool = False, force: bool = False) -> int:
    document = json.loads(LOCATIONS_FILE.read_text(encoding="utf-8"))
    records = [*document.get("hospitals", []),
               *document.get("urgent_care_branches", [])]

    cache: dict[str, dict] = {}
    filled, skipped, failed = 0, 0, []
    for record in records:
        city = (record.get("city") or "").strip()
        if not city:
            failed.append((record.get("id", "?"), "אין עיר ברשומה"))
            continue
        if record.get("lat") is not None and not force:
            skipped += 1
            continue
        resolved = geocode_city(city, cache)
        if not resolved.get("ok"):
            failed.append((record.get("id", "?"), city))
            continue
        record["lat"] = round(resolved["lat"], 5)
        record["lon"] = round(resolved["lon"], 5)
        record["coords_query"] = resolved["query"]
        filled += 1
        print(f"✓ {record.get('id', '?'):34} {city:14} -> "
              f"{record['lat']}, {record['lon']}  (שאילתה: {resolved['query']})")

    document.setdefault("_meta", {})["geocoding"] = {
        "service": "Open-Meteo Geocoding API (tools/location.py)",
        "precision": "יישוב",
        "note": ("הקואורדינטות הן של היישוב, לא של הכתובת המדויקת — שירות "
                 "הגיאוקודינג הוא מאגר יישובים. הכתובת המלאה של כל רשומה "
                 "מוצגת כטקסט מהמקור הרשמי."),
        "script": "geocode_emergency_locations.py",
        "records_with_coords": sum(
            1 for record in records if record.get("lat") is not None),
        "records_total": len(records),
    }

    print(f"\nהושלמו {filled} רשומות · דולגו {skipped} (כבר היו) · "
          f"נכשלו {len(failed)}")
    for record_id, city in failed:
        print(f"  ✗ {record_id:34} {city} — לא נמצא במאגר הגיאוקודינג, "
              "נשאר null")
    if dry_run:
        print("\n(--dry-run: הקובץ לא נכתב)")
        return 0
    LOCATIONS_FILE.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"\nנכתב: {LOCATIONS_FILE}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="השלמת קואורדינטות ליעדי החירום (חד-פעמי, build-time).",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="הדפסה בלבד, בלי לכתוב לקובץ")
    parser.add_argument("--force", action="store_true",
                        help="גיאוקודינג מחדש גם לרשומות שכבר יש להן קואורדינטות")
    args = parser.parse_args()
    return run(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
