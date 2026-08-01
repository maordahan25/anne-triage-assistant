"""
סכמת ה-Postgres של לוג השיחות — אותן 26 עמודות בדיוק, בניב של Supabase.

הסכמה נגזרת מ-turn_log.COLUMNS (מקור אמת אחד): שמות העמודות, סדרן ואוצר
המילים הסגור של topic ו-consult_path מיובאים משם, ולא מועתקים לכאן.
מה שכן חי כאן הוא התרגום הדיאלקטי, שאין ממנו מנוס:

  * ``INTEGER PRIMARY KEY AUTOINCREMENT`` -> ``bigint generated always as
    identity`` (וכך גם אי אפשר להזריק id ידנית — אנחנו לעולם לא כותבים אותו).
  * ל-SQLite יש ``GLOB``, ל-Postgres יש ביטויים רגולריים (``~``). התבניות
    כתובות במחלקות ``[0-9]``/``[a-z]`` ובלי לוכסנים אחורה בכוונה, כדי שלא
    יהיה תלוי ב-standard_conforming_strings.
  * ``REAL`` -> ``double precision`` (אותם 8 בתים).

**שתי טבלאות באותו פרויקט**: ``turns`` (הלוג החי) ו-``turns_synthetic``
(הדאטה הסינתטי לדשבורד ולמודל החיזוי). אותה סכמה בדיוק, ולכן אותו בונה
DDL — המתג בדשבורד מחליף טבלה, לא חיבור ולא פרויקט.

**אבטחה היא חלק מהיצירה, לא צעד שאחריה**: כל טבלה נוצרת עם RLS מופעל
וללא אף policy, והרשאות ``anon``/``authenticated`` נשללות ממנה במפורש —
כלומר מפתח ה-anon הציבורי (זה שיושב בדפדפן) אינו יכול לקרוא או לכתוב את
הלוג. ה-service key וחיבור ה-Postgres של הפרויקט עוקפים RLS ולכן ממשיכים
לעבוד. הפעולות האלה נכנסות גם ל-``migration_sql()`` (הקובץ שמריצים ב-SQL
Editor) וגם ל-``ensure_table_sql()`` (מה שהקוד מריץ אם הטבלה חסרה) — כדי
שטבלה שנוצרה אוטומטית לא תהיה חשופה יותר מטבלה שנוצרה ידנית.

הקובץ ``storage/migrations/001_create_turns.sql`` נוצר מכאן:

    python -m storage.pg_schema            # הדפסה בלבד
    python -m storage.pg_schema --write    # כתיבה לקובץ המיגרציה

בדיקת אופליין משווה את הקובץ לפלט הפונקציה — כך הוא לא יכול להתיישן.
"""
from __future__ import annotations

from pathlib import Path

from .backend import LIVE_TABLE, SYNTHETIC_TABLE, TABLES
from .turn_log import COLUMN_NAMES, CONSULT_PATHS, TOPICS

SCHEMA = "public"

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATION_FILE = MIGRATIONS_DIR / "001_create_turns.sql"


# ── בוני הגדרות עמודה (מקבילים לוולידטורים שב-turn_log) ──────────────────
def _flag(name: str, *, default: bool = False) -> str:
    """דגל 0/1 (מקביל ל-_flag בפייתון)."""
    suffix = " default 0" if default else ""
    return f"{name} integer not null{suffix} check ({name} in (0, 1))"


def _count(name: str) -> str:
    """מונה שלם אי-שלילי."""
    return f"{name} integer not null check ({name} >= 0)"


def _count_or_null(name: str) -> str:
    return f"{name} integer check ({name} is null or {name} >= 0)"


def _seconds(name: str) -> str:
    """משך בשניות, אי-שלילי או NULL."""
    return f"{name} double precision check ({name} is null or {name} >= 0)"


def _enum(name: str, allowed: tuple[str, ...], *, optional: bool) -> str:
    """אוצר מילים סגור — אותה רשימה שבה משתמש הוולידטור בפייתון."""
    values = ", ".join(f"'{value}'" for value in allowed)
    if optional:
        return f"{name} text check ({name} is null or {name} in ({values}))"
    return f"{name} text not null check ({name} in ({values}))"


