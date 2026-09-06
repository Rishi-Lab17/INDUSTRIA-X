"""SQLite access. One short-lived connection per operation (WAL mode)."""
import sqlite3
from pathlib import Path

from .core.config import ROOT, get_settings

SCHEMA_PATH = ROOT / "database" / "schema.sql"


def connect() -> sqlite3.Connection:
    s = get_settings()
    db_file: Path = s.db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    for d in s.storage_dirs():
        d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_file), check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def _columns(con, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(con) -> None:
    """Additive forward-migration for pre-existing databases. Runs BEFORE the
    schema script so CREATE INDEX never references missing columns."""
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}

    def ensure(table: str, col: str, ddl: str) -> None:
        if table in tables and col not in _columns(con, table):
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

    ensure("users", "phone", "TEXT")
    ensure("users", "phone_verified", "INTEGER NOT NULL DEFAULT 0")
    ensure("companies", "settings", "TEXT NOT NULL DEFAULT '{}'")
    ensure("audit_events", "entity_type", "TEXT")
    ensure("audit_events", "entity_id", "INTEGER")
    ensure("evidence_recommendations", "slot", "TEXT NOT NULL DEFAULT ''")
    ensure("evidence_recommendations", "priority", "TEXT NOT NULL DEFAULT 'MEDIUM'")
    ensure("sensor_datasets", "quality_detail", "TEXT NOT NULL DEFAULT '{}'")
    for col, ddl in (
            ("processing_note", "TEXT"),
            ("index_status", "TEXT NOT NULL DEFAULT 'NOT_INDEXED'"),
            ("indexed_version", "INTEGER"),
            ("indexed_at", "TEXT"),
            ("index_error", "TEXT"),
            ("chunk_count", "INTEGER NOT NULL DEFAULT 0"),
            ("embedding_model", "TEXT"),
            ("indexed_checksum", "TEXT")):
        ensure("documents", col, ddl)


def init_db() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    con = connect()
    try:
        _migrate(con)
        con.executescript(schema)
        con.execute("CREATE INDEX IF NOT EXISTS idx_audit_entity"
                    " ON audit_events(entity_type, entity_id)")
        con.commit()
    finally:
        con.close()
