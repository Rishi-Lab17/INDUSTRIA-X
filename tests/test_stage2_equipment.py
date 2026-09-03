"""Stage 2 tests: company workspace, equipment CRUD, QR, history, RBAC matrix,
cross-company isolation, validation, audit."""
from helpers import client, code_for

M = 0


def _next(prefix="s2"):
    global M
    M += 1
    return f"{prefix}{M}@s2.test", f"{prefix.capitalize()} Industries {M}"


def _admin(email=None, company=None):
    email = email or _next()[0]
    company = company or f"Co-{email}"
    r = client.post("/api/auth/register", json={
        "company_name": company, "name": "Admin", "email": email,
        "password": "Str0ngPass!"})
    assert r.status_code == 201, r.text
    assert client.post("/api/auth/verify-otp",
                       json={"email": email, "code": code_for(email)}).status_code == 200
    lr = client.post("/api/auth/login",
                     json={"email": email, "password": "Str0ngPass!"})
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}, email


def _mkuser(admin_h, role, tag):
    email = f"{tag}-{role.lower()}@s2.test"
    r = client.post("/api/auth/users", headers=admin_h,
                    json={"name": tag, "email": email,
                          "password": "Str0ngPass!", "role": role})
    assert r.status_code == 201, r.text
    lr = client.post("/api/auth/login",
                     json={"email": email, "password": "Str0ngPass!"})
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


PUMP = {"code": "P-204", "name": "Feed Pump P-204", "type": "Centrifugal Pump",
        "manufacturer": "KSB", "model": "Etanorm 100", "serial_number": "SN-8812",
        "location": "Hall A", "criticality": "HIGH", "status": "OPERATIONAL",
        "installed_at": "2021-03-15", "commissioned_at": "2021-04-01",
        "metadata": {"duty": "continuous"}}


def _setup_roles(tag="t"):
    ha, _ = _admin()
    he = _mkuser(ha, "ENGINEER", f"{tag}e")
    ht = _mkuser(ha, "TECHNICIAN", f"{tag}t")
    return ha, he, ht


def test_company_profile_and_settings():
    ha, he, ht = _setup_roles("c")
    r = client.get("/api/company", headers=ha)
    assert r.status_code == 200
    assert r.json()["stats"] == {"members": 3, "equipment": 0}
    assert len(r.json()["members"]) == 3

    # engineer/technician may read, only admin may write
    assert client.get("/api/company", headers=he).status_code == 200
    assert client.get("/api/company", headers=ht).status_code == 200
    assert client.patch("/api/company", headers=he,
                        json={"settings": {"x": 1}}).status_code == 403
    assert client.patch("/api/company", headers=ht,
                        json={"settings": {"x": 1}}).status_code == 403
    r = client.patch("/api/company", headers=ha,
                     json={"settings": {"timezone": "Asia/Kolkata"}})
    assert r.status_code == 200
    assert r.json()["company"]["settings"] == {"timezone": "Asia/Kolkata"}
    assert client.get("/api/company").status_code == 401


def test_equipment_crud_admin():
    ha, _, _ = _setup_roles("e")
    r = client.post("/api/equipment", headers=ha, json=PUMP)
    assert r.status_code == 201, r.text
    eq = r.json()
    assert eq["code"] == "P-204" and eq["criticality"] == "HIGH"
    assert eq["metadata"] == {"duty": "continuous"}
    eid = eq["id"]

    assert client.get(f"/api/equipment/{eid}", headers=ha).json()["name"] \
        == "Feed Pump P-204"
    assert any(e["code"] == "P-204"
               for e in client.get("/api/equipment", headers=ha).json()["equipment"])

    r = client.patch(f"/api/equipment/{eid}", headers=ha,
                     json={"status": "DEGRADED", "location": "Hall B"})
    assert r.status_code == 200 and r.json()["status"] == "DEGRADED"

    assert client.delete(f"/api/equipment/{eid}", headers=ha).status_code == 200
    assert client.get(f"/api/equipment/{eid}", headers=ha).status_code == 404
    assert client.get("/api/equipment", headers=ha).json()["equipment"] == []

    # history survives deactivation: created → updated → deactivated
    hist = client.get(f"/api/equipment/{eid}/history",
                      headers=ha).json()["history"]
    assert [h["action"] for h in hist] == ["equipment_deactivated",
                                          "equipment_updated",
                                          "equipment_created"]


