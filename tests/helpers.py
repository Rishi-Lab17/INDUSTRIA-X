"""Shared test fixtures: one TestClient, one SMTP sink wired into settings.

The sink proves real SMTP delivery over TCP. Tests read the OTP from the
sink's server-side inbox — the API itself never returns it.
"""
import sqlite3

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from mail_sink import SmtpSink

_sink = SmtpSink().start()

s = get_settings()
s.SMTP_HOST = "127.0.0.1"
s.SMTP_PORT = _sink.port
s.SMTP_USERNAME = ""
s.SMTP_PASSWORD = ""
s.SMTP_USE_TLS = False
s.SMTP_FROM_EMAIL = "no-reply@industria-x.test"
s.SMTP_FROM_NAME = "INDUSTRIA-X"

# Enter lifespan (runs init_db) — plain TestClient() would skip startup.
client = TestClient(app)
client.__enter__()

sink = _sink


def db() -> sqlite3.Connection:
    con = sqlite3.connect(str(get_settings().db_path()), timeout=30)
    con.row_factory = sqlite3.Row
    return con


def code_for(email: str) -> str:
    codes = sink.codes_to(email)
    assert codes, f"no verification email captured for {email}"
    return codes[-1]
