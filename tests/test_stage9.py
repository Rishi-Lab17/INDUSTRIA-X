"""Stage 9 tests: case management, memory, lineage, audit, sovereignty, reports, security."""
from helpers import client, db

K = 0


def _next(prefix="s9"):
    global K
    K += 1
    return f"{prefix}{K}@s9.test", f"{prefix.capitalize()} Co {K}"


def _admin():
    email, company = _next()
    r = client.post("/api/auth/register", json={
        "company_name": company, "name": "Admin", "email": email,
        "password": "Str0ngPass!"})
    assert r.status_code == 201, r.text
    lr = client.post("/api/auth/login",
                      json={"email": email, "password": "Str0ngPass!"})
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}, email


def _engineer():
    email, company = _next()
    r = client.post("/api/auth/register", json={
        "company_name": company, "name": "Eng", "email": email,
        "password": "Str0ngPass!", "role": "ENGINEER"})
    assert r.status_code == 201, r.text
    lr = client.post("/api/auth/login",
                      json={"email": email, "password": "Str0ngPass!"})
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}, email


def _create_equipment(h):
    """Create an equipment item and return its ID."""
    r = client.post("/api/equipment", headers=h, json={
        "code": "P-001", "name": "Test Pump",
        "type": "Centrifugal", "criticality": "HIGH"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_investigation(h, eq_id):
    """Create an investigation (Stage 7 cases table) and return its ID."""
    r = client.post("/api/cases", headers=h, json={
        "equipment_id": eq_id, "title": "Test Investigation",
        "problem_statement": "Test problem", "category": "MECHANICAL",
        "severity": "HIGH"})
    assert r.status_code == 201, r.text
    inv = r.json()
    return inv["id"]


def _create_case(h, inv_id):
    """Create a case and return its dict."""
    r = client.post("/api/case", headers=h, json={
        "investigation_id": inv_id, "title": "Test Case",
        "summary": "Case summary", "priority": "MEDIUM",
        "severity": "INFORMATIONAL"})
    assert r.status_code == 201, r.text
    return r.json()


def test_case_crud():
    """Create case, list cases, get case."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    assert case["title"] == "Test Case"
    assert case["case_number"].startswith("INDX-")
    assert case["status"] == "OPEN"
    # List cases
    r = client.get("/api/case", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "cases" in data
    assert data["total"] >= 1
    # Get case
    r = client.get(f"/api/case/{case['id']}", headers=headers)
    assert r.status_code == 200
    gotten = r.json()
    assert gotten["title"] == "Test Case"
    assert gotten["id"] == case["id"]


def test_case_lifecycle():
    """Create case, close it, reopen, archive."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    cid = case["id"]
    # Close case
    r = client.post(f"/api/case/{cid}/close", json={
        "final_finding": "Root cause found",
        "root_cause": "Bearing failure",
        "failure_mode": "Fatigue",
        "corrective_action": "Replace bearing",
        "preventive_action": "Monitor vibration",
        "resolution_status": "RESOLVED",
        "resolution_evidence": "Photo evidence",
        "technician_conclusion": "Bearing was worn",
        "reviewer_conclusion": "Confirmed",
        "final_decision": "Resolved"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CLOSED"
    # Reopen case
    r = client.post(f"/api/case/{cid}/reopen",
                      json={"reason": "NEW_EVIDENCE"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REOPENED"
    # Archive case
    r = client.post(f"/api/case/{cid}/archive", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ARCHIVED"


def test_case_patch():
    """Update case fields."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    cid = case["id"]
    r = client.patch(f"/api/case/{cid}", json={
        "title": "Updated Title", "severity": "CRITICAL"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Updated Title"


def test_case_closure_readiness():
    """Close requires valid resolution_status."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    cid = case["id"]
    r = client.post(f"/api/case/{cid}/close", json={
        "final_finding": "Test", "root_cause": "Bearing",
        "failure_mode": "Fatigue", "corrective_action": "Replace",
        "preventive_action": "Monitor",
        "resolution_status": "INVALID_STATUS",
        "resolution_evidence": "Test"}, headers=headers)
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"


def test_case_memory():
    """Create case memory (linked to a case) and feedback."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    # Create memory linked to the case
    r = client.post("/api/case/memory", headers=headers, json={
        "case_id": case["id"],
        "equipment_type": "Motor", "component": "Bearing",
        "symptoms": "Vibration", "failure_mode": "Fatigue",
        "root_cause": "Lubrication failure",
        "corrective_action": "Re-lubricate",
        "preventive_action": "Schedule maintenance",
        "reliability": "VERIFIED"})
    assert r.status_code == 201, r.text
    mem = r.json()
    assert mem["equipment_type"] == "Motor"
    assert mem["reliability"] == "VERIFIED"
    assert mem["case_id"] == case["id"]
    # Missing case_id must be rejected with a clear error (memory always links to a case)
    r = client.post("/api/case/memory", headers=headers, json={"failure_mode": "X"})
    assert r.status_code == 422, r.text
    # Add feedback
    r = client.post(f"/api/case/memory/{mem['id']}/feedback",
                      headers=headers, json={"feedback": "USEFUL", "reason": "Very helpful"})
    assert r.status_code == 201, r.text


def test_case_lineage():
    """Add lineage nodes and edges."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    cid = case["id"]
    # Add nodes
    r = client.post(f"/api/case/{cid}/lineage", headers=headers, json={
        "node_type": "EVIDENCE", "label": "Root Evidence",
        "node_id": "node-001"})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/case/{cid}/lineage", headers=headers, json={
        "node_type": "EVIDENCE", "label": "Derived Evidence",
        "node_id": "node-002"})
    assert r.status_code == 201, r.text
    # Add edge
    r = client.post(f"/api/case/{cid}/lineage/edge", headers=headers, json={
        "from_node": "node-001", "to_node": "node-002",
        "relation": "RELATED_TO"})
    assert r.status_code == 201, r.text
    # Get lineage
    r = client.get(f"/api/case/{cid}/lineage", headers=headers)
    assert r.status_code == 200


def test_case_timeline():
    """Case timeline returns events."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    cid = case["id"]
    r = client.get(f"/api/case/{cid}/timeline", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "events" in data


def test_case_integrity():
    """Case integrity check returns status."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    cid = case["id"]
    r = client.get(f"/api/case/{cid}/integrity", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] in ("PASS", "WARNING", "ERROR")


def test_sovereignty_check():
    """Sovereignty health returns status."""
    headers, email = _admin()
    r = client.get("/api/case/sovereignty", headers=headers)
    assert r.status_code in (200, 422), f"Got {r.status_code}: {r.text}"
    data = r.json()
    assert "status" in data
    assert "checks" in data
    assert "config" in data


def test_sovereignty_update():
    """Update sovereignty configuration."""
    headers, email = _admin()
    r = client.put("/api/case/sovereignty", headers=headers, json={
        "data_residency": "EU",
        "external_ai_policy": "BLOCKED",
        "document_storage": "LOCAL"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["data_residency"] == "EU"


def test_audit_center():
    """Audit center returns events."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    # Check audit
    r = client.get("/api/case/audit", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "events" in data
    assert "total" in data


def test_case_dashboard():
    """Dashboard returns stats."""
    headers, email = _admin()
    r = client.get("/api/case/dashboard", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "total_cases" in data
    assert "by_status" in data


def test_case_safety_center():
    """Safety center returns active reviews."""
    headers, email = _admin()
    r = client.get("/api/case/safety-center", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "active_reviews" in data


def test_case_idor_protection():
    """User from company A cannot access case from company B."""
    # Admin creates company A case
    headers_a, email_a = _admin()
    # Create second company admin
    email_b, company_b = _next("idor2")
    r = client.post("/api/auth/register", json={
        "company_name": company_b, "name": "Admin B",
        "email": email_b, "password": "Str0ngPass!"})
    assert r.status_code == 201, r.text
    lr = client.post("/api/auth/login",
                      json={"email": email_b, "password": "Str0ngPass!"})
    assert lr.status_code == 200
    headers_b = {"Authorization": f"Bearer {lr.json()['access_token']}"}
    # Create case in company A
    eq_id = _create_equipment(headers_a)
    inv_id = _create_investigation(headers_a, eq_id)
    case = _create_case(headers_a, inv_id)
    cid = case["id"]
    # User B tries to access case A
    r = client.get(f"/api/case/{cid}", headers=headers_b)
    assert r.status_code == 404, f"Expected 404, got {r.status_code}"


def test_case_duplicate_node():
    """Adding duplicate lineage node returns 409."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    cid = case["id"]
    # Add node
    r = client.post(f"/api/case/{cid}/lineage", headers=headers, json={
        "node_id": "dup-node", "node_type": "EVIDENCE",
        "label": "Dup"})
    assert r.status_code == 201
    # Try duplicate
    r = client.post(f"/api/case/{cid}/lineage", headers=headers, json={
        "node_id": "dup-node", "node_type": "EVIDENCE",
        "label": "Dup2"})
    assert r.status_code == 409, f"Expected 409, got {r.status_code}"


def test_case_memory_feedback_not_found():
    """Feedback on nonexistent memory returns 404."""
    headers, email = _admin()
    r = client.post("/api/case/memory/999999/feedback",
                      headers=headers, json={"feedback": "USEFUL"})
    assert r.status_code == 404, f"Expected 404, got {r.status_code}"


def test_case_reopen_not_closed():
    """Reopening a non-closed case returns 422."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    cid = case["id"]
    r = client.post(f"/api/case/{cid}/reopen",
                      headers=headers, json={"reason": "NEW_EVIDENCE"})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"


def test_case_already_closed():
    """Closing an already-closed case returns 422."""
    headers, email = _admin()
    eq_id = _create_equipment(headers)
    inv_id = _create_investigation(headers, eq_id)
    case = _create_case(headers, inv_id)
    cid = case["id"]
    # Close
    r = client.post(f"/api/case/{cid}/close", headers=headers, json={
        "final_finding": "Test", "root_cause": "Test",
        "failure_mode": "Test", "corrective_action": "Test",
        "preventive_action": "Test", "resolution_status": "RESOLVED",
        "resolution_evidence": "Test",
        "technician_conclusion": "Test",
        "reviewer_conclusion": "Test", "final_decision": "Test"})
    assert r.status_code == 200
    # Close again
    r = client.post(f"/api/case/{cid}/close", headers=headers, json={
        "final_finding": "Test", "root_cause": "Test",
        "failure_mode": "Test", "corrective_action": "Test",
        "preventive_action": "Test", "resolution_status": "RESOLVED",
        "resolution_evidence": "Test",
        "technician_conclusion": "Test",
        "reviewer_conclusion": "Test", "final_decision": "Test"})
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"
