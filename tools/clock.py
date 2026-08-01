"""
כלי שעון: שעה ותאריך נוכחיים.

ללא רשת וללא מפתח API — מבוסס datetime בלבד. תומך באזור זמן (IANA, למשל
"Asia/Jerusalem") דרך zoneinfo שבספרייה הסטנדרטית (Python 3.9+).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Jerusalem"

# שמות ימים בעברית (Monday=0 ... Sunday=6, לפי datetime.weekday()).
_WEEKDAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


def get_current_time(timezone: str = DEFAULT_TIMEZONE) -> dict:
    """
    מחזיר את השעה והתאריך הנוכחיים באזור הזמן הנתון.

    הפלט (בהצלחה):
        {
          "ok": True,
          "timezone": "Asia/Jerusalem",
          "date": "2026-06-27",         # ISO
          "time": "21:30:05",           # HH:MM:SS מקומי
          "weekday": "שבת",             # שם היום בעברית
          "iso": "2026-06-27T21:30:05+03:00",
        }
    בכשל (אזור זמן לא מוכר): {"ok": False, "error": ...} ולעולם לא זורק.
    """
    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        return {
            "ok": False,
            "error": f"אזור זמן לא תקין '{timezone}': {exc}",
            "timezone": timezone,
        }

    now = datetime.now(tz)
    return {
        "ok": True,
        "timezone": timezone,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": _WEEKDAYS_HE[now.weekday()],
        "iso": now.isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    # הרצה ישירה: בדיקה ידנית מהירה.
    print(get_current_time())