# ── 26 העמודות, באותו סדר בדיוק כמו COLUMN_NAMES ─────────────────────────
PG_COLUMNS: dict[str, str] = {
    "schema_version":
        "schema_version integer not null check (schema_version >= 1)",
    "ts_utc":
        "ts_utc text not null check (ts_utc ~ "
        "'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$')",
    "session_id":
        "session_id text not null check (char_length(session_id) = 32 "
        "and session_id ~ '^[0-9a-f]+$')",
    "turn_index":
        "turn_index integer not null check (turn_index >= 1)",
    "emergency": _flag("emergency"),
    "red_flags_count": _count("red_flags_count"),
    "consulted": _flag("consulted"),
    "consult_path": _enum("consult_path", CONSULT_PATHS, optional=False),
    "topic": _enum("topic", TOPICS, optional=True),
    "illustration_id":
        "illustration_id text check (illustration_id is null or "
        "(char_length(illustration_id) between 1 and 64 "
        "and illustration_id ~ '^[a-z0-9_]+$'))",
    "sources_count": _count("sources_count"),
    "filtered_sources_count": _count("filtered_sources_count"),
    "user_message_chars": _count_or_null("user_message_chars"),
    "reply_chars": _count("reply_chars"),
    "llm_calls": _count("llm_calls"),
    "t_safety_gate": _seconds("t_safety_gate"),
    "t_triage": _seconds("t_triage"),
    "t_consult": _seconds("t_consult"),
    "t_compose": _seconds("t_compose"),
    "t_total": _seconds("t_total"),
    "tool_rag_search": _count("tool_rag_search"),
    "tool_locate_place": _count("tool_locate_place"),
    "tool_get_weather": _count("tool_get_weather"),
    "tool_get_current_time": _count("tool_get_current_time"),
    "tools_other": _count("tools_other"),
    # אחרון, כמו ב-SQLite: עמודה שנוספת בסכמה נכנסת בסוף, כדי שטבלה
    # שעברה ALTER וטבלה שנוצרה מאפס יהיו זהות גם בסדר העמודות.
    "image_attached": _flag("image_attached", default=True),
}

ID_COLUMN = "id bigint generated always as identity primary key"


class SchemaMismatch(RuntimeError):
    """הסכמה כאן והסכמה ב-turn_log התפצלו — תקלת פיתוח, לא תקלת ריצה."""


def assert_matches_declared_schema() -> None:
    """
    שומר הסף: אותן עמודות, באותו סדר, כמו turn_log.COLUMNS.

    עמודה חדשה בלוג תשבור את הבדיקה הזו עד שתתורגם גם לכאן — בדיוק כמו
    שומר הסיווג ב-ml/dataset.py. עדיף להיכשל בבדיקה חינמית מלגלות בזמן
    כתיבה ש-INSERT מפנה לעמודה שאינה קיימת.
    """
    if tuple(PG_COLUMNS) != tuple(COLUMN_NAMES):
        missing = [name for name in COLUMN_NAMES if name not in PG_COLUMNS]
        extra = [name for name in PG_COLUMNS if name not in COLUMN_NAMES]
        raise SchemaMismatch(
            "סכמת ה-Postgres אינה תואמת לסכמה המוצהרת: "
            f"חסרות={missing} · עודפות={extra} · "
            f"סדר זהה={list(PG_COLUMNS) == list(COLUMN_NAMES)}"
        )


def require_table(table: str) -> str:
    """
    אימות שם טבלה מול הרשימה הסגורה — לפני שהוא נכנס למחרוזת SQL.

    שם טבלה הוא מזהה ואי אפשר להעביר אותו כפרמטר, ולכן זו הגנת ההזרקה
    היחידה שיש: כל בונה SQL בקובץ הזה עובר דרך כאן.
    """
    if table not in TABLES:
        raise ValueError(
            f"שם טבלה מחוץ לרשימה הסגורה: {table!r} "
            f"(מותר: {' / '.join(TABLES)})"
        )
    return table


def qualified(table: str) -> str:
    """שם הטבלה המלא, כולל הסכמה (public.turns)."""
    return f"{SCHEMA}.{require_table(table)}"


# ── בוני ה-SQL ───────────────────────────────────────────────────────────
def create_table_sql(table: str) -> str:
    """CREATE TABLE IF NOT EXISTS עם כל 26 העמודות ואילוצי ה-CHECK."""
    assert_matches_declared_schema()
    body = ",\n    ".join([ID_COLUMN, *PG_COLUMNS.values()])
    return f"create table if not exists {qualified(table)} (\n    {body}\n)"


