"""Shared test fixtures: one TestClient."""
import sqlite3

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

# Enter lifespan (runs init_db) — plain TestClient() would skip startup.
client = TestClient(app)
client.__enter__()


def db() -> sqlite3.Connection:
    con = sqlite3.connect(str(get_settings().db_path()), timeout=30)
    con.row_factory = sqlite3.Row
    return con
