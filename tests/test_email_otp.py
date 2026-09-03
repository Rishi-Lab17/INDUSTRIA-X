"""Email-OTP verification tests: real Resend HTTP call to a fake provider,
no OTP in API, single-use, expiry, resend invalidation, cooldown, rate limits,
replay/brute-force protection, Resend-failure safety, unconfigured-provider
refusal, Firebase-unconfigured honesty."""
import re

from app.core.config import get_settings
from app.core.rate_limit import allow, reset_all
from helpers import client, code_for, db, fake

N = 0


def _next(prefix="otp"):
    global N
    N += 1
    return f"{prefix}{N}@email.test", f"{prefix.capitalize()} Co {N}"


def _register(email, company, mobile="+919876543210"):
    body = {"company_name": company, "name": "T User",
            "email": email, "password": "Str0ngPass!"}
    if mobile is not None:
        body["mobile_number"] = mobile
    return client.post("/api/auth/register", json=body)


def test_register_sends_via_resend_and_hides_otp():
    email, company = _next()
    r = _register(email, company)
    assert r.status_code == 201, r.text
    assert r.json() == {"message": "Verification code sent to your email address.",
                        "email_masked": "o****@email.test", "dev_mode": False}
    assert "dev_otp" not in r.text and "verification_code" not in r.text.lower()

    # A real HTTP call hit the provider with the right contract.
    m = fake.last_to(email)
    assert m is not None
    assert m["path"] == "/emails"
    assert m["auth"].startswith("Bearer ") and len(m["auth"]) > 10
    assert m["content_type"] == "application/json"
    assert m["body"]["subject"] == "INDUSTRIA-X Email Verification"
    assert m["body"]["from"] == "INDUSTRIA-X <no-reply@industria-x.test>"
    codes = re.findall(r"(?m)^(\d{6})\r?$", m["body"].get("text", ""))
    assert len(codes) == 1
    # The transmitted code is NOT anywhere in the API response...
    assert codes[0] not in r.text
    # ...and neither is the provider API key.
    assert "test-key-not-a-secret" not in r.text

    # DB stores only a hash, user is unverified.
    con = db()
    try:
        user = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        assert user and not user["is_active"]
        assert user["phone"] == "+919876543210" and not user["phone_verified"]
        row = con.execute("SELECT * FROM otp_codes WHERE user_id = ?",
                          (user["id"],)).fetchone()
        assert row and row["code_hash"] != codes[0] and len(row["code_hash"]) == 64
    finally:
        con.close()


def test_verify_correct_code_replay_fails_and_audit_clean():
    email, company = _next()
    assert _register(email, company).status_code == 201
    code = code_for(email)

    r = client.post("/api/auth/verify-otp", json={"email": email, "code": code})
    assert r.status_code == 200
    assert r.json()["message"] == "Email verified successfully. You can now log in."

    # Replay of the same code must fail (single use).
    r2 = client.post("/api/auth/verify-otp", json={"email": email, "code": code})
    assert r2.status_code == 400

    # The plaintext code must not appear in any audit record.
    con = db()
    try:
        rows = con.execute("SELECT detail FROM audit_events").fetchall()
        assert all(code not in (row[0] or "") for row in rows)
    finally:
        con.close()

    # Login works after verification.
    lr = client.post("/api/auth/login",
                     json={"email": email, "password": "Str0ngPass!"})
    assert lr.status_code == 200