def add_columns_sql(table: str) -> list[str]:
    """
    השלמת עמודות בטבלה שנוצרה לפני שהעמודה נוספה לסכמה (אידמפוטנטי).

    המקביל של _migrate ב-SQLite: ADD COLUMN IF NOT EXISTS מדלג על עמודה
    קיימת ולכן אפשר להריץ את הכול שוב. אותה מגבלה תקפה כאן: עמודה חדשה
    שהיא NOT NULL חייבת לבוא עם DEFAULT, אחרת ההוספה תיכשל על טבלה שיש
    בה כבר רשומות.
    """
    name = qualified(table)
    return [
        f"alter table {name} add column if not exists {definition}"
        for definition in PG_COLUMNS.values()
    ]


def create_index_sql(table: str) -> list[str]:
    """אינדקסים על חותם הזמן ועל מזהה השיחה (כמו ב-SQLite)."""
    name = qualified(table)
    return [
        f"create index if not exists idx_{table}_ts on {name} (ts_utc)",
        f"create index if not exists idx_{table}_session on {name} (session_id)",
    ]


def security_sql(table: str) -> list[str]:
    """
    RLS + שלילת הרשאות מ-anon: הלוג אינו נגיש למפתח הציבורי שבדפדפן.

    RLS מופעל בלי אף policy — כלומר כל תפקיד שכפוף ל-RLS (anon,
    authenticated) לא רואה ולא כותב כלום. ה-REVOKE הוא השכבה השנייה,
    ולא קוסמטיקה: Supabase מעניקה הרשאות לתפקידים האלה על טבלאות חדשות
    ב-public כברירת מחדל, כך שבלי השלילה הן היו נשארות. service_role
    (ומחרוזת החיבור של הפרויקט) עוקפים RLS וממשיכים לעבוד.
    """
    name = qualified(table)
    return [
        f"alter table {name} enable row level security",
        f"revoke all on table {name} from anon",
        f"revoke all on table {name} from authenticated",
        f"grant all on table {name} to service_role",
    ]


def comment_sql(table: str) -> str:
    """הערה על הטבלה — נראית ב-Table Editor של Supabase."""
    kind = "דאטה סינתטי לניסוי" if table == SYNTHETIC_TABLE else "לוג חי"
    return (
        f"comment on table {qualified(table)} is "
        f"'אן — לוג שיחות אנונימי ({kind}). "
        "אין בטבלה טקסט משתמש: אורכים, מונים וקטגוריות סגורות בלבד.'"
    )


def ensure_table_sql(table: str) -> list[str]:
    """
    כל ההצהרות הדרושות כדי שהטבלה תהיה קיימת, מאובטחת ומעודכנת.

    זה מה שהקוד מריץ בפעם הראשונה בתהליך (init_db), וזה גם הגוף של קובץ
    המיגרציה — אותו מקור, כדי שטבלה שנוצרה אוטומטית לא תפגר אחרי טבלה
    שנוצרה ידנית. הכול אידמפוטנטי.
    """
    return [
        create_table_sql(table),
        *add_columns_sql(table),
        *create_index_sql(table),
        *security_sql(table),
        comment_sql(table),
    ]


def insert_sql(table: str) -> str:
    """INSERT עם פרמטרים בשם (:ts_utc) — הערכים לעולם לא בתוך ה-SQL."""
    assert_matches_declared_schema()
    columns = ", ".join(PG_COLUMNS)
    values = ", ".join(f":{name}" for name in PG_COLUMNS)
    return f"insert into {qualified(table)} ({columns}) values ({values})"


def select_sql(table: str, limit: int | None = None) -> str:
    """SELECT בסדר כרונולוגי (id), עם אותן עמודות שהסכמה מצהירה."""
    assert_matches_declared_schema()
    columns = ", ".join(["id", *PG_COLUMNS])
    sql = f"select {columns} from {qualified(table)} order by id"
    if limit is not None:
        sql += f" limit {int(limit)}"
    return sql


def count_sql(table: str) -> str:
    return f"select count(*) as rows from {qualified(table)}"


def delete_all_sql(table: str) -> str:
    return f"delete from {qualified(table)}"


