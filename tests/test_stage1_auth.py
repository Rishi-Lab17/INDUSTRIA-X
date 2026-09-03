"""Stage 1 tests: auth, OTP-via-email, sessions, RBAC, tenant isolation, system probes."""
from helpers import client, code_for


def _register(company="Acme Industries", name="A Admin", email="admin@acme.test",
              password="Str0ngPass!"):
    return client.post("/api/auth/register", json={
        "company_name": company, "name": name, "email": email, "password": password})


def _login(email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _auth(email, password):
    r = _login(email, password)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_register_verify_login_me_logout():
    r = _register()
    assert r.status_code == 201, r.text
    assert r.json()["message"] == "Verification code sent to your email address."
    assert "otp" not in r.text.lower() and "dev_otp" not in r.text
    otp = code_for("admin@acme.test")  # server-side sink inbox, never the API

    # login before verification must be rejected
    assert _login("admin@acme.test", "Str0ngPass!").status_code == 403

    # wrong OTP rejected
    assert client.post("/api/auth/verify-otp",
                       json={"email": "admin@acme.test", "code": "000000"}).status_code == 400

    # correct OTP verifies
    assert client.post("/api/auth/verify-otp",
                       json={"email": "admin@acme.test", "code": otp}).status_code == 200

    h = _auth("admin@acme.test", "Str0ngPass!")
    me = client.get("/api/auth/me", headers=h)
    assert me.status_code == 200
    assert me.json()["company"]["name"] == "Acme Industries"
    assert me.json()["user"]["role"] == "COMPANY_ADMIN"

    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401  # revoked


def test_invalid_login_and_duplicates():
    assert _login("admin@acme.test", "WrongPass123").status_code == 401
    assert _login("nobody@acme.test", "Whatever123").status_code == 401
    # duplicate email / company
    assert _register().status_code == 409  # admin@acme.test already exists
    r = _register(company="Acme Industries", email="other@acme.test")
    assert r.status_code == 409


def test_validation():
    r = _register(company="V", name="V", email="not-an-email")
    assert r.status_code == 422
    r = _register(company="V2", name="V2", email="v2@v.test", password="short")
    assert r.status_code == 422


def test_rbac_and_tenant_isolation():
    ha = _auth("admin@acme.test", "Str0ngPass!")

    # admin creates engineer + technician in ITS company
    for name, email, role in [("E Eng", "eng@acme.test", "ENGINEER"),
                              ("T Tech", "tech@acme.test", "TECHNICIAN")]:
        r = client.post("/api/auth/users", headers=ha,
                        json={"name": name, "email": email,
                              "password": "Str0ngPass!", "role": role})
        assert r.status_code == 201, r.text

    he = _auth("eng@acme.test", "Str0ngPass!")
    ht = _auth("tech@acme.test", "Str0ngPass!")

    # engineer may list, may NOT create
    assert client.get("/api/auth/users", headers=he).status_code == 200
    r = client.post("/api/auth/users", headers=he,
                    json={"name": "X", "email": "x@acme.test",
                          "password": "Str0ngPass!", "role": "ENGINEER"})
    assert r.status_code == 403
    # technician may do neither
    assert client.get("/api/auth/users", headers=ht).status_code == 403

    # second company
    r = _register(company="Globex Corp", name="G Admin",
                  email="admin@globex.test", password="Str0ngPass!")
    assert r.status_code == 201
    client.post("/api/auth/verify-otp",
                json={"email": "admin@globex.test",
                      "code": code_for("admin@globex.test")})
    hg = _auth("admin@globex.test", "Str0ngPass!")

    users_g = client.get("/api/auth/users", headers=hg).json()["users"]
    emails_g = {u["email"] for u in users_g}
    assert "admin@globex.test" in emails_g
    assert "admin@acme.test" not in emails_g  # no cross-company leak

    users_a = client.get("/api/auth/users", headers=ha).json()["users"]
    assert "admin@globex.test" not in {u["email"] for u in users_a}

    # audit is company-scoped too
    audit_g = client.get("/api/auth/audit", headers=hg).json()["events"]
    audit_a = client.get("/api/auth/audit", headers=ha).json()["events"]
    assert len(audit_a) > 0 and len(audit_g) > 0


def test_system_endpoints_are_live():
    h = client.get("/api/health")
    assert h.status_code == 200
    svcs = h.json()["services"]
    for k in ["backend", "database", "storage", "kimi", "rag", "vector_db"]:
        assert k in svcs, k
    assert svcs["database"]["status"] == "ONLINE"  # real probe
    # Kimi honestly OFFLINE on this machine (no local K3 server)
    assert svcs["kimi"]["status"] == "OFFLINE"

    s = client.get("/api/sovereignty").json()
    assert s["external_ai"] == "BLOCKED" and s["external_fallback"] == "DISABLED"
    assert s["ai_active_model"] == "none"
