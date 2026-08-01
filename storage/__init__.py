"""
storage — שכבת לוג השיחות האנונימית של "אן" (SQLite, ספריית התקן בלבד).

ראה turn_log.py לסכמה ולעקרונות הפרטיות; synthetic.py למחולל דאטה סינתטי.
"""
from .turn_log import (
    COLUMN_NAMES,
    DEFAULT_DB_PATH,
    ENV_DB_VAR,
    SCHEMA_VERSION,
    fetch_turns,
    init_db,
    log_turn,
    record_from_turn,
    reset_log,
    scrub_record,
    write_record,
)

__all__ = [
    "COLUMN_NAMES",
    "DEFAULT_DB_PATH",
    "ENV_DB_VAR",
    "SCHEMA_VERSION",
    "fetch_turns",
    "init_db",
    "log_turn",
    "record_from_turn",
    "reset_log",
    "scrub_record",
    "write_record",
]
