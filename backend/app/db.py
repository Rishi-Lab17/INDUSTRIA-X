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
        con.commit()
    finally:
        con.close()
