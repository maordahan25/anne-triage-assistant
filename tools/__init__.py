"""
חבילת הכלים (tools) של "אן".

כל כלי הוא פונקציה נקייה וניתנת-לבדיקה עצמאית, שמחזירה dict ולעולם לא קורסת:
בכשל היא מחזירה {"ok": False, "error": ...} במקום לזרוק חריגה.

    weather  - מזג אוויר נוכחי + מקסימום/מינימום יומי לפי קואורדינטות (Open-Meteo, חינמי, ללא מפתח).
    clock    - שעה ותאריך נוכחיים (datetime מקומי, ללא רשת).
    location - גיאוקודינג: שם מקום -> קואורדינטות (Open-Meteo, חינמי, ללא מפתח).
"""
from .clock import get_current_time
from .location import geocode_location
from .weather import get_weather

__all__ = ["get_weather", "get_current_time", "geocode_location"]