def test_wrong_and_expired_codes():
    email, company = _next("wrong")
    assert _register(email, company).status_code == 201
    r = client.post("/api/auth/verify-otp", json={"email": email, "code": "000000"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid verification code. Please try again."

    email2, company2 = _next("expired")
    assert _register(email2, company2).status_code == 201
    con = db()
    try:
        user = con.execute("SELECT id FROM users WHERE email = ?", (email2,)).fetchone()
        con.execute("UPDATE otp_codes SET expires_at = '2000-01-01T00:00:00+00:00'"
                    " WHERE user_id = ?", (user["id"],))
        con.commit()
    finally:
        con.close()
    r = client.post("/api/auth/verify-otp",
                    json={"email": email2, "code": code_for(email2)})
    assert r.status_code == 400
    assert r.json()["detail"] == "Verification code expired. Please request a new code."


def test_resend_invalidates_previous_and_cooldown():
    email, company = _next("resend")
    assert _register(email, company).status_code == 201
    first = code_for(email)

    r = client.post("/api/auth/resend-otp", json={"email": email})
    assert r.status_code == 200
    assert r.json()["message"] == "Verification code sent to your email address."
    # The resend also went through Resend to the exact address.
    assert fake.last_to(email) is not None
    second = code_for(email)
    assert second != first  # completely new code

    # Old code is dead, new code works.
    assert client.post("/api/auth/verify-otp",
                       json={"email": email, "code": first}).status_code == 400
    assert client.post("/api/auth/verify-otp",
                       json={"email": email, "code": second}).status_code == 200

    # Immediate second resend for a fresh unverified account hits cooldown.
    email_b, company_b = _next("cool")
    assert _register(email_b, company_b).status_code == 201
    assert client.post("/api/auth/resend-otp", json={"email": email_b}).status_code == 200
    r = client.post("/api/auth/resend-otp", json={"email": email_b})
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    assert "Please wait" in r.json()["detail"]

    # Resend for unknown email is a generic success (no enumeration, no mail).
    n_before = len(fake.requests)
    r = client.post("/api/auth/resend-otp", json={"email": "ghost@email.test"})
    assert r.status_code == 200
    assert len(fake.requests) == n_before


def test_verify_rate_limit_and_limiter_unit():
    # Unit: sliding window blocks over-limit calls with retry_after.
    reset_all()
    for _ in range(3):
        ok, _ = allow("unit:key", 3, 60)
        assert ok
    ok, retry_after = allow("unit:key", 3, 60)
    assert not ok and retry_after >= 1
    reset_all()

    # Live: >10 wrong verify attempts within 10 min → 429.
    email, company = _next("brute")
    assert _register(email, company).status_code == 201
    statuses = [client.post("/api/auth/verify-otp",
                            json={"email": email, "code": "000000"}).status_code
                for _ in range(11)]
    assert 429 in statuses
    reset_all()  # do not pollute other tests (same process, shared limiter)


def test_resend_provider_failure_stays_unverified():
    # Resend 500 → safe 502, account stays unverified, code never leaks.
    email, company = _next("fail500")
    assert _register(email, company).status_code == 201
    fake.fail_with = (500, {"message": "internal error"})
    try:
        r = client.post("/api/auth/resend-otp", json={"email": email})
        assert r.status_code == 502
        assert "Could not send verification email" in r.json()["detail"]
        assert "dev_otp" not in r.text and '"otp"' not in r.text
    finally:
        fake.fail_with = None
    con = db()
    try:
        user = con.execute("SELECT is_active FROM users WHERE email = ?", (email,)).fetchone()
        assert user and not user["is_active"]
    finally:
        con.close()

    # Resend 429 (provider rate limit) → safe 502 as well (fresh email:
    # our own 60s resend cooldown must not mask the provider failure).
    email2, company2 = _next("fail429")
    assert _register(email2, company2).status_code == 201
    fake.fail_with = (429, {"message": "rate limited"})
    try:
        r = client.post("/api/auth/resend-otp", json={"email": email2})
        assert r.status_code == 502
    finally:
        fake.fail_with = None

    # Provider unreachable (bad base URL) → safe 502.
    email3, company3 = _next("faildns")
    assert _register(email3, company3).status_code == 201
    s = get_settings()
    old_url = s.RESEND_BASE_URL
    s.RESEND_BASE_URL = "http://127.0.0.1:1"
    try:
        r = client.post("/api/auth/resend-otp", json={"email": email3})
        assert r.status_code == 502
    finally:
        s.RESEND_BASE_URL = old_url


def test_register_fails_loudly_without_provider_outside_local():
    # Outside APP_ENV=local, unconfigured Resend must refuse loudly (502),
    # never fake delivery and never leak the code.
    s = get_settings()
    old_key, old_env = s.RESEND_API_KEY, s.APP_ENV
    s.RESEND_API_KEY, s.APP_ENV = "", "production"
    try:
        email, company = _next("noresend")
        r = _register(email, company)
        assert r.status_code == 502
        assert "dev_otp" not in r.text and '"otp"' not in r.text
    finally:
        s.RESEND_API_KEY, s.APP_ENV = old_key, old_env


def test_dev_outbox_flow_local_no_provider():
    # Documented local mechanism: code saved to a server-side outbox FILE.
    # The API response and UI still never carry the code.
    import tempfile
    from pathlib import Path
    s = get_settings()
    old_key, old_dir = s.RESEND_API_KEY, s.DEV_OUTBOX_DIR
    tmp = tempfile.mkdtemp(prefix="ix-outbox-")
    s.RESEND_API_KEY, s.DEV_OUTBOX_DIR = "", tmp
    try:
        email, company = _next("devbox")
        r = _register(email, company)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["dev_mode"] is True
        assert "Development mode" in body["message"]
        assert "dev_otp" not in r.text and '"otp"' not in r.text

        safe = re.sub(r"[^a-z0-9]", "_", email.lower())
        eml = Path(tmp) / f"{safe}.eml"
        assert eml.exists()
        codes = re.findall(r"(?m)^(\d{6})\r?$", eml.read_text(encoding="utf-8"))
        assert len(codes) == 1

        vr = client.post("/api/auth/verify-otp",
                         json={"email": email, "code": codes[0]})
        assert vr.status_code == 200
        assert vr.json()["message"] == "Email verified successfully. You can now log in."
        lr = client.post("/api/auth/login",
                         json={"email": email, "password": "Str0ngPass!"})
        assert lr.status_code == 200
    finally:
        s.RESEND_API_KEY, s.DEV_OUTBOX_DIR = old_key, old_dir


def test_password_length_rules():
    email, company = _next("pwlen")
    r = client.post("/api/auth/register", json={
        "company_name": company, "name": "T User",
        "email": email, "password": "x" * 73})
    assert r.status_code == 422  # bcrypt 72-byte limit enforced loudly


def test_phone_link_requires_firebase():
    email, company = _next("phone")
    assert _register(email, company).status_code == 201
    assert client.post("/api/auth/verify-otp",
                       json={"email": email, "code": code_for(email)}).status_code == 200
    lr = client.post("/api/auth/login",
                     json={"email": email, "password": "Str0ngPass!"})
    h = {"Authorization": f"Bearer {lr.json()['access_token']}"}
    # No Firebase project configured → honest 501, never a fake link.
    r = client.post("/api/auth/phone/link", json={"id_token": "fake"}, headers=h)
    assert r.status_code == 501
    r = client.post("/api/auth/phone/link", json={"id_token": "fake"})
    assert r.status_code == 401  # unauthenticated first
