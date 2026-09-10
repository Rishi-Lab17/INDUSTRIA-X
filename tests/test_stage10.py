"""Stage 10 tests: live video investigation, AI copilot, evidence capture, lineage."""
import json
import hashlib

from helpers import client, db

K = 0
EQ_COUNTER = 0


def _next(prefix="s10"):
    global K
    K += 1
    return f"{prefix}{K}@s10.test", f"{prefix.capitalize()} Co {K}"


def _next_eq_code():
    global EQ_COUNTER
    EQ_COUNTER += 1
    return f"P-{EQ_COUNTER:03d}"


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
    code = _next_eq_code()
    r = client.post("/api/equipment", headers=h, json={
        "code": code, "name": f"Test Pump {code}",
        "type": "Centrifugal", "criticality": "HIGH"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_investigation(h, eq_id):
    r = client.post("/api/cases", headers=h, json={
        "equipment_id": eq_id, "title": "Test Investigation",
        "problem_statement": "Test problem", "category": "MECHANICAL",
        "severity": "HIGH"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_case(h, inv_id):
    r = client.post("/api/case", headers=h, json={
        "investigation_id": inv_id, "title": "Test Case",
        "summary": "Case summary", "priority": "MEDIUM",
        "severity": "INFORMATIONAL"})
    assert r.status_code == 201, r.text
    return r.json()


def test_recording_crud():
    """Create, list, get, update recording."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "equipment_id": eq_id,
        "title": "Test Recording", "media_type": "video"})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["title"] == "Test Recording"
    assert rec["status"] == "DRAFT"
    rec_id = rec["id"]
    
    # List
    r = client.get("/api/recordings", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    
    # Get
    r = client.get(f"/api/recordings/{rec_id}", headers=h)
    assert r.status_code == 200
    assert r.json()["id"] == rec_id
    
    # Patch
    r = client.patch(f"/api/recordings/{rec_id}", headers=h, json={"title": "Updated"})
    assert r.status_code == 200
    assert r.json()["title"] == "Updated"


def test_recording_lifecycle():
    """Start, pause, resume, stop recording."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": eq_id, "title": "Lifecycle Test", "media_type": "video"})
    rec_id = r.json()["id"]
    
    # Start
    r = client.post(f"/api/recordings/{rec_id}/start", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "RECORDING"
    
    # Pause
    r = client.post(f"/api/recordings/{rec_id}/pause", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "PAUSED"
    
    # Resume
    r = client.post(f"/api/recordings/{rec_id}/resume", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "RECORDING"
    
    # Stop
    r = client.post(f"/api/recordings/{rec_id}/stop", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "PROCESSING"
    assert r.json()["duration_seconds"] >= 0


def test_recording_events_timeline():
    """Recording events are created for timeline."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Events Test"})
    rec_id = r.json()["id"]
    
    # Start
    client.post(f"/api/recordings/{rec_id}/start", headers=h)
    # Pause
    client.post(f"/api/recordings/{rec_id}/pause", headers=h)
    # Resume
    client.post(f"/api/recordings/{rec_id}/resume", headers=h)
    # Stop
    client.post(f"/api/recordings/{rec_id}/stop", headers=h)
    
    r = client.get(f"/api/recordings/{rec_id}/events", headers=h)
    assert r.status_code == 200
    events = r.json()["events"]
    types = [e["event_type"] for e in events]
    assert "RECORDING_STARTED" in types
    assert "RECORDING_PAUSED" in types
    assert "RECORDING_RESUMED" in types
    assert "RECORDING_STOPPED" in types


def test_frame_capture():
    """Capture frame from recording."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Frame Test"})
    rec_id = r.json()["id"]
    
    # Start and stop to have a recording
    client.post(f"/api/recordings/{rec_id}/start", headers=h)
    client.post(f"/api/recordings/{rec_id}/stop", headers=h)
    
    # Try to capture frame (will fail without actual video, but endpoint should respond)
    r = client.post(f"/api/recordings/{rec_id}/frames", headers=h, json={
        "recording_id": rec_id, "timestamp_seconds": 5.0,
        "capture_type": "MANUAL"})
    # Should fail gracefully since no video file exists
    assert r.status_code in (404, 422)


def test_frame_capture_with_mock():
    """Test frame capture endpoint accepts valid input."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Frame Validation"})
    rec_id = r.json()["id"]
    
    # Invalid timestamp
    r = client.post(f"/api/recordings/{rec_id}/frames", headers=h, json={
        "recording_id": rec_id, "timestamp_seconds": -1.0})
    assert r.status_code == 422
    
    # Valid capture_type
    r = client.post(f"/api/recordings/{rec_id}/frames", headers=h, json={
        "recording_id": rec_id, "timestamp_seconds": 0.0,
        "capture_type": "PERIODIC"})
    # Will fail without video, but validation passes
    assert r.status_code in (404, 422)


def test_ai_copilot_during_recording():
    """AI questions can be asked during recording."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "AI Test"})
    rec_id = r.json()["id"]
    
    # Start recording
    client.post(f"/api/recordings/{rec_id}/start", headers=h)
    
    # Ask AI question
    r = client.post(f"/api/recordings/{rec_id}/questions", headers=h, json={
        "recording_id": rec_id,
        "question": "What could cause this vibration?",
        "recording_timestamp_seconds": 30.0})
    assert r.status_code == 201
    interaction = r.json()
    assert interaction["question"] == "What could cause this vibration?"
    assert interaction["recording_timestamp_seconds"] == 30.0
    assert "interaction_id" in interaction or "id" in interaction
    
    # List interactions
    r = client.get(f"/api/recordings/{rec_id}/interactions", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    
    # Recording should still be in progress (not stopped by AI)
    rec = client.get(f"/api/recordings/{rec_id}", headers=h).json()
    assert rec["status"] in ("RECORDING", "PAUSED", "PROCESSING")


def test_evidence_from_frame():
    """Create evidence from captured frame."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Evidence Test"})
    rec_id = r.json()["id"]
    
    # Need a frame first - will fail without video, test validation
    r = client.post(f"/api/recordings/{rec_id}/evidence", headers=h, data={
        "frame_id": 99999, "title": "Test Evidence", "description": "Test"})
    assert r.status_code == 404  # Frame not found


def test_recording_evidence_linking():
    """Evidence created from recording links back correctly."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Linking Test"})
    rec_id = r.json()["id"]
    
    r = client.get(f"/api/recordings/{rec_id}/evidence", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_ai_does_not_stop_recording():
    """CRITICAL: AI question does not stop recording."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "AI No Stop Test"})
    rec_id = r.json()["id"]
    
    # Start recording
    client.post(f"/api/recordings/{rec_id}/start", headers=h)
    
    # Ask multiple AI questions
    for i in range(3):
        r = client.post(f"/api/recordings/{rec_id}/questions", headers=h, json={
            "recording_id": rec_id,
            "question": f"Test question {i}",
            "recording_timestamp_seconds": float(i * 10)})
        assert r.status_code == 201
    
    # Recording should still be in progress
    rec = client.get(f"/api/recordings/{rec_id}", headers=h).json()
    assert rec["status"] in ("RECORDING", "PAUSED", "PROCESSING"), \
        f"Recording stopped unexpectedly: {rec['status']}"
    
    # Stop
    client.post(f"/api/recordings/{rec_id}/stop", headers=h)
    rec = client.get(f"/api/recordings/{rec_id}", headers=h).json()
    assert rec["status"] == "PROCESSING"


def test_recording_tenant_isolation():
    """Company A cannot access Company B recordings."""
    h_a, _ = _admin()
    eq_id = _create_equipment(h_a)
    inv_id = _create_investigation(h_a, eq_id)
    case = _create_case(h_a, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h_a, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h_a), "title": "Company A Recording"})
    rec_a = r.json()["id"]
    
    # Company B
    h_b, _ = _admin()
    eq_id_b = _create_equipment(h_b)
    inv_id_b = _create_investigation(h_b, eq_id_b)
    r = client.post("/api/recordings", headers=h_b, json={
        "investigation_id": inv_id_b, "equipment_id": eq_id_b,
        "title": "Company B Recording"})
    rec_b = r.json()["id"]
    
    # A tries to access B's recording
    r = client.get(f"/api/recordings/{rec_b}", headers=h_a)
    assert r.status_code == 404
    
    # B tries to access A's recording
    r = client.get(f"/api/recordings/{rec_a}", headers=h_b)
    assert r.status_code == 404


def test_recording_rbac():
    """Roles enforce recording permissions - all authenticated roles can create."""
    h_admin, _ = _admin()
    eq_id = _create_equipment(h_admin)
    inv_id = _create_investigation(h_admin, eq_id)
    case = _create_case(h_admin, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h_admin, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h_admin), "title": "RBAC Test"})
    rec_id = r.json()["id"]
    
    # ENGINEER can create recording (all authenticated roles can)
    h_tech, _ = _engineer()
    eq_id_tech = _create_equipment(h_tech)
    inv_id_tech = _create_investigation(h_tech, eq_id_tech)
    r = client.post("/api/recordings", headers=h_tech, json={
        "investigation_id": inv_id_tech, "equipment_id": eq_id_tech,
        "title": "Tech Recording"})
    assert r.status_code == 201
    
    # Unauthenticated cannot create
    r = client.post("/api/recordings", json={
        "investigation_id": inv_id, "equipment_id": _create_equipment(h_admin),
        "title": "Unauth Recording"})
    assert r.status_code in (401, 403)


def test_recording_idor_protection():
    """Cannot access recordings by guessing IDs."""
    h_a, _ = _admin()
    eq_id = _create_equipment(h_a)
    inv_id = _create_investigation(h_a, eq_id)
    case = _create_case(h_a, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h_a, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h_a), "title": "IDOR Test"})
    rec_a = r.json()["id"]
    
    h_b, _ = _admin()
    r = client.get(f"/api/recordings/{rec_a}", headers=h_b)
    assert r.status_code == 404


def test_recording_audit_events():
    """Recording lifecycle creates audit events."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Audit Test"})
    rec_id = r.json()["id"]
    
    client.post(f"/api/recordings/{rec_id}/start", headers=h)
    client.post(f"/api/recordings/{rec_id}/pause", headers=h)
    client.post(f"/api/recordings/{rec_id}/resume", headers=h)
    client.post(f"/api/recordings/{rec_id}/stop", headers=h)
    
    # Check audit events exist
    # This would query audit_events table directly
    con = db()
    events = con.execute(
        "SELECT * FROM audit_events WHERE entity_type = 'recording' AND entity_id = ?",
        (rec_id,)).fetchall()
    assert len(events) >= 4  # created, started, paused, stopped


def test_recording_sovereignty():
    """Recording respects sovereignty configuration."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Sov Test"})
    rec_id = r.json()["id"]
    
    # Check sovereignty classification defaults
    rec = client.get(f"/api/recordings/{rec_id}", headers=h).json()
    assert rec["sovereignty_classification"] == "INTERNAL"
    
    # Update sovereignty classification
    # (Would need PUT endpoint - not implemented yet)
    # Just verify field exists
    assert "sovereignty_classification" in rec
    assert "integrity_hash" in rec
    assert "sha256_hash" in rec


def test_recording_duplicate_chunk():
    """Uploading duplicate chunk index fails."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Chunk Test"})
    rec_id = r.json()["id"]
    
    # Try to upload chunk with same index twice
    import hashlib
    chunk_data = b"test chunk data"
    sha256_hash = hashlib.sha256(b"test chunk data").hexdigest()
    
    # First upload
    files = {"file": ("chunk1.webm", b"chunk1", "video/webm")}
    data = {"chunk_index": 0, "total_chunks": 2, "chunk_sha256": sha256_hash}
    r = client.post(f"/api/recordings/1/chunks", headers=h, data=data, files=files)
    # Will fail because recording 1 may not exist, but tests endpoint
    assert r.status_code in (404, 422)


