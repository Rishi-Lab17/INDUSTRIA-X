"""Stage 6 tests: sensor ingest/analysis, vision, annotations, multimodal,
isolation, RBAC, audit, provenance. All results derive from real inputs."""
import io

import numpy as np

from app.core.config import get_settings
from helpers import client, code_for, db

K = 0


def _next(prefix="s6"):
    global K
    K += 1
    return f"{prefix}{K}@s6.test", f"{prefix.capitalize()} Co {K}"


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
    email = f"{tag}-{role.lower()}@s6.test"
    r = client.post("/api/auth/users", headers=admin_h,
                    json={"name": tag, "email": email,
                          "password": "Str0ngPass!", "role": role})
    assert r.status_code == 201, r.text
    lr = client.post("/api/auth/login",
                     json={"email": email, "password": "Str0ngPass!"})
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


def _equipment(h, code="P-204"):
    r = client.post("/api/equipment", headers=h,
                    json={"code": code, "name": f"Pump {code}", "type": "Pump",
                          "criticality": "HIGH"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload_sensor(h, content: bytes, filename: str, equipment_id: int):
    files = {"file": (filename, io.BytesIO(content), "text/csv")}
    return client.post("/api/sensors/upload", headers=h, files=files,
                       data={"equipment_id": str(equipment_id)})


def _upload_image(h, content: bytes, filename: str, equipment_id: int,
                  mime="image/png"):
    files = {"file": (filename, io.BytesIO(content), mime)}
    return client.post("/api/vision/images", headers=h, files=files,
                       data={"equipment_id": str(equipment_id)})


def _stub_run(h, sid):
    """Insert a minimal ai_runs row (FK-safe) for direct tool-execution tests."""
    me = client.get("/api/auth/me", headers=h).json()["user"]
    con = db()
    try:
        cur = con.execute(
            "INSERT INTO ai_runs (company_id, user_id, session_id, provider, model,"
            " task_type, status, created_at) VALUES (?,?,?,?,?,'document_qa','QUEUED',"
            " datetime('now'))",
            (me["company_id"], me["id"], sid, "test", "test"))
        con.commit()
        return cur.lastrowid, me
    finally:
        con.close()


def _png(color="red", size=(800, 600)):
    from PIL import Image, ImageDraw
    buf = io.BytesIO()
    img = Image.new("RGB", size, color)
    d = ImageDraw.Draw(img)
    for i in range(0, size[0], 16):
        d.line([(i, 0), (i, size[1])], fill="black", width=2)
    d.text((40, 40), "SYNTHETIC", fill="white")
    img.save(buf, format="PNG")
    return buf.getvalue()


def _webp(size=(800, 600)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 90, 160)).save(buf, format="WEBP")
    return buf.getvalue()


VIB_CSV = None


def _vib_csv():
    global VIB_CSV
    if VIB_CSV is None:
        rng = np.random.default_rng(11)
        n = 600
        lines = ["timestamp,vibration_mm_s,temperature_C"]
        for i in range(n):
            v = 2.0 + 0.2 * rng.standard_normal()
            if 300 <= i < 330:
                v = 6.5
            lines.append(f"2026-09-01 12:{i // 60:02d}:{i % 60:02d},"
                         f"{v:.3f},{68 + 0.1 * rng.standard_normal():.2f}")
        VIB_CSV = "\n".join(lines).encode()
    return VIB_CSV


# ---------- ingestion ----------

def test_sensor_upload_and_quality():
    ha, _ = _admin()
    eq = _equipment(ha)
    r = _upload_sensor(ha, _vib_csv(), "vib.csv", eq)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["row_count"] == 600
    assert [c["name"] for c in d["channels"]] == ["vibration_mm_s", "temperature_C"]
    assert d["quality_status"] in ("GOOD", "WARNING")
    assert d["quality"]["score"] >= 50


def test_long_format_and_units():
    ha, _ = _admin()
    eq = _equipment(ha)
    body = b"timestamp,sensor_name,value\n2026-09-01 12:00:00,vib,2.1\n2026-09-01 12:00:01,vib,2.2\n"
    r = _upload_sensor(ha, body, "long.csv", eq)
    assert r.status_code == 201, r.text
    assert r.json()["channels"][0]["name"] == "vib"
    body2 = b"timestamp,temperature [C]\n2026-09-01 12:00:00,68.1\n2026-09-01 12:00:01,68.2\n"
    r = _upload_sensor(ha, body2, "u.csv", eq)
    assert r.json()["channels"][0] == {"name": "temperature", "unit": "C"}


def test_malformed_and_missing_data():
    ha, _ = _admin()
    eq = _equipment(ha)
    assert _upload_sensor(ha, b"1.0,2.0\n3.0,4.0\n", "noheader.csv", eq).status_code == 422
    assert _upload_sensor(ha, b"timestamp,v\nnot-a-time,1.0\n", "badts.csv", eq).status_code == 422
    assert _upload_sensor(ha, b"", "empty.csv", eq).status_code == 422
    assert _upload_sensor(ha, b"a,b\n", "exe.csv.exe", eq).status_code == 422
    assert _upload_sensor(ha, b"timestamp,v\n2026-09-01 12:00:00,\n2026-09-01 12:00:01,1.0\n",
                          "miss.csv", eq).status_code == 201


def test_duplicates_and_irregular_flagged():
    ha, _ = _admin()
    eq = _equipment(ha)
    rows = ["timestamp,v"]
    for i in range(12):
        ts = f"2026-09-01 12:00:{i:02d}" if i != 5 else "2026-09-01 12:00:04"
        rows.append(f"{ts},{1.0 + i * 0.1:.1f}")
    rows.append("2026-09-01 12:00:30,2.5")  # gap
    r = _upload_sensor(ha, "\n".join(rows).encode(), "dup.csv", eq)
    assert r.status_code == 201
    q = r.json()["quality"]
    text = " ".join(q.get("problems", [])).lower()
    assert "duplicate" in text or q["status"] in ("WARNING", "POOR")


def test_oversize_and_row_cap():
    s = get_settings()
    old = s.SENSOR_MAX_ROWS
    s.SENSOR_MAX_ROWS = 10
    try:
        ha, _ = _admin()
        eq = _equipment(ha)
        lines = ["timestamp,v"] + [f"2026-09-01 12:00:{i:02d},1.0" for i in range(30)]
        r = _upload_sensor(ha, "\n".join(lines).encode(), "big.csv", eq)
        assert r.status_code == 422 and "limit" in r.json()["detail"].lower()
    finally:
        s.SENSOR_MAX_ROWS = old


# ---------- analysis math ----------

def test_statistics_exact():
    ha, _ = _admin()
    eq = _equipment(ha)
    lines = ["timestamp,v"] + [f"2026-09-01 12:00:{i:02d},{float(i)}" for i in range(60)]
    did = _upload_sensor(ha, "\n".join(lines).encode(), "lin.csv", eq).json()["id"]
    r = client.post(f"/api/sensors/{did}/analyze", headers=ha,
                    json={"channel": "v", "method": "zscore"}).json()
    st = r["statistics"]
    assert st["n"] == 60 and st["min"] == 0.0 and st["max"] == 59.0
    assert abs(st["mean"] - 29.5) < 1e-9
    assert abs(st["rms"] - (sum(float(i) ** 2 for i in range(60)) / 60) ** 0.5) < 1e-6
    assert r["trend"]["direction"] == "INCREASING"


def test_trend_directions():
    ha, _ = _admin()
    eq = _equipment(ha)

    def mk(vals, name):
        lines = ["timestamp,v"] + [
            f"2026-09-01 12:{i // 60:02d}:{i % 60:02d},{v}" for i, v in enumerate(vals)]
        return _upload_sensor(ha, "\n".join(lines).encode(), name, eq).json()["id"]

    assert client.post(f"/api/sensors/{mk(list(range(60, 0, -1)), 'd.csv')}/trend",
                       headers=ha, json={"channel": "v"}).json()["trend"]["direction"] == "DECREASING"
    assert client.post(f"/api/sensors/{mk([5.0] * 60, 's.csv')}/trend",
                       headers=ha, json={"channel": "v"}).json()["trend"]["direction"] == "STABLE"


def test_anomaly_methods_and_language():
    ha, _ = _admin()
    eq = _equipment(ha)
    did = _upload_sensor(ha, _vib_csv(), "v.csv", eq).json()["id"]
    for method, minimum in (("zscore", 20), ("rolling_zscore", 1), ("iqr", 1)):
        r = client.post(f"/api/sensors/{did}/analyze", headers=ha,
                        json={"channel": "vibration_mm_s", "method": method}).json()
        assert r["anomalies"]["count"] >= minimum, (method, r["anomalies"]["count"])
        assert r["anomalies"]["language"] == "Statistical anomaly detected."
        assert "fail" not in r["anomalies"]["language"].lower()
    r = client.post(f"/api/sensors/{did}/analyze", headers=ha,
                    json={"channel": "vibration_mm_s", "method": "threshold"}).json()
    assert r["anomalies"]["note"] == "No configured engineering threshold."
    r = client.post(f"/api/sensors/{did}/analyze", headers=ha,
                    json={"channel": "vibration_mm_s", "method": "threshold",
                          "gt": 5.0}).json()
    assert 25 <= r["anomalies"]["count"] <= 35


def test_fft_valid_and_invalid():
    ha, _ = _admin()
    eq = _equipment(ha)
    n, fs = 500, 50.0
    t = np.arange(n) / fs
    x = 2.0 * np.sin(2 * np.pi * 5 * t)
    lines = ["timestamp,v"] + [
        f"2026-09-01 12:00:00.{int((t[i] % 1) * 1000000):06d},{x[i]:.4f}" for i in range(n)]
    # use epoch-based regular timestamps instead
    base = 1756728000.0
    lines = ["timestamp,v"] + [f"{base + i / fs:.3f},{x[i]:.4f}" for i in range(n)]
    did = _upload_sensor(ha, "\n".join(lines).encode(), "sine.csv", eq).json()["id"]
    f = client.post(f"/api/sensors/{did}/frequency", headers=ha,
                    json={"channel": "v"}).json()["frequency"]
    assert f["available"] is True
    assert abs(f["peaks"][0]["frequency_hz"] - 5.0) < 0.3
    assert f["sample_rate_hz"] == 50.0
    assert "interpretation" in f["limitation"].lower() or "interpret" in f["limitation"].lower()
    # irregular sampling refused honestly
    irr = ["timestamp,v", "2026-09-01 12:00:00,1.0", "2026-09-01 12:00:01,1.0",
           "2026-09-01 12:00:10,1.0", "2026-09-01 12:00:11,1.0",
           "2026-09-01 12:00:12,1.0", "2026-09-01 12:00:40,1.0"]
    did2 = _upload_sensor(ha, "\n".join(irr).encode(), "irr.csv", eq).json()["id"]
    f2 = client.post(f"/api/sensors/{did2}/frequency", headers=ha,
                     json={"channel": "v"}).json()["frequency"]
    assert f2["available"] is False
    assert f2["reason"] == "Frequency analysis unavailable for this dataset."


def test_correlation_and_event_window():
    ha, _ = _admin()
    eq = _equipment(ha)
    did = _upload_sensor(ha, _vib_csv(), "v.csv", eq).json()["id"]
    r = client.post("/api/sensors/correlation", headers=ha,
                    json={"dataset_id": did, "channel_a": "vibration_mm_s",
                          "channel_b": "vibration_mm_s"}).status_code
    assert r == 422  # identical channels rejected
    r = client.post("/api/sensors/correlation", headers=ha,
                    json={"dataset_id": did, "channel_a": "vibration_mm_s",
                          "channel_b": "temperature_C"}).json()
    assert r["r"] is not None and r["n"] > 100
    assert "causation" in r["note"]
    assert -1.0 <= r["r"] <= 1.0
    r = client.post(f"/api/sensors/{did}/analyze", headers=ha,
                    json={"channel": "vibration_mm_s", "method": "zscore",
                          "event_start": 1788264240.0, "event_end": 1788264360.0}).json()
    assert "event" in r and r["event"]["anomalies_in_window"] >= 1
    assert r["event"]["baseline_before"]["n"] > 0


def test_series_chart_and_export():
    ha, _ = _admin()
    eq = _equipment(ha)
    did = _upload_sensor(ha, _vib_csv(), "v.csv", eq).json()["id"]
    s = client.get(f"/api/sensors/{did}/series?channel=vibration_mm_s",
                   headers=ha).json()
    assert len(s["times"]) == 600 and s["downsampled"] is False
    r = client.get(f"/api/sensors/{did}/export", headers=ha)
    assert r.status_code == 200 and "timestamp" in r.text
    assert len(r.text.splitlines()) == 601


# ---------- vision ----------

def test_image_upload_and_metadata():
    ha, _ = _admin()
    eq = _equipment(ha)
    r = _upload_image(ha, _png(), "insp.png", eq)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["width"] == 800 and m["height"] == 600
    assert len(m["sha256_hash"]) == 64
    assert m["quality_status"] in ("GOOD", "WARNING")
    assert _upload_image(ha, _webp(), "insp.webp", eq,
                         mime="image/webp").status_code == 201


def test_invalid_images_rejected():
    ha, _ = _admin()
    eq = _equipment(ha)
    assert _upload_image(ha, b"not an image", "x.png", eq).status_code == 422
    assert _upload_image(ha, _png()[:100], "trunc.png", eq).status_code == 422
    assert _upload_image(ha, _png(), "x.exe", eq).status_code == 422
    assert _upload_image(ha, _png(), "x.png", 999999).status_code == 404


def test_image_quality_states():
    ha, _ = _admin()
    eq = _equipment(ha)
    tiny = _upload_image(ha, _png(size=(200, 150)), "tiny.png", eq).json()
    assert tiny["quality_status"] == "POOR"
    assert any("resolution" in r for r in tiny["quality_detail"]["reasons"])


def test_ocr_unavailable_honest():
    from app.processing.ocr import ocr_available
    assert ocr_available() is False  # no tesseract binary here
    ha, _ = _admin()
    eq = _equipment(ha)
    aid = _upload_image(ha, _png(), "o.png", eq).json()["id"]
    r = client.post(f"/api/vision/images/{aid}/ocr", headers=ha).json()
    assert r["ocr_status"] == "UNAVAILABLE"
    assert "unavailable" in r["note"].lower()
    assert r["ocr_text"] == ""


def test_vision_analyze_refuses_poor():
    ha, _ = _admin()
    eq = _equipment(ha)
    aid = _upload_image(ha, _png(size=(200, 150)), "tiny.png", eq).json()["id"]
    r = client.post(f"/api/vision/images/{aid}/analyze", headers=ha).json()
    assert r["status"] == "REFUSED"
    assert "POOR" in r["reason"]
    aid2 = _upload_image(ha, _png(), "good.png", eq).json()["id"]
    r = client.post(f"/api/vision/images/{aid2}/analyze", headers=ha).json()
    assert r["status"] == "ANALYZED"
    assert "diagnosis" in r["limitation"].lower() or "diagnos" in r["limitation"].lower()


def test_annotations_crud_and_authz():
    ha, _ = _admin()
    he = _mkuser(ha, "ENGINEER", "ann-e")
    ht = _mkuser(ha, "TECHNICIAN", "ann-t")
    eq = _equipment(ha)
    aid = _upload_image(ha, _png(), "a.png", eq).json()["id"]
    body = {"x": 0.4, "y": 0.3, "w": 0.2, "h": 0.2, "label": "corrosion",
            "note": "flaking paint"}
    r = client.post(f"/api/vision/images/{aid}/annotations", headers=ht, json=body)
    assert r.status_code == 201, r.text  # tech may observe
    ann = r.json()["id"]
    bad = dict(body, x=0.9, w=0.5)
    assert client.post(f"/api/vision/images/{aid}/annotations",
                       headers=he, json=bad).status_code == 422
    bad2 = dict(body, label="alien")
    assert client.post(f"/api/vision/images/{aid}/annotations",
                       headers=he, json=bad2).status_code == 422
    # other engineer cannot edit tech's annotation; admin can
    he2 = _mkuser(ha, "ENGINEER", "ann-e2")
    assert client.patch(f"/api/vision/images/{aid}/annotations/{ann}",
                        headers=he2, json=body).status_code == 403
    assert client.patch(f"/api/vision/images/{aid}/annotations/{ann}",
                        headers=ha, json=dict(body, note="confirmed")).status_code == 200
    assert client.delete(f"/api/vision/images/{aid}/annotations/{ann}",
                         headers=he2).status_code == 403
    assert client.delete(f"/api/vision/images/{aid}/annotations/{ann}",
                         headers=ht).status_code == 200
    lst = client.get(f"/api/vision/images/{aid}/annotations", headers=ha).json()
    assert lst["annotations"] == []


# ---------- multimodal ----------

def _doc(h, content: bytes, name: str, equipment_id=None):
    import io as _io
    files = {"file": (name, _io.BytesIO(content), "application/octet-stream")}
    data = {}
    if equipment_id is not None:
        data["equipment_id"] = str(equipment_id)
    r = client.post("/api/documents", headers=h, files=files, data=data)
    assert r.status_code == 201, r.text
    return r.json()


def test_multimodal_run_and_snapshot():
    ha, _ = _admin()
    he = _mkuser(ha, "ENGINEER", "mm-e")
    eq = _equipment(ha)
    doc = _doc(he, b"Vibration operating range 0-2.8 mm/s for pumps.", "range.txt", eq)
    client.post(f"/api/knowledge/documents/{doc['id']}/index",
                headers=he).json()
    ds = _upload_sensor(he, _vib_csv(), "v.csv", eq).json()["id"]
    aid = _upload_image(he, _png(), "i.png", eq).json()["id"]
    ann = client.post(f"/api/vision/images/{aid}/annotations", headers=he, json={
        "x": 0.4, "y": 0.3, "w": 0.2, "h": 0.2, "label": "corrosion",
        "note": "surface rust"}).json()["id"]
    body = {"equipment_id": eq, "question": "Is vibration abnormal?",
            "document_ids": [doc["id"]], "dataset_ids": [ds], "asset_ids": [aid]}
    r = client.post("/api/investigations/multimodal", headers=he, json=body)
    assert r.status_code == 200, r.text
    res = r.json()
    kinds = {e["type"] for e in res["evidence"]}
    assert {"DOCUMENT", "SENSOR", "IMAGE"} <= kinds
    assert all(set(o) == {"kind", "text"} and o["kind"] in
               ("OBSERVATION", "INTERPRETATION", "LIMITATION")
               for o in res["observations"])
    assert res["timeline"] == sorted(res["timeline"],
                                     key=lambda e: (e["ts"] is None, e["ts"] or 0))
    assert res["interpretation"] is None or res["interpretation"]["status"] in (
        "UNAVAILABLE", "COMPLETED")
    assert any(o["kind"] == "LIMITATION" for o in res["observations"])
    assert any(o["kind"] == "INTERPRETATION" for o in res["observations"])
    assert not any(w in o["text"].lower() for o in res["observations"]
                   for w in ("definitely failed", "replace immediately", "safe to operate"))
    # snapshot round-trip
    s = client.post("/api/investigations/snapshot", headers=he, json={
        "equipment_id": eq, "question": "Is vibration abnormal?",
        "config": body, "results": res}).json()
    got = client.get(f"/api/investigations/{s['investigation_id']}",
                     headers=he).json()
    assert got["results"]["question"] == "Is vibration abnormal?"
    assert got["results"]["results"]["evidence"] == res["evidence"]
    assert got["results"]["saved_at"] and got["results"]["format_version"] == 1
    lst = client.get("/api/investigations", headers=he).json()
    assert any(i["id"] == s["investigation_id"] for i in lst["investigations"])
    # tech cannot create investigations but can view
    ht = _mkuser(ha, "TECHNICIAN", "mm-t")
    assert client.post("/api/investigations/multimodal", headers=ht,
                       json=body).status_code == 403
    assert client.get(f"/api/investigations/{s['investigation_id']}",
                      headers=ht).status_code == 200


def test_multimodal_scoping_and_validation():
    ha, _ = _admin()
    hb, _ = _admin()
    eq_a = _equipment(ha)
    eq_b = _equipment(hb, code="C-301")
    doc_b = _doc(hb, b"other company doc", "o.txt", eq_b)
    body = {"equipment_id": eq_a, "question": "q", "document_ids": [doc_b["id"]]}
    assert client.post("/api/investigations/multimodal", headers=ha,
                       json=body).status_code in (404, 422)
    inv = client.post("/api/investigations/snapshot", headers=hb, json={
        "equipment_id": eq_b, "question": "q", "config": {}, "results": {}}).json()
    assert client.get(f"/api/investigations/{inv['investigation_id']}",
                      headers=ha).status_code == 404
    assert client.post("/api/investigations/multimodal", headers=ha, json={
        "equipment_id": eq_a, "question": " ",
        "window_start": 2.0}).status_code == 422


# ---------- isolation / RBAC / audit ----------

def test_cross_company_multimodal_isolation():
    ha, _ = _admin()
    hb, _ = _admin()
    eq_a = _equipment(ha)
    ds = _upload_sensor(ha, _vib_csv(), "v.csv", eq_a).json()["id"]
    aid = _upload_image(ha, _png(), "i.png", eq_a).json()["id"]
    for method, path in [("get", f"/api/sensors/{ds}"),
                         ("get", f"/api/sensors/{ds}/quality"),
                         ("get", f"/api/sensors/{ds}/series?channel=vibration_mm_s"),
                         ("get", f"/api/sensors/{ds}/export"),
                         ("get", f"/api/vision/images/{aid}"),
                         ("get", f"/api/vision/images/{aid}/file"),
                         ("get", f"/api/vision/images/{aid}/annotations")]:
        r = client.request(method, path, headers=hb)
        assert r.status_code == 404, (method, path, r.status_code)
        assert "2.1" not in r.text and "PNG" not in r.text
    assert client.get("/api/sensors", headers=hb).json()["datasets"] == []
    assert client.get("/api/vision/images", headers=hb).json()["images"] == []


def test_rbac_sensor_vision():
    ha, _ = _admin()
    ht = _mkuser(ha, "TECHNICIAN", "rb-t")
    eq = _equipment(ha)
    assert _upload_sensor(ht, _vib_csv(), "v.csv", eq).status_code == 403
    ds = _upload_sensor(ha, _vib_csv(), "v.csv", eq).json()["id"]
    assert client.post(f"/api/sensors/{ds}/analyze", headers=ht,
                       json={"channel": "vibration_mm_s"}).status_code == 403
    assert client.get(f"/api/sensors/{ds}", headers=ht).status_code == 200
    assert client.get(f"/api/sensors/{ds}/export", headers=ht).status_code == 200
    assert _upload_image(ht, _png(), "t.png", eq).status_code == 201
    for method, path in [("get", "/api/sensors"), ("get", "/api/vision/images"),
                         (None, None)]:
        if method:
            assert client.request(method, path).status_code == 401


def test_audit_and_provenance_records():
    ha, _ = _admin()
    eq = _equipment(ha)
    ds = _upload_sensor(ha, _vib_csv(), "v.csv", eq).json()["id"]
    client.post(f"/api/sensors/{ds}/analyze", headers=ha,
                json={"channel": "vibration_mm_s"})
    aid = _upload_image(ha, _png(), "i.png", eq).json()["id"]
    ann = client.post(f"/api/vision/images/{aid}/annotations", headers=ha, json={
        "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "crack"}).json()["id"]
    client.post(f"/api/vision/images/{aid}/analyze", headers=ha)
    con = db()
    try:
        acts = {r[0] for r in con.execute(
            "SELECT DISTINCT action FROM audit_events").fetchall()}
        runs = con.execute("SELECT method, params, result_summary, warnings FROM"
                           " analysis_runs").fetchall()
    finally:
        con.close()
    for a in ("sensor_uploaded", "sensor_analysis", "image_uploaded",
              "annotation_created"):
        assert a in acts, acts
    assert runs and any(r[0].startswith("sensor") for r in runs)
    assert any(r[0].startswith("vision") for r in runs)
    import json as _json
    assert all(_json.loads(r[1]) for r in runs)


def test_agent_tools_execute_scoped():
    from app.agents import tools as T
    ha, _ = _admin()
    hb, _ = _admin()
    me = client.get("/api/auth/me", headers=ha).json()["user"]
    sess = {"company_id": me["company_id"], "user_id": me["id"], "role": "ENGINEER"}
    sid = client.post("/api/ai/sessions", headers=ha, json={}).json()["id"]
    rid, _ = _stub_run(ha, sid)
    eq = _equipment(ha)
    ds = _upload_sensor(ha, _vib_csv(), "v.csv", eq).json()["id"]
    r = T.execute_tool(run_id=rid, sess=sess, name="analyze_sensor_data",
                       args={"dataset_id": ds, "channel": "vibration_mm_s",
                             "method": "zscore"})
    assert r["ok"] is True and r["output"]["anomaly_count"] >= 20
    r = T.execute_tool(run_id=rid,
                       sess={"company_id": 999999, "user_id": 1, "role": "ENGINEER"},
                       name="analyze_sensor_data",
                       args={"dataset_id": ds, "channel": "vibration_mm_s"})
    assert r["ok"] is False
    r = T.execute_tool(run_id=rid, sess={**sess, "role": "TECHNICIAN"},
                       name="analyze_sensor_data",
                       args={"dataset_id": ds, "channel": "vibration_mm_s"})
    assert r["ok"] is False and r.get("denied") is True
    aid = _upload_image(ha, _png(), "i.png", eq).json()["id"]
    r = T.execute_tool(run_id=rid, sess=sess, name="analyze_vision_image",
                       args={"asset_id": aid})
    assert r["ok"] is True and r["output"]["quality"] in ("GOOD", "WARNING")
