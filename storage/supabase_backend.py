"""
ה-backend של Supabase (Postgres) ללוג השיחות — חיבור, DDL וארבע הפעולות.

SQLAlchemy + psycopg (הגלגל הבינארי: ``psycopg[binary]``, בלי קומפילציה
מקומית, wheels ל-macOS ול-Windows). שני הייבואים **עצלים בתוך פונקציות
בכוונה**: ``import storage`` חייב להמשיך לעבוד גם בסביבה שבה החבילות
אינן מותקנות — שם פשוט נרשמת אזהרה והלוג ממשיך ב-SQLite (ראה
storage/backend.py). מאותה סיבה אין כאן שום ייבוא של crew/ או של numpy.

מה יש כאן:
  * **נרמול מחרוזת החיבור** (``normalize_db_url``) — כולל URL-encoding
    לסיסמה, שהוא הבאג שממתין לכל מי שמעתיק מחרוזת חיבור מ-Supabase:
    סיסמה שנוצרה אוטומטית עשויה להכיל ``@ / : ? # %`` ורווח, וכל אחד מהם
    מבלבל כל פרסר URL בעולם. הפירוק כאן ידני (חיתוך ב-``@`` **האחרון**)
    ולא דרך urlsplit, בדיוק כי סיסמה עם ``@`` או ``#`` שוברת את urlsplit
    לפני שהגענו לקודד אותה.
  * **Direct מול Transaction pooler** — פורט 5432 מול 6543. השני דורש
    הגדרות אחרות (בלי prepared statements, בלי pool מקומי), ולכן ההבחנה
    היא בקוד ולא בתיעוד בלבד.
  * **תפר לבדיקות** (``set_connection_factory``) — כל ה-SQL עובר דרך
    ``_connection()``, וכך בדיקות האופליין מזריקות חיבור מדומה ומאמתות
    את המיפוי, את שם הטבלה ואת הנפילה החיננית **בלי שום קריאת רשת**.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import quote

from . import pg_schema
from .backend import (
    ENV_DB_URL_VAR,
    ENV_POOLER_URL_VAR,
    Target,
    missing_supabase_settings,
    supabase_settings,
    warn_once,
)

# הדיאלקט היחיד שאנחנו מדברים: psycopg (מהדורה 3), הגלגל הבינארי.
DRIVER = "postgresql+psycopg"

# סכימות שמותר לקבל מהמשתמש במחרוזת החיבור — כולן מתורגמות ל-DRIVER.
_ACCEPTED_SCHEMES = (
    "postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg2",
    "postgres+psycopg", "postgresql+asyncpg",
)

# פורט ה-Transaction pooler של Supabase, ושם המאחסן שלו.
POOLER_PORT = 6543
DIRECT_PORT = 5432
_POOLER_HOST_MARK = "pooler.supabase.com"

# ברירות מחדל שמוזרקות למחרוזת החיבור אם אינן מופיעות בה:
# Supabase דורשת TLS, וטיים-אאוט קצר הוא מה שהופך "אין רשת" לנפילה
# חיננית מהירה במקום תור שנתקע.
_DEFAULT_QUERY = (("sslmode", "require"), ("connect_timeout", "5"))

_ENCODED_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_SCHEME_RE = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*)://(?P<rest>.*)$",
                        re.DOTALL)

# מטמון המנועים (מחרוזת חיבור -> Engine) והטבלאות שכבר הוכנו בתהליך הזה.
_engines: dict[str, Any] = {}
_ready_tables: set[str] = set()
_active_url: str | None = None

# תפר הבדיקות: מפעל חיבורים חלופי (context manager). None = המנוע האמיתי.
_connection_factory: Callable[[], Any] | None = None


class SupabaseConfigError(RuntimeError):
    """הגדרות חסרות או פסולות — הודעה בעברית, ונפילה חיננית ל-SQLite."""


class SupabaseDependencyError(RuntimeError):
    """SQLAlchemy/psycopg אינם מותקנים בסביבה הזו."""


# ── מחרוזת החיבור ────────────────────────────────────────────────────────
def _split_url(raw: str) -> tuple[str, str, str, str]:
    """
    פירוק מחרוזת חיבור ל-(scheme, user, password, hostpart) — פירוק ידני.

    החיתוך הוא ב-``@`` **האחרון**: מותר לסיסמה להכיל ``@``, לשם המאחסן
    לא. אחרי החיתוך, החלוקה ל-user/password היא ב-``:`` הראשון (סיסמה
    עשויה להכיל ``:``). זה בדיוק המקום שבו urlsplit נכשל, ולכן הוא לא
    בשימוש כאן.
    """
    match = _SCHEME_RE.match(raw)
    if match:
        scheme, rest = match.group("scheme"), match.group("rest")
    else:
        scheme, rest = "postgresql", raw
    if "@" in rest:
        userinfo, hostpart = rest.rsplit("@", 1)
    else:
        userinfo, hostpart = "", rest
    user, _, password = userinfo.partition(":")
    return scheme, user, password, hostpart


def _looks_encoded(value: str) -> bool:
    """האם הערך כבר מכיל תווי %XX — כלומר כבר קודד, ואין לקודד פעמיים."""
    return bool(_ENCODED_RE.search(value))


def encode_credential(value: str) -> str:
    """
    URL-encoding לשם משתמש/סיסמה, בלי קידוד כפול.

    ``safe=""`` מקודד גם ``/``, ``@``, ``:`` ו-``?`` — בדיוק התווים
    שמפרקים מחרוזת חיבור. אם הערך כבר מכיל ``%XX`` מניחים שהמשתמש הדביק
    מחרוזת מקודדת ומשאירים אותה כפי שהיא, אחרת ``%40`` היה הופך
    ל-``%2540`` והסיסמה הייתה נכשלת בשקט.
    """
    if not value or _looks_encoded(value):
        return value
    return quote(value, safe="")


def _split_hostpart(hostpart: str) -> tuple[str, str]:
    """(בסיס, query) — הפרדת מחרוזת השאילתה מהמאחסן/הפורט/שם ה-DB."""
    base, sep, query = hostpart.partition("?")
    return base, query if sep else ""


def _with_default_query(hostpart: str) -> str:
    """השלמת sslmode ו-connect_timeout אם לא נמסרו במחרוזת."""
    base, query = _split_hostpart(hostpart)
    pairs = [pair for pair in query.split("&") if pair]
    present = {pair.split("=", 1)[0].lower() for pair in pairs}
    for key, value in _DEFAULT_QUERY:
        if key not in present:
            pairs.append(f"{key}={value}")
    return f"{base}?{'&'.join(pairs)}" if pairs else base


def normalize_db_url(raw: str) -> str:
    """
    מחרוזת החיבור כפי שהיא נמסרת ב-.env -> מחרוזת שאפשר לתת ל-SQLAlchemy.

    שלושה דברים: הסכימה מתורגמת ל-``postgresql+psycopg``, שם המשתמש
    והסיסמה מקודדים ב-URL-encoding (ראה encode_credential), ו-sslmode/
    connect_timeout מושלמים. הסיסמה עצמה אינה נרשמת לשום לוג — לתצוגה יש
    ``safe_display_url``.
    """
    text = (raw or "").strip()
    if not text:
        raise SupabaseConfigError(
            f"מחרוזת החיבור ל-Supabase ריקה ({ENV_DB_URL_VAR})."
        )
    scheme, user, password, hostpart = _split_url(text)
    if scheme.lower() not in _ACCEPTED_SCHEMES:
        raise SupabaseConfigError(
            f"סכימת חיבור לא נתמכת: {scheme!r}. "
            "מצופה מחרוזת Postgres (postgresql://...)."
        )
    base, _ = _split_hostpart(hostpart)
    if not base or base.startswith("/"):
        raise SupabaseConfigError(
            "מחרוזת החיבור ל-Supabase חסרה מאחסן (host) — "
            "העתיקו אותה מ-Supabase: Connect -> Direct connection."
        )
    userinfo = encode_credential(user)
    if password:
        userinfo = f"{userinfo}:{encode_credential(password)}"
    prefix = f"{userinfo}@" if userinfo else ""
    return f"{DRIVER}://{prefix}{_with_default_query(hostpart)}"


def safe_display_url(url: str) -> str:
    """אותה מחרוזת עם הסיסמה מוסתרת — הצורה היחידה שמותר לרשום ללוג."""
    if not url:
        return ""
    scheme, user, password, hostpart = _split_url(url)
    if not password:
        return url
    userinfo = f"{user}:***" if user else "***"
    return f"{scheme}://{userinfo}@{hostpart}"


def _host_and_port(url: str) -> tuple[str, int | None]:
    """(מאחסן, פורט) ממחרוזת חיבור מנורמלת."""
    _, _, _, hostpart = _split_url(url)
    base, _ = _split_hostpart(hostpart)
    authority = base.split("/", 1)[0]
    host, sep, port = authority.rpartition(":")
    if not sep or not port.isdigit():
        return authority, None
    return host, int(port)


def is_pooler_url(url: str) -> bool:
    """
    האם זו מחרוזת של ה-Transaction pooler ולא חיבור ישיר.

    שני סימנים, וכל אחד מספיק: הפורט 6543, או שם המאחסן של ה-pooler
    (``…pooler.supabase.com``, שמשמש גם את ה-Session pooler בפורט 5432).
    ההבחנה משנה התנהגות: ב-transaction pooling כל טרנזקציה עשויה לקבל
    חיבור אחר, ולכן prepared statements בצד השרת נשברים ואין טעם ב-pool
    מקומי מעל pool מרוחק.
    """
    host, port = _host_and_port(url)
    return port == POOLER_PORT or _POOLER_HOST_MARK in host.lower()


def engine_options(url: str) -> dict[str, Any]:
    """
    הגדרות ה-Engine לפי סוג החיבור — פונקציה טהורה (נבדקת בלי SQLAlchemy).

    ``poolclass`` מוחזר כשם ולא כמחלקה בדיוק כדי שהפונקציה לא תדרוש את
    SQLAlchemy; ``_engine`` מתרגם אותו. חיבור ישיר: pool קטן עם
    pre-ping ומיחזור, כי אותו תהליך כותב תור אחרי תור. pooler: בלי pool
    מקומי (``NullPool``) ובלי prepared statements
    (``prepare_threshold=None``) — שתי הדרישות של pgbouncer במצב
    טרנזקציה.
    """
    if is_pooler_url(url):
        return {
            "poolclass": "NullPool",
            "pool_pre_ping": False,
            "connect_args": {"prepare_threshold": None},
        }
    return {
        "poolclass": None,
        "pool_pre_ping": True,
        "pool_size": 2,
        "max_overflow": 2,
        "pool_recycle": 300,
        "connect_args": {},
    }


def candidate_urls() -> list[tuple[str, str]]:
    """
    מחרוזות החיבור לניסיון, בסדר: מה שהוגדר, ואחריו ה-pooler אם הוגדר.

    Supabase מפרסמת שתי מחרוזות שונות לאותו פרויקט (Direct בפורט 5432
    ו-Transaction pooler בפורט 6543), ושם המאחסן של ה-pooler כולל את
    האזור — כלומר **אי אפשר לגזור אותו** מהמחרוזת הישירה. לכן הגיבוי
    האוטומטי קיים רק כשמדביקים גם אותו ל-SUPABASE_DB_URL_POOLER;
    להחלפה מלאה פשוט מחליפים את SUPABASE_DB_URL (ראה README).
    """
    missing = missing_supabase_settings()
    if missing:
        raise SupabaseConfigError(
            "חסרות הגדרות Supabase ב-.env: " + ", ".join(missing)
        )
    settings = supabase_settings()
    candidates = [("ישיר", normalize_db_url(settings["db_url"]))]
    if settings["pooler_url"]:
        pooler = normalize_db_url(settings["pooler_url"])
        if pooler != candidates[0][1]:
            candidates.append(("pooler", pooler))
    return candidates


# ── המנוע והחיבור ────────────────────────────────────────────────────────
def _create_engine(url: str):
    """יצירת Engine אחד. ייבוא SQLAlchemy עצל — כאן ולא בראש הקובץ."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool
    except Exception as exc:  # ImportError, וגם התקנה שבורה
        raise SupabaseDependencyError(
            "החבילות לחיבור Supabase אינן מותקנות "
            "(SQLAlchemy / psycopg). התקינו: "
            "pip install --prefer-binary -r llm_requirements.txt"
        ) from exc
    options = dict(engine_options(url))
    pool_name = options.pop("poolclass", None)
    if pool_name == "NullPool":
        options["poolclass"] = NullPool
    return create_engine(url, **options)


