"""Shared test fixtures: one TestClient, one fake Resend API wired into settings.

The fake proves the backend performs a real HTTP call to the email provider
with the right contract. Tests read the OTP from the fake's server-side
record — the API itself never returns it.
"""
import sqlite3

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from resend_fake import FakeResend

_fake = FakeResend().start()

s = get_settings()
s.RESEND_API_KEY = "test-key-not-a-secret"
s.RESEND_FROM_EMAIL = "no-reply@industria-x.test"
s.RESEND_FROM_NAME = "INDUSTRIA-X"
s.RESEND_BASE_URL = _fake.url

# Enter lifespan (runs init_db) — plain TestClient() would skip startup.
client = TestClient(app)
client.__enter__()

fake = _fake


def db() -> sqlite3.Connection:
    con = sqlite3.connect(str(get_settings().db_path()), timeout=30)
    con.row_factory = sqlite3.Row
    return con


def code_for(email: str) -> str:
    codes = fake.codes_to(email)
    assert codes, f"no verification email captured for {email}"
    return codes[-1]
