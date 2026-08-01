"""
מונה קריאות ה-LLM של התור — נספר במקור, דרך ה-event bus של crewai 1.6.1.

הרקע (באג מאומת): הספירה הקודמת קראה usage_metrics מהפלט של כל kickoff,
אבל ב-crewai 1.6.1 המותקן זה שבור פעמיים:
  * LiteAgentOutput.usage_metrics הוא dict (model_dump), ולכן
    getattr(metrics, "successful_requests", 0) החזיר תמיד 0 בכל נתיבי
    ה-LiteAgent (אן, דקסטר, רופא ישיר) — רק ה-crew ההיררכי דיווח מספר.
  * גם לו קראנו את ה-dict נכון — המונה הפנימי של ה-LLM הנייטיבי
    (BaseLLM._token_usage) מצטבר לאורך חיי האובייקט, כלומר פר-סוכן
    פר-שיחה, לא פר-תור.

לכן הספירה כאן נעשית במקור: כל LLMCallCompletedEvent שנפלט מה-event bus
הגלובלי של crewai — הן קריאות LiteAgent (אן, דקסטר, רופא ישיר), הן
הקריאות הפנימיות של ה-crew ההיררכי (manager והאצלות), הן קריאות ההמרה
של Converter (response_format) — כל קריאת LLM אמיתית, בכל הנתיבים.
האיפוס פר-תור נעשה ב-pipeline.run_turn, ממש כמו מוני הכלים.

הערת דיוק: ה-handlers של ה-bus רצים ב-thread pool, כך שתיאורטית האירוע
האחרון של תור עלול להיספר מעט אחרי קריאת הסיכום. בפועל ה-handler הטריוויאלי
רץ תוך מיקרו-שניות מרגע הפליטה (שקורית לפני שה-kickoff מחזיר), והקריאה
לסיכום מגיעה אחרי שכל ה-kickoffs הסתיימו. זהו מדד observability — לא בטיחות.
"""
from __future__ import annotations

import threading

from crewai.events import LLMCallCompletedEvent, crewai_event_bus

_LOCK = threading.Lock()
_LLM_CALLS = 0


@crewai_event_bus.on(LLMCallCompletedEvent)
def _count_llm_call(source, event) -> None:  # noqa: ARG001 — חתימת ה-bus
    """רישום קריאת LLM אחת שהושלמה (thread-safe; נרשם פעם אחת ב-import)."""
    global _LLM_CALLS
    with _LOCK:
        _LLM_CALLS += 1


def reset_llm_calls() -> None:
    """איפוס המונה — בתחילת כל תור-שיחה (pipeline.run_turn)."""
    global _LLM_CALLS
    with _LOCK:
        _LLM_CALLS = 0


def get_llm_calls() -> int:
    """מספר קריאות ה-LLM שהושלמו מאז האיפוס האחרון."""
    with _LOCK:
        return _LLM_CALLS