def _probe(engine) -> None:
    """בדיקת חיבור זולה (SELECT 1) — כדי שכשל יתגלה כאן ולא בכתיבה."""
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(text("select 1"))


def _engine():
    """
    ה-Engine הפעיל, עם ניסיון גיבוי ל-pooler אם הישיר נכשל.

    המנוע נשמר במטמון לכל התהליך: בלעדיו כל תור היה פותח חיבור חדש
    לפוסטגרס מרוחק (עוד ~100-300ms לכל הודעה).
    """
    global _active_url
    if _active_url is not None and _active_url in _engines:
        return _engines[_active_url]

    errors: list[str] = []
    for label, url in candidate_urls():
        engine = _engines.get(url) or _create_engine(url)
        try:
            _probe(engine)
        except Exception as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
            warn_once(
                f"חיבור {label} ל-Supabase נכשל "
                f"({safe_display_url(url)}): {type(exc).__name__}"
            )
            continue
        _engines[url] = engine
        _active_url = url
        return engine
    raise SupabaseConfigError("החיבור ל-Supabase נכשל — " + " | ".join(errors))


class _SqlAlchemyConnection:
    """
    עטיפה דקה מעל חיבור SQLAlchemy — שתי מתודות, וזה כל החוזה.

    בדיוק אותן שתי מתודות ממומשות בחיבור המדומה של הבדיקות, ולכן אפשר
    לאמת את כל השכבה הזו בלי רשת ובלי Postgres.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    def execute(self, sql: str, params: dict | None = None) -> list[dict]:
        from sqlalchemy import text

        result = self._conn.execute(text(sql), params or {})
        if not result.returns_rows:
            return []
        return [dict(row) for row in result.mappings()]

    def execute_many(self, sql: str, rows: Sequence[dict]) -> None:
        from sqlalchemy import text

        if rows:
            self._conn.execute(text(sql), list(rows))


@contextmanager
def _connection():
    """חיבור פתוח בטרנזקציה אחת (או החיבור המדומה של הבדיקות)."""
    if _connection_factory is not None:
        with _connection_factory() as conn:
            yield conn
        return
    engine = _engine()
    with engine.begin() as raw:
        yield _SqlAlchemyConnection(raw)


def set_connection_factory(factory: Callable[[], Any] | None) -> None:
    """
    הזרקת מפעל חיבורים — **לבדיקות בלבד**; None מחזיר את המנוע האמיתי.

    המפעל מחזיר context manager שנותן אובייקט עם execute/execute_many.
    """
    global _connection_factory
    _connection_factory = factory
    reset_connection_state()


def reset_connection_state() -> None:
    """שכחת המנוע והטבלאות שהוכנו (בדיקות, או ניסיון חיבור מחדש)."""
    global _active_url
    _engines.clear()
    _ready_tables.clear()
    _active_url = None


def active_url() -> str | None:
    """מחרוזת החיבור שנבחרה בפועל, עם סיסמה מוסתרת (לדיווח)."""
    return safe_display_url(_active_url) if _active_url else None


# ── ארבע הפעולות שמעליהן יושב turn_log ───────────────────────────────────
def _existing_columns(conn, table: str) -> set[str]:
    """שמות העמודות הקיימות בטבלה (ריק = הטבלה אינה קיימת)."""
    rows = conn.execute(
        "select column_name from information_schema.columns "
        "where table_schema = :schema and table_name = :table",
        {"schema": pg_schema.SCHEMA, "table": pg_schema.require_table(table)},
    )
    return {str(row["column_name"]) for row in rows}


def ensure_ready(target: Target) -> str:
    """
    לוודא שהטבלה קיימת, מאובטחת ומעודכנת — פעם אחת בכל תהליך.

    המסלול המהיר הוא שאילתה אחת: אם כל 26 העמודות + id כבר שם, אין מה
    לעשות. כשמשהו חסר מריצים את ההצהרות של pg_schema — ורק אז גם את
    הצהרות האבטחה, כדי שטבלה שהקוד יצר לא תישאר בלי RLS. הן רצות כל אחת
    בטרנזקציה נפרדת בכוונה: ב-Postgres הצהרה שנכשלת מפילה את הטרנזקציה
    כולה, ו-``revoke ... from anon`` נכשל בפוסטגרס שאינו Supabase
    (התפקיד לא קיים) — זה ראוי לאזהרה, לא לביטול הכתיבה.
    """
    table = pg_schema.require_table(target.table)
    if table in _ready_tables:
        return table
    expected = {"id", *pg_schema.PG_COLUMNS}
    with _connection() as conn:
        existing = _existing_columns(conn, table)
        created = not expected <= existing
        if created:
            for statement in (
                pg_schema.create_table_sql(table),
                *pg_schema.add_columns_sql(table),
                *pg_schema.create_index_sql(table),
                pg_schema.comment_sql(table),
            ):
                conn.execute(statement)
            missing_after = expected - _existing_columns(conn, table)
            if missing_after:
                raise SupabaseConfigError(
                    f"הטבלה {table} נוצרה אך חסרות בה עמודות: "
                    f"{sorted(missing_after)}"
                )
    if created:
        for statement in pg_schema.security_sql(table):
            try:
                with _connection() as conn:
                    conn.execute(statement)
            except Exception as exc:
                warn_once(
                    f"הגדרת אבטחה לא הוחלה על {table} "
                    f"({statement.split(' on ')[0]}): {type(exc).__name__}. "
                    "הריצו את סקריפט המיגרציה ב-SQL Editor של Supabase."
                )
    _ready_tables.add(table)
    return table


def insert_records(target: Target, records: Iterable[dict]) -> int:
    """כתיבת רשומות מנוקות (כבר עברו scrub_record) בטרנזקציה אחת."""
    rows = [
        {name: record[name] for name in pg_schema.PG_COLUMNS}
        for record in records
    ]
    if not rows:
        return 0
    with _connection() as conn:
        conn.execute_many(pg_schema.insert_sql(target.table), rows)
    return len(rows)


def fetch_records(target: Target, limit: int | None = None) -> list[dict]:
    """קריאת הרשומות בסדר כרונולוגי — אותה צורה כמו ב-SQLite (list[dict])."""
    with _connection() as conn:
        return [dict(row) for row in
                conn.execute(pg_schema.select_sql(target.table, limit))]


def delete_all(target: Target) -> int:
    """מחיקת כל הרשומות (כפתור המנהל). מחזיר כמה נמחקו."""
    with _connection() as conn:
        rows = conn.execute(pg_schema.count_sql(target.table))
        before = int(rows[0]["rows"]) if rows else 0
        conn.execute(pg_schema.delete_all_sql(target.table))
    return before