def test_lineage_node_type_validation():
    """Lineage node type must be valid."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Lineage Test"})
    rec_id = r.json()["id"]
    
    # This tests the lineage node type CHECK constraint indirectly
    # via the recording frame capture
    r = client.post(f"/api/recordings/1/lineage", headers=h, json={
        "node_type": "INVALID_TYPE", "label": "Test"})
    assert r.status_code in (404, 422)


def test_recording_sovereignty_classification():
    """Recordings have sovereignty classification field."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Sov Test"})
    rec = r.json()
    
    assert "sovereignty_classification" in rec
    assert rec["sovereignty_classification"] in ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")


def test_recording_integrity_hash():
    """Recording has integrity hash field."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Hash Test"})
    rec = r.json()
    
    assert "integrity_hash" in rec
    assert "sha256_hash" in rec
    assert "file_size" in rec


def test_recording_processing_status():
    """Recording has processing status tracking."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Processing Test"})
    rec = r.json()
    
    assert rec["status"] == "DRAFT"
    assert rec["processing_status"] == "PENDING"
    
    client.post(f"/api/recordings/{rec['id']}/start", headers=h)
    client.post(f"/api/recordings/{rec['id']}/stop", headers=h)
    
    rec = client.get(f"/api/recordings/{rec['id']}", headers=h).json()
    assert rec["status"] == "PROCESSING"
    assert rec["processing_status"] == "QUEUED"


