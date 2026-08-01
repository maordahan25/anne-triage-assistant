"""
storage — שכבת לוג השיחות האנונימית של "אן" (SQLite מקומי או Supabase).

ראה turn_log.py לסכמה ולעקרונות הפרטיות; backend.py למתג ה-backend
(ANNE_LOG_BACKEND) ולנפילה החיננית ל-SQLite; supabase_backend.py לחיבור
ה-Postgres; pg_schema.py לתרגום הסכמה ל-Postgres ולסקריפט המיגרציה;
synthetic.py למחולל דאטה סינתטי.
"""
from .backend import (
    BACKEND_SQLITE,
    BACKEND_SUPABASE,
    BACKENDS,
    DEFAULT_DB_PATH,
    ENV_BACKEND_VAR,
    ENV_DB_VAR,
    ENV_TABLE_VAR,
    LIVE_TABLE,
    SYNTHETIC_DB_PATH,
    SYNTHETIC_TABLE,
    TABLES,
    Target,
    active_backend,
    describe_target,
    fallback_reason,
    resolve_target,
)
from .turn_log import (
    COLUMN_NAMES,
    COLUMNS,
    CONSULT_PATHS,
    SCHEMA_VERSION,
    TOOL_COLUMNS,
    TOPICS,
    fetch_turns,
    init_db,
    log_turn,
    record_from_turn,
    reset_log,
    scrub_record,
    write_record,
    write_records,
)

__all__ = [
    # הסכמה ואוצר המילים הסגור
    "COLUMNS",
    "COLUMN_NAMES",
    "SCHEMA_VERSION",
    "TOPICS",
    "TOOL_COLUMNS",
    "CONSULT_PATHS",
    # ה-API של הלוג — זהה בשני ה-backends
    "init_db",
    "log_turn",
    "write_record",
    "write_records",
    "reset_log",
    "fetch_turns",
    "record_from_turn",
    "scrub_record",
    # שכבת ה-backend
    "BACKENDS",
    "BACKEND_SQLITE",
    "BACKEND_SUPABASE",
    "DEFAULT_DB_PATH",
    "SYNTHETIC_DB_PATH",
    "ENV_DB_VAR",
    "ENV_BACKEND_VAR",
    "ENV_TABLE_VAR",
    "LIVE_TABLE",
    "SYNTHETIC_TABLE",
    "TABLES",
    "Target",
    "active_backend",
    "describe_target",
    "fallback_reason",
    "resolve_target",
]
