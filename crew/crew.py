"""
הרכבת ה-crew ההיררכי — צוות הייעוץ הרפואי שמאחורי הקלעים.

האורקסטרציה (שקף 9 במצגת): Process היררכי של CrewAI. ה-manager אינו דמות
ואינו רופא נוסף — הוא מנגנון ניתוב (manager_llm, דרגה חסכונית, טמפרטורה
נמוכה) שבוחר לאיזה רופא מומחה להאציל את המקרה.

עובדה חשובה ב-crewai 1.6.1: בתהליך היררכי ה-manager הוא שמבצע כל משימה,
ומערב את המומחים דרך כלי ההאצלה ('Delegate work to coworker' /
'Ask question to coworker'). לכן משימת הייעוץ מוגדרת ללא agent — כך
ה-manager רשאי להאציל לכל אחד מארבעת הרופאים. אן אינה חברה ב-crew הזה:
היא ה-lead והקול, ורצה מחוץ לו (ראה pipeline.py).
"""
from __future__ import annotations

from crewai import Crew, Process, Task

from llm import get_llm

from .agents import SPECIALISTS, build_all_specialists
from .schemas import SpecialistAdvice

# פירוט הרופאים ל-description של משימת הייעוץ (שמות מדויקים להאצלה).
_ROSTER_HE = "\n".join(
    f"* {spec['name']} — {spec['expertise_he']} (topic: {topic})"
    for topic, spec in SPECIALISTS.items()
)

# תבנית משימת הייעוץ. משתני התבנית מסופקים ב-kickoff(inputs=...):
#   current_time    - הקשר-זמן מוזרק (שעה/תאריך/יום) — מ-tools.clock, לא מכלי
#   weather_context - הקשר מזג אוויר מוזרק (כשאן חילצה יישוב), או "לא סופק"
#   image_context   - הקשר מתמונה שהמשתמש העלה (מדידות + תיאור חזותי),
#                     או "לא צורפה תמונה" — ראה vision/ ו-pipeline
#   case_summary    - סיכום המקרה שאן ניסחה
#   topic_hint      - התחום המשוער שאן זיהתה (רמז בלבד)
#   user_message    - ההודעה האחרונה של המשתמש, כלשונה
#   chat_history    - תמליל השיחה עד כה
#   shown_illustrations - האיורים שהוצגו כבר בשיחה (מניעת חזרה; האכיפה
#                     עצמה בקוד — pipeline._pick_illustration)
_CONSULT_DESCRIPTION = (
    "אן, האחות המתשאלת, מעבירה אליך מקרה לייעוץ מקצועי.\n"
    "\n"
    "הקשר זמן נוכחי (מהמערכת): {current_time}\n"
    "\n"
    "הקשר מזג אוויר (מהמערכת): {weather_context}\n"
    "\n"
    "הקשר מתמונה שהמשתמש העלה (מהמערכת): {image_context}\n"
    "\n"
    "סיכום המקרה מאן:\n{case_summary}\n"
    "\n"
    "התחום המשוער לפי אן (רמז בלבד — מותר לך לקבוע אחרת): {topic_hint}\n"
    "\n"
    "ההודעה האחרונה של המשתמש, כלשונה:\n{user_message}\n"
    "\n"
    "תמליל השיחה עד כה (רקע בלבד — לא מקור לציטוט):\n{chat_history}\n"
    "\n"
    "איורים שהמשתמש כבר ראה בשיחה הזו: {shown_illustrations}\n"
    "\n"
    "המשימה: קבע את התחום המתאים והאצל את המקרה לרופא המומחה הנכון מהצוות "
    "(העבר לו את סיכום המקרה במלואו). הרופא חייב לחפש במאגר הידע שלו לפני "
    "שהוא ממליץ, ושדה sources חייב להכיל אך ורק את מקורות הקטעים שנשלפו "
    "בחיפוש של התור הנוכחי — לא מקורות שהוזכרו בתמליל השיחה. אם המקרה אינו "
    "שייך לאף תחום — קבע topic=other, השאר את sources ריק לחלוטין (אין "
    "שליפה רלוונטית — אסור להמציא שמות מקורות), והמלץ בעדינות "
    "על פנייה לרופא/ת המשפחה, בלי להמציא טיפול.\n"
    "הצוות:\n"
    f"{_ROSTER_HE}"
)

_CONSULT_EXPECTED_OUTPUT = (
    "אובייקט JSON יחיד (ללא טקסט נוסף) לפי הסכמה שסופקה: topic, advice_he "
    "(המלצת הטיפול בעברית, נאמנה למקורות שנשלפו), follow_up_questions_he "
    "(שאלות המשך אם חסר מידע, אחרת רשימה ריקה), illustration_id (מהרשימה "
    "הסגורה של הרופא או null), sources (שמות המקורות מהקטעים שנשלפו "
    "בחיפוש הנוכחי בלבד — לא מקורות מהתמליל או מתשובות קודמות; "
    "ב-topic=other — רשימה ריקה)."
)


def build_consult_task() -> Task:
    """משימת הייעוץ: ניתוב ע"י ה-manager -> המלצת מומחה כפלט מובנה."""
    return Task(
        description=_CONSULT_DESCRIPTION,
        expected_output=_CONSULT_EXPECTED_OUTPUT,
        # agent=None בכוונה: בהיררכי זה מותיר ל-manager האצלה לכל הרופאים.
        output_pydantic=SpecialistAdvice,
    )


def build_care_crew(verbose: bool = False) -> Crew:
    """
    צוות הייעוץ: ארבעת הרופאים תחת manager מנתב (Process היררכי).

    ה-crew נבנה פעם אחת לשיחה ומופעל מחדש בכל תור עם inputs חדשים —
    crewai משחזר את תבניות המשימה המקוריות בכל kickoff.
    """
    return Crew(
        agents=build_all_specialists(verbose=verbose),
        tasks=[build_consult_task()],
        process=Process.hierarchical,
        manager_llm=get_llm("manager"),
        memory=False,  # הזיכרון מנוהל במפורש ב-pipeline (תמליל השיחה)
        verbose=verbose,
    )
