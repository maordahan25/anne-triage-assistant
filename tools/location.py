"""
כלי מיקום (גיאוקודינג): המרת שם מקום לקואורדינטות.

מקור: Open-Meteo Geocoding API
(https://open-meteo.com/en/docs/geocoding-api) — חינמי, ללא מפתח API.
מקבל שם מקום (עברית או אנגלית) ומחזיר latitude/longitude + שם מנורמל ומדינה,
כך שניתן להזין את הקואורדינטות ישירות ל-tools.weather.get_weather.

עקרון מנחה: לעולם לא קורס. כשל רשת / מקום לא נמצא -> {"ok": False, "error": ...}.
"""
from __future__ import annotations

import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
REQUEST_TIMEOUT = 10  # שניות


def geocode_location(name: str, language: str = "he") -> dict:
    """
    מחזיר את הקואורדינטות של המקום הראשון התואם לשם הנתון.

    הפלט (בהצלחה):
        {
          "ok": True,
          "query": "תל אביב",
          "name": "Tel Aviv-Yafo",      # שם מנורמל מהשירות
          "country": "Israel",
          "latitude": 32.08,
          "longitude": 34.78,
        }
    בכשל (מקום ריק / לא נמצא / רשת): {"ok": False, "error": ...}.
    """
    if not name or not name.strip():
        return {"ok": False, "error": "שם מקום ריק.", "query": name}

    params = {"name": name.strip(), "count": 1, "language": language, "format": "json"}
    try:
        resp = requests.get(GEOCODING_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "פג זמן ההמתנה לשירות הגיאוקודינג (timeout).",
                "query": name}
    except requests.exceptions.RequestException as exc:
        return {"ok": False, "error": f"כשל בפנייה לשירות הגיאוקודינג: {exc}",
                "query": name}
    except ValueError as exc:  # JSON לא תקין
        return {"ok": False, "error": f"תשובה לא תקינה משירות הגיאוקודינג: {exc}",
                "query": name}

    results = data.get("results")
    if not results:
        return {"ok": False, "error": f"לא נמצא מקום בשם '{name}'.", "query": name}

    top = results[0]
    return {
        "ok": True,
        "query": name,
        "name": top.get("name"),
        "country": top.get("country"),
        "latitude": top.get("latitude"),
        "longitude": top.get("longitude"),
    }


if __name__ == "__main__":
    # הרצה ישירה: בדיקה ידנית.
    print(geocode_location("תל אביב"))