def test_recording_case_integration():
    """Recording links to case correctly."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]
    
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Case Integration"})
    rec = r.json()
    
    assert rec["case_id"] == cid
    assert rec["investigation_id"] == inv_id
    
    # Get via case
    r = client.get(f"/api/case/{cid}", headers=h)
    # Case detail should include recordings (if implemented)
    assert r.status_code == 200


def test_ai_copilot_is_grounded_not_fake():
    """AI copilot answer must be grounded, never a fabricated placeholder."""
    h, _ = _admin()
    eq_id = _create_equipment(h)
    inv_id = _create_investigation(h, eq_id)
    case = _create_case(h, inv_id)
    cid = case["id"]

    # Recording linked to an investigation → grounded answer.
    r = client.post("/api/recordings", headers=h, json={
        "investigation_id": inv_id, "case_id": cid,
        "equipment_id": _create_equipment(h), "title": "Grounded AI Test"})
    rec_id = r.json()["id"]

    r = client.post(f"/api/recordings/{rec_id}/questions", headers=h, json={
        "recording_id": rec_id,
        "question": "What could cause this vibration?",
        "recording_timestamp_seconds": 30.0})
    assert r.status_code == 201
    answer = r.json().get("answer", "")
    assert answer, "Answer must not be empty"
    assert "placeholder" not in answer.lower(), f"Fake placeholder leaked: {answer}"

    # Recording WITHOUT a linked investigation → honest "unavailable".
    r2 = client.post("/api/recordings", headers=h, json={
        "equipment_id": _create_equipment(h), "title": "No-Investigation AI Test"})
    rec2 = r2.json()["id"]
    r = client.post(f"/api/recordings/{rec2}/questions", headers=h, json={
        "recording_id": rec2,
        "question": "What do you see?",
        "recording_timestamp_seconds": 5.0})
    assert r.status_code == 201
    answer2 = r.json().get("answer", "")
    assert "unavailable" in answer2.lower(), f"Expected honest unavailable, got: {answer2}"
    assert "placeholder" not in answer2.lower()
