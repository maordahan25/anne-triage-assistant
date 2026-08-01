"""
הזרמת ניסוח התשובה של אן (streaming) — הצינור מ-crewai אל שכבת התצוגה.

למה בכלל: תור-ייעוץ שלם אורך ~10-15 שניות, מהן שלב הניסוח הוא הרביע
האחרון. בלי הזרמה המשתמש רואה "אן מקלידה…" לאורך כל התור ואז קיר טקסט;
עם הזרמה המילים מתחילות להופיע ברגע שאן מתחילה לנסח. משך התור לא משתנה —
הזמן ה*מורגש* כן.

איך זה עובד ב-crewai 1.6.1 (אומת בקוד המותקן, לא מהתיעוד):
  * `LLM(stream=True)` -> ספק ה-OpenAI הנייטיבי עובר ל-
    `_handle_streaming_completion`, שפולט `LLMStreamChunkEvent` לכל delta
    ובסוף מחזיר את הטקסט המלא. כלומר `kickoff().raw` נשאר בדיוק כשהיה —
    ההזרמה היא תוספת, לא החלפה.
  * האירוע נפלט עם ה-*LLM* כמקור (`crewai_event_bus.emit(self, ...)`),
    ולכן אפשר לזהות בוודאות מאיזה סוכן הוא בא. אי אפשר לזהות לפי
    from_agent: `Agent.kickoff()` בונה LiteAgent חדש בכל קריאה.

המימוש: handler אחד נרשם ב-import (כמו ב-crew/metrics.py), ומפנה כל מקטע
ל-sink הרשום עבור אובייקט ה-LLM שפלט אותו. אין sink -> המקטע נזרק, וזה
המצב הרגיל (CLI, בדיקות, כל תור שלא ביקש הזרמה).

עקרון עמידות: כשל ב-sink (למשל דפדפן שהתנתק) נבלע ולעולם אינו מפיל תור.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from crewai.events import crewai_event_bus
from crewai.events.types.llm_events import LLMStreamChunkEvent

# id(אובייקט LLM) -> פונקציה שמקבלת מקטע טקסט. ה-id בטוח כמפתח: האובייקט
# מוחזק ע"י הסוכן כל זמן הרישום, ולכן אינו יכול להתחלף באובייקט אחר.
_SINKS: dict[int, Callable[[str], None]] = {}
_LOCK = threading.Lock()


@crewai_event_bus.on(LLMStreamChunkEvent)
def _fan_out_chunk(source, event) -> None:  # noqa: ARG001 — חתימת ה-bus
    """העברת מקטע זורם ל-sink של אותו LLM (אם נרשם כזה)."""
    with _LOCK:
        sink = _SINKS.get(id(source))
    if sink is None:
        return
    chunk = getattr(event, "chunk", "") or ""
    if not chunk:
        return
    try:
        sink(chunk)
    except Exception:
        # צד הצריכה נשבר (דפדפן שהתנתק וכד') — התור ממשיך כרגיל.
        pass


@contextmanager
def stream_to(llm, sink: Callable[[str], None]) -> Iterator[None]:
    """
    הקשר שבו כל מקטע שה-LLM הנתון פולט מועבר ל-sink.

    יציאה מההקשר מבטלת את הרישום תמיד (גם בחריגה), כך שמקטעים של תור
    הבא לא ידלפו ל-sink של תור שהסתיים.
    """
    key = id(llm)
    with _LOCK:
        previous = _SINKS.get(key)
        _SINKS[key] = sink
    try:
        yield
    finally:
        with _LOCK:
            if previous is None:
                _SINKS.pop(key, None)
            else:
                _SINKS[key] = previous


def active_sink_count() -> int:
    """מספר ה-sinks הרשומים כרגע — ל-observability ולבדיקות אופליין."""
    with _LOCK:
        return len(_SINKS)
