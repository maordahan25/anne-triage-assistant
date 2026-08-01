"""
כלי מזג אוויר: מצב מזג האוויר הנוכחי + נתוני היום לפי קואורדינטות.

מקור: Open-Meteo (https://open-meteo.com) — חינמי, ללא צורך במפתח API.
מקבל latitude/longitude ומחזיר טמפרטורה ולחות נוכחיות, תיאור מצב מזג אוויר,
וכן את המקסימום/מינימום היומי (חשוב לתרחיש "כאב ראש אחרי יום חם").

עקרון מנחה: הפונקציה לעולם לא קורסת. כשל רשת / timeout / תשובה לא צפויה
מתורגם לתשובה בטוחה {"ok": False, "error": ...}.
"""
from __future__ import annotations

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT = 10  # שניות — תקרת המתנה לבקשת הרשת

# מיפוי קודי מזג האוויר (WMO weather code) לתיאור בעברית.
# https://open-meteo.com/en/docs  ->  Weather variable documentation
_WMO_CODES_HE = {
    0: "בהיר",
    1: "בהיר ברובו",
    2: "מעונן חלקית",
    3: "מעונן",
    45: "ערפל",
    48: "ערפל מתמשך",
    51: "טפטוף קל",
    53: "טפטוף בינוני",
    55: "טפטוף חזק",
    56: "טפטוף קפוא קל",
    57: "טפטוף קפוא חזק",
    61: "גשם קל",
    63: "גשם בינוני",
    65: "גשם חזק",
    66: "גשם קפוא קל",
    67: "גשם קפוא חזק",
    71: "שלג קל",
    73: "שלג בינוני",
    75: "שלג חזק",
    77: "גרגרי שלג",
    80: "ממטרים קלים",
    81: "ממטרים בינוניים",
    82: "ממטרים עזים",
    85: "ממטרי שלג קלים",
    86: "ממטרי שלג עזים",
    95: "סופת רעמים",
    96: "סופת רעמים עם ברד קל",
    99: "סופת רעמים עם ברד כבד",
}


def _describe_weather_code(code) -> str:
    """תרגום קוד WMO לתיאור עברי; קוד לא מוכר -> 'לא ידוע'."""
    try:
        return _WMO_CODES_HE.get(int(code), "לא ידוע")
    except (TypeError, ValueError):
        return "לא ידוע"


def _first(values):
    """מחזיר את האיבר הראשון ברשימה (נתון היום הנוכחי) או None אם אין."""
    if isinstance(values, list) and values:
        return values[0]
    return None


def get_weather(latitude: float, longitude: float) -> dict:
    """
    מחזיר את מצב מזג האוויר הנוכחי + נתוני היום בנקודה הגאוגרפית הנתונה.

    הפלט (בהצלחה):
        {
          "ok": True,
          "latitude": 32.08,
          "longitude": 34.78,
          "temperature_c": 28.4,        # מעלות צלזיוס — הטמפרטורה הנוכחית
          "humidity_pct": 55,           # לחות יחסית באחוזים — נוכחי
          "weather_code": 0,
          "description": "בהיר",
          "temp_max_today_c": 33.1,     # מקסימום הטמפרטורה היומי
          "temp_min_today_c": 21.7,     # מינימום הטמפרטורה היומי
        }
    בכשל (רשת / timeout / תשובה חסרה): {"ok": False, "error": ...}.
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min",
        # timezone=auto -> "היום" מחושב לפי היום המקומי של המיקום, לא לפי GMT.
        "timezone": "auto",
        # מבטיח שהאיבר הראשון בנתוני daily הוא היום הנוכחי בלבד.
        "forecast_days": 1,
    }
    try:
        resp = requests.get(FORECAST_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "פג זמן ההמתנה לשירות מזג האוויר (timeout)."}
    except requests.exceptions.RequestException as exc:
        return {"ok": False, "error": f"כשל בפנייה לשירות מזג האוויר: {exc}"}
    except ValueError as exc:  # JSON לא תקין
        return {"ok": False, "error": f"תשובה לא תקינה משירות מזג האוויר: {exc}"}

    current = data.get("current")
    if not isinstance(current, dict):
        return {"ok": False, "error": "תשובת מזג האוויר אינה כוללת נתונים נוכחיים."}

    # נתוני היום (daily). חסרים? לא מפילים — מחזירים None בשדות החדשים.
    daily = data.get("daily")
    if not isinstance(daily, dict):
        daily = {}

    code = current.get("weather_code")
    return {
        "ok": True,
        "latitude": latitude,
        "longitude": longitude,
        "temperature_c": current.get("temperature_2m"),
        "humidity_pct": current.get("relative_humidity_2m"),
        "weather_code": code,
        "description": _describe_weather_code(code),
        "temp_max_today_c": _first(daily.get("temperature_2m_max")),
        "temp_min_today_c": _first(daily.get("temperature_2m_min")),
    }


if __name__ == "__main__":
    # הרצה ישירה: בדיקה ידנית (תל אביב).
    print(get_weather(32.0853, 34.7818))
