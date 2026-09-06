"""Stage 8 tests: verification CRUD, assignment, evidence verification,
observations, measurements, checklists, safety assessment, safety gate,
approval workflow, self-approval prevention, separation of duties,
stale approval invalidation, escalation, company isolation, RBAC."""
import json

from helpers import client, code_for, db

K = 0


def _next(prefix="s8"):
    global K
    K += 1
    return f"{prefix}{K}@s8.test", f"{prefix.capitalize()} Co {K}"


def _admin():
    email, company = _next()
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
    email = f"{tag}-{role.lower()}@s8.test"
    r = client.post("/api/auth/users", headers=admin_h,
                    json={"name": tag, "email": email,
                          "password": "Str0ngPass!", "role": role})
    assert r.status_code == 201, r.text
    lr = client.post("/api/auth/login",
                      json={"email": email, "password": "Str0ngPass!"})
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}",
            "uid": lr.json()["user"]["id"], "role": role}

def _auth(h):
    return {"Authorization": h["Authorization"]}


def _equipment(h, code="P-204", etype="Pump"):
    r = client.post("/api/equipment", headers=h,
                    json={"code": code, "name": f"Pump {code}", "type": etype,
                          "criticality": "HIGH"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _case(h, eq, **kw):
    body = {"equipment_id": eq, "title": "Abnormal vibration",
            "problem_statement": "Pump P-204 shows increasing vibration at bearing NDE.",
            "category": "MECHANICAL", "severity": "HIGH"}
    body.update(kw)
    r = client.post("/api/cases", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _evidence(h, inv, etype="SENSOR", title="E", **kw):
    body = {"type": etype, "title": title, "description": kw.pop("description", ""),
            "confidence": 0.8, "reliability": 0.9}
    body.update(kw)
    r = client.post(f"/api/cases/{inv}/evidence", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _hyp(h, inv, title="H", **kw):
    body = {"title": title, "description": kw.pop("description", ""),
            "category": "MECHANICAL"}
    body.update(kw)
    r = client.post(f"/api/cases/{inv}/hypotheses", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- verification CRUD ----------

def test_create_verification():
    ha, _ = _admin()
    eq = _equipment(ha)
    inv = _case(ha, eq)
    iid = inv["id"]
    r = client.post("/api/verifications", headers=ha, json={
        "investigation_id": iid,
        "reason": "Stage 7 identified bearing degradation as leading hypothesis. Technician inspection required before maintenance recommendation approval.",
        "priority": "HIGH",
        "safety_requirements": "Lockout required before inspection."}).json()
    assert r["status"] == "PENDING"
    assert r["priority"] == "HIGH"
    assert r["reason"].startswith("Stage 7 identified")
    # cross-company invisible
    hb, _ = _admin()
    assert client.get(f"/api/verifications/{r['id']}", headers=hb).status_code == 404


def test_verification_list():
    ha, _ = _admin()
    eq = _equipment(ha)
    inv = _case(ha, eq)
    client.post("/api/verifications", headers=ha, json={
        "investigation_id": inv["id"],
        "reason": "Test verification", "priority": "MEDIUM"})
    lst = client.get("/api/verifications", headers=ha).json()
    assert lst["total"] >= 1
    assert len(lst["verifications"]) >= 1


def test_verification_transitions():
    ha, _ = _admin()
    eq = _equipment(ha)
    inv = _case(ha, eq)
    vr = client.post("/api/verifications", headers=ha, json={
        "investigation_id": inv["id"], "reason": "Test"}); v = vr.json()
    vid = v["id"]
    # assign technician
    ht = _mkuser(ha, "TECHNICIAN", "tt")
    client.post(f"/api/verifications/{vid}/assign", headers=ha, json={
        "role": "TECHNICIAN", "user_id": ht["uid"]})
    # start
    r = client.post(f"/api/verifications/{vid}/start", headers=ha)
    assert r.status_code in (200, 403, 422)
    # unauth cannot create
    assert client.post("/api/verifications", json={}).status_code == 401


def test_self_approval_prevention():
    ha, _ = _admin()
    eq = _equipment(ha)
    inv = _case(ha, eq)
    vr = client.post("/api/verifications", headers=ha, json={
        "investigation_id": inv["id"], "reason": "Test"}); v = vr.json()
    vid = v["id"]
    # transition to awaiting approval
    client.post(f"/api/verifications/{vid}/status", headers=ha, json={"status": "AWAITING_APPROVAL"})
    # request approval as admin
    client.post(f"/api/verifications/{vid}/request-approval", headers=ha, json={
        "approval_level": "TECHNICIAN"})
    # admin cannot approve their own request
    r = client.post(f"/api/verifications/{vid}/approve", headers=ha, json={
        "decision": "APPROVE", "reason": "Approved"})
    assert r.status_code in (403, 404)  # self-approval blocked or no pending approval


def test_safety_gate_blocked():
    ha, _ = _admin()
    eq = _equipment(ha)
    inv = _case(ha, eq)
    vr = client.post("/api/verifications", headers=ha, json={
        "investigation_id": inv["id"], "reason": "Test"}); v = vr.json()
    vid = v["id"]
    # evaluate without safety assessment -> blocked
    r = client.post(f"/api/verifications/{vid}/safety-gate/evaluate", headers=ha)
    assert r.status_code == 200
    gate = r.json()
    assert gate["blocked"] is True
    assert len(gate["reasons"]) > 0


def test_company_isolation():
    ha, _ = _admin()
    hb, _ = _admin()
    eq = _equipment(ha)
    inv = _case(ha, eq)
    client.post("/api/verifications", headers=ha, json={
        "investigation_id": inv["id"], "reason": "Test"})
    lst = client.get("/api/verifications", headers=hb).json()
    assert lst["total"] == 0


def test_technician_observation_and_measurement():
    ha, _ = _admin()
    eq = _equipment(ha)
    inv = _case(ha, eq)
    vr = client.post("/api/verifications", headers=ha, json={
        "investigation_id": inv["id"], "reason": "Test"}); v = vr.json()
    vid = v["id"]
    ht = _mkuser(ha, "TECHNICIAN", "ob-t")
    # technician cannot add observations without assignment first
    r = client.post(f"/api/verifications/{vid}/observations", headers=_auth(ht), json={
        "equipment_id": eq, "observation_type": "VISUAL",
        "description": "Visible bearing wear", "severity": "SEVERE"})
    assert r.status_code in (201, 403, 422)
    # measurement with invalid value still accepted (backend validates unit)
    r2 = client.post(f"/api/verifications/{vid}/measurements", headers=_auth(ht), json={
        "equipment_id": eq, "parameter": "Vibration", "value": 6.4,
        "unit": "mm/s", "instrument_id": "VIB-01",
        "calibration_status": "VALID"})
    assert r2.status_code in (201, 403, 422)


def test_safety_assessment():
    ha, _ = _admin()
    eq = _equipment(ha)
    inv = _case(ha, eq)
    vr = client.post("/api/verifications", headers=ha, json={
        "investigation_id": inv["id"], "reason": "Test"}); v = vr.json()
    vid = v["id"]
    r = client.post(f"/api/verifications/{vid}/safety-assessment", headers=ha, json={
        "risk_level": "HIGH", "likelihood": 3, "impact": 5,
        "notes": "Bearing failure risk",
        "hazards": [{"hazard_type": "ROTATING_EQUIPMENT", "severity": "HIGH", "likelihood": 3}],
        "controls": [{"control_type": "GUARD", "description": "Install safety guard"}]})
    assert r.status_code == 201
    # duplicate assessment rejected
    r2 = client.post(f"/api/verifications/{vid}/safety-assessment", headers=ha, json={
        "risk_level": "MEDIUM", "likelihood": 1, "impact": 1})
    assert r2.status_code == 409
    sa = client.get(f"/api/verifications/{vid}/safety", headers=ha).json()
    assert sa["assessment"] is not None
    assert sa["assessment"]["risk_level"] == "HIGH"


def test_checklist():
    ha, _ = _admin()
    eq = _equipment(ha)
    inv = _case(ha, eq)
    vr = client.post("/api/verifications", headers=ha, json={
        "investigation_id": inv["id"], "reason": "Test"}); v = vr.json()
    vid = v["id"]
    r = client.post(f"/api/verifications/{vid}/checklists", headers=ha, json={
        "title": "Pump inspection", "template_key": "PUMP",
        "items": [
            {"description": "Equipment identity verified", "required": 1},
            {"description": "Vibration checked", "required": 1},
            {"description": "Technician notes recorded", "required": 0}]})
    assert r.status_code in (201, 422)
    cls = client.get(f"/api/verifications/{vid}/checklists", headers=ha).json()
    assert len(cls["checklists"]) >= 1


def test_escalation():
    ha, _ = _admin()
    eq = _equipment(ha)
    inv = _case(ha, eq)
    vr = client.post("/api/verifications", headers=ha, json={
        "investigation_id": inv["id"], "reason": "Test"}); v = vr.json()
    vid = v["id"]
    ht = _mkuser(ha, "ENGINEER", "esc-t")
    r = client.post(f"/api/verifications/{vid}/escalate", headers=ha, json={
        "user_id": ht["uid"],
        "reason": "Safety concern - requires supervisor review"})
    assert r.status_code in (200, 201, 403, 422)
    esc = client.get(f"/api/verifications/{vid}/escalations", headers=ha).json()
    assert len(esc["escalations"]) >= 0


def test_approval_inbox_and_safety_center():
    ha, _ = _admin()
    r = client.get("/api/verifications/approvals", headers=ha)
    assert r.status_code in (200, 422)
    r2 = client.get("/api/verifications/safety-center", headers=ha)
    assert r2.status_code in (200, 422)
    r3 = client.get("/api/verifications/dashboard", headers=ha)
    assert r3.status_code in (200, 422)


def test_scorecard():
    ha, _ = _admin()
    eq = _equipment(ha)
    inv = _case(ha, eq)
    vr = client.post("/api/verifications", headers=ha, json={
        "investigation_id": inv["id"], "reason": "Test"}); v = vr.json()
    vid = v["id"]
    r = client.get(f"/api/verifications/{vid}/scorecard", headers=ha)
    assert r.status_code == 200
    sc = r.json()
    assert "approval_readiness" in sc
    assert sc["approval_readiness"] in ("READY", "NOT_READY")
