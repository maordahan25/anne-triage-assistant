"""
חבילת הסוכנים של "אן" (שלב ב'): צוות CrewAI מעל ה-RAG והכלים.

מבנה החבילה:
    schemas.py       - חוזי הפלט המובנה (Pydantic) של הסוכנים
    illustrations.py - הרשימה הסגורה של האיורים + אימות illustration_id
    tools.py         - עטיפות CrewAI לכלים (RAG נעול-תחום, שעה, מיקום, מזג אוויר)
    agents.py        - הגדרות הסוכנים: אן, 4 רופאים מומחים, Dr. Dexter
    crew.py          - הרכבת ה-crew ההיררכי (manager מנתב + הרופאים)
    pipeline.py      - זרימת תור-שיחה מלאה (בטיחות -> אן -> ייעוץ -> ניסוח)
    main.py          - נקודת כניסה: צ'אט אינטראקטיבי במסוף

פרטיות by design (שקף 18): טלמטריית crewai כבויה כברירת מחדל — אפשר
לעקוף דרך משתני סביבה (.env נטען קודם ואינו נדרס).
"""
import os

from dotenv import load_dotenv

# טעינת .env לפני קביעת ברירות המחדל, כדי שבחירה מפורשת של המשתמש תגבר.
load_dotenv()

# כיבוי טלמטריה/מעקב של crewai כברירת מחדל (חייב לקרות לפני import crewai —
# ה-Telemetry singleton נוצר בזמן ה-import).
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")

from .pipeline import ChatSession, TurnResult, ensure_api_key  # noqa: E402

__all__ = ["ChatSession", "TurnResult", "ensure_api_key"]
