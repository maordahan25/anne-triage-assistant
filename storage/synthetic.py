"""
מחולל דאטה סינתטי ללוג השיחות — להזנת דשבורד/מודל חיזוי לפני שיש נתוני אמת.

הרשומות נכתבות דרך אותו מסלול בדיוק כמו תורי שיחה אמיתיים (write_record ->
scrub_record + אילוצי ה-CHECK של הסכמה) — כך המחולל משמש גם בדיקת עומס
קטנה על שכבת הפרטיות. ברירת המחדל כותבת לקובץ נפרד (anne_log_synthetic.db)
כדי לא לערבב נתונים מדומים בלוג האמיתי; אותו seed מייצר בדיוק אותו דאטה
(הריצו עם --reset כדי להימנע מהכפלות בהרצה חוזרת).

ההתפלגויות מחקות בגסות את ההתנהגות שנצפתה בריצות אמיתיות: רוב התורים
במסלול הישיר, topic=other נופל ל-crew ההיררכי (האיטי), חירום נדיר ועוצר
את השיחה, ותורי ברכה/אנמנזה ללא ייעוץ. אין כאן שום טקסט — רק שדות מובנים.

**גם ל-Supabase.** המחולל אינו יודע לאיזה backend הוא כותב, וזה בדיוק
העניין: הוא קורא ל-write_records, ושכבת ה-backend מחליטה. כשהמתג
ANNE_LOG_BACKEND=supabase, ``--db`` שנשאר בברירת המחדל (קובץ ששמו מכיל
synthetic) ממופה אוטומטית לטבלה turns_synthetic; אפשר גם לנקוב בשם
הטבלה במפורש. בסיום מודפס היעד **בפועל** — כך שנפילה חיננית ל-SQLite
לא יכולה להיראות כמו זריעה מוצלחת לענן.

הרצה (חינם, ללא LLM):
    python -m storage.synthetic                       # 200 תורים, seed=7
    python -m storage.synthetic --rows 500 --seed 42
    python -m storage.synthetic --reset               # ניקוי היעד קודם
    python -m storage.synthetic --db anne_log.db      # במפורש אל הלוג האמיתי
    python -m storage.synthetic --db turns_synthetic  # טבלה ב-Supabase
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone

from .turn_log import (
    SCHEMA_VERSION,
    SYNTHETIC_DB_PATH,
    describe_target,
    init_db,
    reset_log,
    write_records,
)

# ברירת המחדל: קובץ נפרד מהלוג האמיתי (או הטבלה הסינתטית, ב-Supabase).
DEFAULT_SYNTH_DB = SYNTHETIC_DB_PATH

_HEX = "0123456789abcdef"

# התפלגות תחומים משוערת (מקרי other נדירים יותר מארבעת תחומי הליבה).
TOPIC_WEIGHTS = (
    ("wounds", 30), ("cold", 25), ("anxiety", 20),
    ("dehydration", 15), ("other", 10),
)

# מזהי איורים אמיתיים מהרשימה הסגורה (illustrations/illustrations.json) —
# כדי שהדאטה הסינתטי ייראה בדשבורד כמו נתוני אמת.
TOPIC_ILLUSTRATIONS = {
    "wounds": ("wound_cleaning", "stop_bleeding_pressure", "wound_bandaging"),
    "anxiety": ("breathing_exercise", "grounding_54321",
                "muscle_relaxation", "anxiety_settle"),
    "dehydration": ("rehydration_sips", "cooling_down_heat"),
    "cold": ("saline_nasal_rinse", "salt_water_gargle", "steam_inhalation",
             "rest_and_fluids", "measure_temperature"),
}

# תחומים שבהם ההקשר מזג-אוויר רלוונטי (ה-pipeline מדלג על wounds/anxiety).
WEATHER_TOPICS = {"dehydration", "cold"}


def _base_record(session_id: str, turn_index: int, ts: datetime) -> dict:
    """שלד רשומה: תור ללא ייעוץ, כל המונים באפס — התורים השונים מעדכנים."""
    return {
        "schema_version": SCHEMA_VERSION,
        "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": session_id,
        "turn_index": turn_index,
        "emergency": 0,
        "red_flags_count": 0,
        "consulted": 0,
        "consult_path": "none",
        "topic": None,
        "illustration_id": None,
        "sources_count": 0,
        "filtered_sources_count": 0,
        "user_message_chars": None,
        "reply_chars": 0,
        "llm_calls": 2,  # שער הבטיחות + triage רצים תמיד, במקביל
        "t_safety_gate": None,
        "t_triage": None,
        "t_consult": None,
        "t_compose": None,
        "t_total": None,
        "tool_rag_search": 0,
        "tool_locate_place": 0,
        "tool_get_weather": 0,
        "tool_get_current_time": 0,
        "tools_other": 0,
    }


def _reply_turn(rng: random.Random, record: dict) -> dict:
    """תור ברכה/אנמנזה: אן עונה בעצמה, בלי ייעוץ (המסלול הזול ביותר)."""
    gate = rng.uniform(1.2, 3.0)
    triage = rng.uniform(1.5, 3.5)
    record.update(
        user_message_chars=rng.randint(4, 60),
        reply_chars=rng.randint(80, 260),
        t_safety_gate=round(gate, 3),
        t_triage=round(triage, 3),
        t_total=round(max(gate, triage) + rng.uniform(0.02, 0.15), 3),
    )
    return record


def _emergency_turn(rng: random.Random, record: dict) -> dict:
    """תור חירום: Dexter עוצר את השיחה — אין ייעוץ, יש הפניה."""
    gate = rng.uniform(1.5, 4.0)
    triage = rng.uniform(1.5, 4.0)
    record.update(
        emergency=1,
        red_flags_count=rng.randint(1, 3),
        user_message_chars=rng.randint(15, 160),
        reply_chars=rng.randint(180, 400),
        t_safety_gate=round(gate, 3),
        t_triage=round(triage, 3),
        t_total=round(max(gate, triage) + rng.uniform(0.02, 0.15), 3),
    )
    return record


def _consult_turn(rng: random.Random, record: dict) -> dict:
    """תור ייעוץ מלא: ניתוב (ישיר/crew), RAG, איור, מקורות וניסוח."""
    topic = rng.choices(
        [t for t, _ in TOPIC_WEIGHTS], weights=[w for _, w in TOPIC_WEIGHTS],
    )[0]
    # כמו במערכת האמיתית: other תמיד נופל ל-crew ההיררכי; בארבעת התחומים
    # המסלול הישיר הוא הרוב המכריע (רשת הביטחון משלימה רמזים חסרים).
    crew_path = topic == "other" or rng.random() < 0.10
    failsafe = rng.random() < 0.03  # כשל המרה נדיר -> תשובת fallback קבועה

    gate = rng.uniform(1.2, 3.5)
    triage = rng.uniform(1.5, 4.0)
    consult = rng.uniform(10.0, 28.0) if crew_path else rng.uniform(4.0, 12.0)
    compose = rng.uniform(2.0, 6.0)

    record.update(
        consulted=0 if failsafe else 1,
        consult_path="crew" if crew_path else "direct",
        topic=None if failsafe else topic,
        user_message_chars=rng.randint(25, 220),
        llm_calls=rng.randint(7, 12) if crew_path else rng.randint(4, 6),
        tool_rag_search=1 if rng.random() < 0.85 else 2,
        t_safety_gate=round(gate, 3),
        t_triage=round(triage, 3),
        t_consult=round(consult, 3),
    )
    if failsafe:
        record.update(
            reply_chars=rng.randint(120, 160),
            t_total=round(max(gate, triage) + consult + rng.uniform(0.05, 0.3), 3),
        )
        return record

    if topic in WEATHER_TOPICS and rng.random() < 0.35:
        record.update(tool_locate_place=1, tool_get_weather=1)
    if crew_path and rng.random() < 0.20:
        record.update(tool_get_current_time=1)
    if topic in TOPIC_ILLUSTRATIONS and rng.random() < 0.70:
        record.update(illustration_id=rng.choice(TOPIC_ILLUSTRATIONS[topic]))
    record.update(
        sources_count=0 if topic == "other" else rng.randint(1, 3),
        filtered_sources_count=1 if rng.random() < 0.08 else 0,
        reply_chars=rng.randint(300, 900),
        t_compose=round(compose, 3),
        t_total=round(
            max(gate, triage) + consult + compose + rng.uniform(0.05, 0.3), 3,
        ),
    )
    return record


def generate_records(rows: int, rng: random.Random, days: int) -> list[dict]:
    """יצירת ~rows תורים המחולקים לשיחות, פרוסים על פני N הימים האחרונים."""
    now = datetime.now(timezone.utc)
    records: list[dict] = []
    while len(records) < rows:
        session_id = "".join(rng.choice(_HEX) for _ in range(32))
        turn_count = rng.choices(
            (1, 2, 3, 4, 5, 6), weights=(15, 25, 25, 18, 10, 7),
        )[0]
        ts = now - timedelta(days=rng.uniform(0, days))
        for turn_index in range(1, turn_count + 1):
            if len(records) >= rows:
                break
            ts += timedelta(seconds=rng.uniform(40, 240))
            record = _base_record(session_id, turn_index, ts)
            if rng.random() < 0.04:
                records.append(_emergency_turn(rng, record))
                break  # חירום מסיים את השיחה (המשתמש הופנה הלאה)
            if turn_index == 1 and rng.random() < 0.35:
                records.append(_reply_turn(rng, record))
            else:
                records.append(_consult_turn(rng, record))
    return records


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="מחולל דאטה סינתטי ללוג השיחות של אן (חינם, ללא LLM).",
    )
    parser.add_argument("--rows", type=int, default=200,
                        help="מספר תורי-שיחה לייצר (ברירת מחדל: 200)")
    parser.add_argument("--db", default=str(DEFAULT_SYNTH_DB),
                        help="היעד: נתיב קובץ SQLite או שם טבלה ב-Supabase "
                             "(turns / turns_synthetic). ברירת מחדל: "
                             "anne_log_synthetic.db, שממופה ל-turns_synthetic "
                             "כשה-backend הוא supabase")
    parser.add_argument("--seed", type=int, default=7,
                        help="seed לשחזוריות — אותו seed מייצר אותו דאטה")
    parser.add_argument("--days", type=int, default=30,
                        help="פריסת חותמי הזמן על פני N הימים האחרונים")
    parser.add_argument("--reset", action="store_true",
                        help="מחיקת כל הרשומות בקובץ לפני הכתיבה")
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    init_db(args.db)
    if args.reset:
        deleted = reset_log(args.db)
        print(f"נוקו {deleted} רשומות קיימות.")

    records = generate_records(args.rows, rng, args.days)
    # טרנזקציה אחת, דרך scrub + אילוצי ה-CHECK (אותו מסלול כמו תור אמיתי).
    write_records(records, db_path=args.db)

    sessions = {record["session_id"] for record in records}
    emergencies = sum(record["emergency"] for record in records)
    by_topic: dict[str, int] = {}
    for record in records:
        key = record["topic"] or ("emergency" if record["emergency"] else "no_consult")
        by_topic[key] = by_topic.get(key, 0) + 1
    # היעד *בפועל* (אחרי נפילה חיננית, אם הייתה) ולא זה שהתבקש.
    print(f"נכתבו {len(records)} תורים ב-{len(sessions)} שיחות אל: "
          f"{describe_target(args.db)}")
    print(f"  חירום: {emergencies} | פילוח: " + ", ".join(
        f"{key}={count}" for key, count in sorted(by_topic.items())
    ))


if __name__ == "__main__":
    main()
