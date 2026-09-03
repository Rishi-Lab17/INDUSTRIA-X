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


def init_db() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    con = connect()
    try:
        con.executescript(schema)
        # Lightweight forward-migration for pre-existing databases.
        cols = {r[1] for r in con.execute("PRAGMA table_info(users)").fetchall()}
        if "phone" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        if "phone_verified" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN phone_verified INTEGER NOT NULL DEFAULT 0")
        ccols = {r[1] for r in con.execute("PRAGMA table_info(companies)").fetchall()}
        if "settings" not in ccols:
            con.execute("ALTER TABLE companies ADD COLUMN settings TEXT NOT NULL DEFAULT '{}'")
        acols = {r[1] for r in con.execute("PRAGMA table_info(audit_events)").fetchall()}
        if "entity_type" not in acols:
            con.execute("ALTER TABLE audit_events ADD COLUMN entity_type TEXT")
        if "entity_id" not in acols:
            con.execute("ALTER TABLE audit_events ADD COLUMN entity_id INTEGER")
        con.execute("CREATE INDEX IF NOT EXISTS idx_audit_entity"
                    " ON audit_events(entity_type, entity_id)")
        con.commit()
    finally:
        con.close()
