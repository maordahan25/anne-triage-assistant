"""
נקודת הכניסה לשיחה עם אן — צ'אט אינטראקטיבי במסוף.

הרצה (דורש OPENAI_API_KEY ב-.env; כל תור מבצע קריאות LLM בתשלום):

    python -m crew.main

יציאה: הקלדת 'יציאה' / 'ביי' / 'exit' / 'quit' (או Ctrl+C).

איורים: כשהתשובה כוללת איור מודרך, מודפס בלוק עם שם האיור ושלביו,
וקובץ ה-PNG נפתח בתוכנת ברירת המחדל של מערכת ההפעלה. אפשר לכבות את
הפתיחה האוטומטית (למשל בסביבת SSH) עם ANNE_NO_IMAGE_OPEN=1.

עם ANNE_VERBOSE=1 מודפסים גם תזמוני השלבים, מספר קריאות ה-LLM ומוני
הפעלות הכלים של כל תור.
"""
from __future__ import annotations

import os
import subprocess
import sys

from rag.config import PROJECT_ROOT

from .pipeline import WELCOME_HE, ChatSession, ensure_api_key

_EXIT_WORDS = {"יציאה", "ביי", "exit", "quit", "q"}

ILLUSTRATIONS_DIR = PROJECT_ROOT / "illustrations"


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def _open_image(path) -> None:
    """פתיחת קובץ האיור בתוכנת ברירת המחדל; כשל בפתיחה לא מפיל את השיחה."""
    if _env_flag("ANNE_NO_IMAGE_OPEN"):
        return
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False, timeout=10)
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", str(path)], check=False, timeout=10)
        elif sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        pass  # למשל סביבת SSH בלי תצוגה — הבלוק הטקסטואלי כבר הודפס


def _show_illustration(illustration: dict) -> None:
    """הדפסת בלוק האיור (שם + שלבים ממוספרים) ופתיחת ה-PNG למשתמש."""
    width = 46
    print("  ┌" + "─" * width)
    print(f"  │ איור מודרך: {illustration['name']}")
    print("  │" + "┄" * width)
    for i, step in enumerate(illustration.get("steps", []), start=1):
        print(f"  │ {i}. {step}")
    print("  └" + "─" * width)

    path = ILLUSTRATIONS_DIR / illustration.get("file", "")
    if path.is_file():
        _open_image(path)
    else:
        print(f"  [קובץ האיור לא נמצא: {path}]")


def main() -> None:
    try:
        ensure_api_key()
    except RuntimeError as exc:
        print(f"\n{exc}\n")
        return

    verbose = _env_flag("ANNE_VERBOSE")

    print("\n" + "=" * 60)
    print("אן — עוזרת טרום-מיון חכמה (עזרה ראשונית בלבד, לא ייעוץ רפואי)")
    print("=" * 60)
    print("בונה את הצוות... (הרצה ראשונה עשויה לקחת כמה שניות)\n")

    session = ChatSession()
    print(f"אן: {WELCOME_HE}\n")

    while True:
        try:
            user_message = input("אתם: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nאן: שיהיה לכם המשך יום רגוע. אני כאן כשצריך אותי.")
            break

        if not user_message:
            continue
        if user_message.lower() in _EXIT_WORDS:
            print("\nאן: שיהיה לכם המשך יום רגוע. אני כאן כשצריך אותי.")
            break

        result = session.run_turn(user_message)
        print(f"\nאן: {result.reply_he}\n")

        if result.illustration:
            _show_illustration(result.illustration)
        if verbose and result.timings:
            stages = " | ".join(
                f"{name}: {seconds:.1f}s" for name, seconds in result.timings.items()
            )
            print(f"  [תזמונים: {stages} | קריאות LLM: {result.llm_calls} | "
                  f"נסיגות המרה: {result.structured_retries}]")
            tools_used = ", ".join(
                f"{name}×{count}" for name, count in result.tool_usage.items()
            ) or "ללא"
            print(f"  [כלים שהופעלו בתור: {tools_used}]")
        if result.emergency:
            print("[זוהה מצב חירום — אן עצרה את השיחה והפנתה לעזרה מקצועית.]")
            break


if __name__ == "__main__":
    main()