# ── קובץ המיגרציה (מה שמריצים ב-SQL Editor של Supabase) ──────────────────
_MIGRATION_HEADER = """\
-- ═══════════════════════════════════════════════════════════════════════
-- אן — לוג השיחות האנונימי ב-Supabase (Postgres)
-- ═══════════════════════════════════════════════════════════════════════
-- מה זה: יצירת שתי הטבלאות שמאחורי storage/ — turns (הלוג החי) ו-
-- turns_synthetic (הדאטה הסינתטי לדשבורד ולמודל החיזוי). אותן 26
-- עמודות בדיוק כמו סכמת ה-SQLite, כולל אילוצי ה-CHECK: הפרטיות של הלוג
-- מובנית בסכמה עצמה (אין אף עמודת טקסט חופשי), ולא רק בקוד שכותב אליה.
--
-- איך מריצים: Supabase -> SQL Editor -> New query -> הדביקו והריצו.
-- הסקריפט אידמפוטנטי: אפשר להריץ אותו שוב בבטחה (create/add column/
-- create index -> if not exists), וגם אחרי הוספת עמודה לסכמה.
--
-- אבטחה: כל טבלה נוצרת עם RLS מופעל וללא אף policy, וההרשאות של anon
-- ושל authenticated נשללות ממנה במפורש — מפתח ה-anon הציבורי אינו יכול
-- לקרוא או לכתוב את הלוג. השרת מתחבר במחרוזת החיבור של הפרויקט
-- (SUPABASE_DB_URL), שאינה כפופה ל-RLS, ולכן הוא ממשיך לעבוד.
--
-- ⚠ אין לערוך את הקובץ ידנית: הוא נוצר מ-storage/pg_schema.py, שהוא
--   התרגום היחיד של הסכמה ל-Postgres —
--       python -m storage.pg_schema --write
--   ובדיקת אופליין משווה את הקובץ לפלט הפונקציה.
-- ═══════════════════════════════════════════════════════════════════════
"""

_MIGRATION_FOOTER = """\
-- ── אימות (להרצה ידנית, לא חלק מהמיגרציה) ────────────────────────────
--   select table_name, count(*) as columns
--     from information_schema.columns
--    where table_schema = 'public'
--      and table_name in ('turns', 'turns_synthetic')
--    group by table_name;            -- מצופה: 27 (26 + id) לכל טבלה
--
--   select relname, relrowsecurity
--     from pg_class
--    where relname in ('turns', 'turns_synthetic');   -- מצופה: true
"""


def migration_sql() -> str:
    """
    תוכן קובץ המיגרציה במלואו — הכותרת, שתי הטבלאות והערות האימות.

    זה גם התוכן שנשמר ב-storage/migrations/001_create_turns.sql, ובדיקת
    אופליין משווה ביניהם: כך אי אפשר לשנות את הסכמה ולשכוח את הקובץ.
    """
    parts = [_MIGRATION_HEADER]
    for table in (LIVE_TABLE, SYNTHETIC_TABLE):
        kind = ("הדאטה הסינתטי" if table == SYNTHETIC_TABLE else "הלוג החי")
        parts.append(
            f"\n-- ── {qualified(table)} — {kind} "
            + "─" * max(2, 46 - len(qualified(table)) - len(kind))
            + "\n"
            + "".join(f"{statement};\n" for statement in ensure_table_sql(table))
        )
    parts.append("\n" + _MIGRATION_FOOTER)
    return "".join(parts)


def write_migration_file(path: Path | None = None) -> Path:
    """כתיבת קובץ המיגרציה מהסכמה. מחזיר את הנתיב."""
    target = Path(path) if path is not None else MIGRATION_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(migration_sql(), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="ה-DDL של לוג השיחות ל-Postgres/Supabase (חינם, ללא רשת).",
    )
    parser.add_argument("--write", action="store_true",
                        help="כתיבת קובץ המיגרציה במקום הדפסה בלבד")
    args = parser.parse_args(argv)

    assert_matches_declared_schema()
    if args.write:
        path = write_migration_file()
        print(f"נכתב: {path}")
        print(f"הריצו אותו ב-SQL Editor של Supabase ({len(TABLES)} טבלאות, "
              f"{len(PG_COLUMNS)} עמודות + id).")
    else:
        print(migration_sql())


if __name__ == "__main__":
    main()
