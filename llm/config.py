"""
הגדרת ה-LLM לכל תפקיד בצוות הסוכנים.

מטרות:
  * החלפה קלה בין ספקים (OpenAI / Anthropic) דרך LLM_PROVIDER ב-.env,
    בלי לגעת בקוד הסוכנים.
  * מיפוי תפקיד -> (דרגת מודל, טמפרטורה), לפי הטבלה:

        תפקיד               דרגת מודל   טמפרטורה
        ─────────────────   ─────────   ────────
        אן / תשאול          בינוני      0.35   (טווח 0.3–0.4)
        בטיחות (Dr. Dexter) חזק         0.1    (טווח 0.0–0.2)
        מומחים (רופאים)     חסכוני      0.25   (טווח 0.2–0.3)
        מנהל / ניתוב        חסכוני      0.1    (טווח 0.0–0.2)

הערה: get_llm() בונה אובייקט crewai.LLM — ללא שום קריאת רשת/LLM בתשלום.
ב-crewai 1.6.1 מודלי OpenAI רצים על ה-SDK הרשמי (native provider, לא
litellm), ומפתח ה-API חייב להיות מוגדר בסביבה כבר בעת בניית ה-LLM/הסוכן
(אחרת ImportError בבנייה); הקריאה בתשלום מתבצעת רק כשהסוכן רץ בפועל.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

# טעינת .env פעם אחת בעת import (אם קיים). לא דורס משתני סביבה קיימים.
load_dotenv()

# --- דרגות מודל לכל ספק ---------------------------------------------------
# שלוש דרגות: strong (חזק) / medium (בינוני) / economical (חסכוני).
# ניתן לעקוף כל ערך דרך משתני סביבה (ראה .env.example).
_OPENAI_TIERS = {
    "strong": os.getenv("OPENAI_MODEL_STRONG", "gpt-4o"),
    "medium": os.getenv("OPENAI_MODEL_MEDIUM", "gpt-4o-mini"),
    "economical": os.getenv("OPENAI_MODEL_ECONOMICAL", "gpt-4o-mini"),
}

# פורמט litellm לספק Anthropic דורש קידומת "anthropic/".
_ANTHROPIC_TIERS = {
    "strong": os.getenv("ANTHROPIC_MODEL_STRONG", "anthropic/claude-opus-4-8"),
    "medium": os.getenv("ANTHROPIC_MODEL_MEDIUM", "anthropic/claude-sonnet-4-6"),
    "economical": os.getenv("ANTHROPIC_MODEL_ECONOMICAL", "anthropic/claude-haiku-4-5"),
}

_PROVIDER_TIERS = {
    "openai": _OPENAI_TIERS,
    "anthropic": _ANTHROPIC_TIERS,
}

# --- מיפוי תפקיד -> (דרגה, טמפרטורה) -------------------------------------
ROLE_CONFIG = {
    "anne":       {"tier": "medium",     "temperature": 0.35},  # אן / תשאול
    "safety":     {"tier": "strong",     "temperature": 0.1},   # Dr. Dexter / בטיחות
    "specialist": {"tier": "economical", "temperature": 0.25},  # רופאים מומחים
    "manager":    {"tier": "economical", "temperature": 0.1},   # manager / ניתוב
}


def get_provider() -> str:
    """שם ספק ה-LLM הפעיל (openai / anthropic), מנורמל ל-lowercase."""
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    if provider not in _PROVIDER_TIERS:
        raise ValueError(
            f"LLM_PROVIDER='{provider}' אינו נתמך. בחר אחד מ: "
            f"{', '.join(_PROVIDER_TIERS)}."
        )
    return provider


def get_role_config(role: str) -> dict:
    """
    מחזיר את ההגדרה המלאה לתפקיד נתון, ללא בניית אובייקט LLM:
        {"provider": ..., "model": ..., "tier": ..., "temperature": ...}
    שימושי לבדיקה/דיבוג בלי לדרוש מפתח API.
    """
    if role not in ROLE_CONFIG:
        raise ValueError(
            f"תפקיד '{role}' אינו מוכר. בחר אחד מ: {', '.join(ROLE_CONFIG)}."
        )
    provider = get_provider()
    cfg = ROLE_CONFIG[role]
    return {
        "provider": provider,
        "tier": cfg["tier"],
        "model": _PROVIDER_TIERS[provider][cfg["tier"]],
        "temperature": cfg["temperature"],
    }


def get_llm(role: str, stream: bool = False):
    """
    בונה אובייקט crewai.LLM עבור התפקיד הנתון, לפי הספק והדרגה/טמפרטורה.

    stream=True מבקש תשובה זורמת (token by token). התשובה המוחזרת מ-kickoff
    זהה לחלוטין (crewai מצרף את המקטעים), אבל בדרך נפלט LLMStreamChunkEvent
    לכל מקטע — וזה מה שמאפשר להזרים את ניסוח אן לדפדפן (crew/streaming.py).
    משמש כיום רק למופע הניסוח של אן; שאר התפקידים אינם זורמים.

    אינו מבצע קריאת רשת/LLM — רק הגדרת לקוח. מפתח ה-API נקרא מהסביבה בעת
    שהסוכן ירוץ בפועל (OPENAI_API_KEY / ANTHROPIC_API_KEY).
    """
    from crewai import LLM  # import עצל — נמנע מתלות ב-crewai בזמן בדיקת הכלים

    cfg = get_role_config(role)
    return LLM(model=cfg["model"], temperature=cfg["temperature"], stream=stream)


if __name__ == "__main__":
    # הרצה ישירה: הדפסת מיפוי התפקידים לספק הפעיל (ללא בניית LLM, ללא API).
    print(f"ספק פעיל: {get_provider()}\n")
    for role in ROLE_CONFIG:
        print(f"{role:12s} -> {get_role_config(role)}")