def test_rbac_matrix():
    ha, he, ht = _setup_roles("r")
    body = dict(PUMP, code="R-1")

    assert client.post("/api/equipment", headers=ht, json=body).status_code == 403
    r = client.post("/api/equipment", headers=he, json=body)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]

    assert client.patch(f"/api/equipment/{eid}", headers=ht,
                        json={"location": "X"}).status_code == 403
    assert client.patch(f"/api/equipment/{eid}", headers=he,
                        json={"location": "Hall C"}).status_code == 200
    assert client.delete(f"/api/equipment/{eid}",
                         headers=he).status_code == 403
    assert client.delete(f"/api/equipment/{eid}",
                         headers=ht).status_code == 403

    # read + QR for every role; history only for admin/engineer
    for h in (ha, he, ht):
        assert client.get("/api/equipment", headers=h).status_code == 200
        assert client.get(f"/api/equipment/{eid}", headers=h).status_code == 200
        assert client.get(f"/api/equipment/{eid}/qr", headers=h).status_code == 200
    assert client.get(f"/api/equipment/{eid}/history", headers=ha).status_code == 200
    assert client.get(f"/api/equipment/{eid}/history", headers=he).status_code == 200
    assert client.get(f"/api/equipment/{eid}/history", headers=ht).status_code == 403

    assert client.delete(f"/api/equipment/{eid}", headers=ha).status_code == 200


def test_cross_company_isolation():
    ha, _ = _admin()
    hb, _ = _admin()
    eid = client.post("/api/equipment", headers=ha, json=PUMP).json()["id"]

    # B sees nothing of A: 404 everywhere (no existence oracle), and B's own
    # list is empty. Same code is reusable in B (per-company uniqueness).
    assert client.get(f"/api/equipment/{eid}", headers=hb).status_code == 404
    assert client.patch(f"/api/equipment/{eid}", headers=hb,
                        json={"location": "X"}).status_code == 404
    assert client.delete(f"/api/equipment/{eid}", headers=hb).status_code == 404
    assert client.get(f"/api/equipment/{eid}/qr", headers=hb).status_code == 404
    assert client.get(f"/api/equipment/{eid}/history", headers=hb).status_code == 404
    assert client.get("/api/equipment", headers=hb).json()["equipment"] == []
    r = client.post("/api/equipment", headers=hb, json=PUMP)
    assert r.status_code == 201, r.text
    assert r.json()["id"] != eid

    # A untouched by B's actions.
    assert client.get(f"/api/equipment/{eid}", headers=ha).status_code == 200


def test_validation_and_duplicates():
    ha, _, _ = _setup_roles("v")
    assert client.post("/api/equipment", headers=ha, json=PUMP).status_code == 201
    assert client.post("/api/equipment", headers=ha, json=PUMP).status_code == 409

    bad_code = dict(PUMP, code="bad code!")
    assert client.post("/api/equipment", headers=ha, json=bad_code).status_code == 422
    bad_crit = dict(PUMP, code="V-2", criticality="EXTREME")
    assert client.post("/api/equipment", headers=ha, json=bad_crit).status_code == 422
    bad_date = dict(PUMP, code="V-3", installed_at="15-03-2021")
    assert client.post("/api/equipment", headers=ha, json=bad_date).status_code == 422
    no_name = dict(PUMP, code="V-4", name="  ")
    assert client.post("/api/equipment", headers=ha, json=no_name).status_code == 422
    assert client.get("/api/equipment?status=BROKEN", headers=ha).status_code == 422


def test_qr_generation():
    ha, _, _ = _setup_roles("q")
    eid = client.post("/api/equipment", headers=ha, json=PUMP).json()["id"]
    r = client.get(f"/api/equipment/{eid}/qr", headers=ha)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n" and len(r.content) > 500
    import json as _json
    payload = _json.loads(r.headers["x-qr-payload"])
    assert payload["app"] == "INDUSTRIA-X" and payload["code"] == "P-204"
    assert payload["equipment_id"] == eid
    assert client.get(f"/api/equipment/{eid}/qr").status_code == 401


def test_unauthenticated_blocked():
    for method, path in [("get", "/api/company"), ("patch", "/api/company"),
                         ("get", "/api/equipment"),
                         ("post", "/api/equipment"),
                         ("get", "/api/equipment/1"),
                         ("get", "/api/equipment/1/qr")]:
        r = client.request(method, path,
                           json={"settings": {}} if method == "patch" else None)
        assert r.status_code in (401, 422), (method, path, r.status_code)
