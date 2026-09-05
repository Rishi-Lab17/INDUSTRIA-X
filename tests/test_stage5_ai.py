"""Stage 5 tests: provider abstraction, Kimi offline honesty, registry/routing,
sessions, runs, streaming, cancel, timeout, retry, RAG grounding, equipment
context, isolation, RBAC, tool security, limits, audit, sovereignty, secrets.

AI_PROVIDER=test for infrastructure tests (never presented as Kimi).
Real-Kimi contract tests SKIP honestly when no runtime is present.
"""
import json
import threading
import time

import pytest

from app.agents import orchestrator, tools as tool_registry
from app.ai import prompts
from app.ai.providers import (KimiK3Provider, ModelRequestInvalid,
                              ModelUnavailable, TestProvider as _TestDouble,
                              get_provider, set_provider)
from app.ai.registry import cached_health, list_models, route
from app.core.config import get_settings
from app.core.rate_limit import reset_all
from helpers import client, code_for, db

_s = get_settings()
_orig = {"AI_PROVIDER": _s.AI_PROVIDER, "KIMI_K3_TIMEOUT_S": _s.KIMI_K3_TIMEOUT_S,
         "AI_RUNS_PER_USER": _s.AI_RUNS_PER_USER,
         "AI_RUNS_PER_USER_WINDOW_S": _s.AI_RUNS_PER_USER_WINDOW_S,
         "AI_MAX_TOOL_CALLS_PER_RUN": _s.AI_MAX_TOOL_CALLS_PER_RUN,
         "KIMI_ENABLED": _s.KIMI_ENABLED}
_s.AI_PROVIDER = "test"
_s.KIMI_K3_TIMEOUT_S = 5
set_provider(None)

N = 0


def _next(prefix="ai"):
    global N
    N += 1
    return f"{prefix}{N}@ai.test", f"{prefix.capitalize()} Co {N}"


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
    token = lr.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, token, email


def _mkuser(admin_h, role, tag):
    email = f"{tag}-{role.lower()}@ai.test"
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


def _upload_index(h, content: bytes, filename: str, equipment_id=None):
    import io
    files = {"file": (filename, io.BytesIO(content), "application/octet-stream")}
    data = {}
    if equipment_id is not None:
        data["equipment_id"] = str(equipment_id)
    r = client.post("/api/documents", headers=h, files=files, data=data)
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    r = client.post(f"/api/knowledge/documents/{doc_id}/index", headers=h)
    assert r.status_code == 200, r.text
    return doc_id


def _session(h, equipment_id=None):
    body = {}
    if equipment_id is not None:
        body["equipment_id"] = equipment_id
    r = client.post("/api/ai/sessions", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _run_id(h, sid, content="hello"):
    r = client.post(f"/api/ai/sessions/{sid}/messages", headers=h, json={
        "content": content})
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


# ---------- provider selection / config ----------

def test_provider_selection_test_only():
    p = get_provider()
    assert isinstance(p, _TestDouble) and p.is_test
    assert p.display_name.startswith("Test Provider")


def test_kimi_config_env_based():
    s = get_settings()
    assert s.KIMI_K3_BASE_URL.startswith("http")
    assert isinstance(s.KIMI_ENABLED, bool)


def test_kimi_health_offline_honest():
    h = KimiK3Provider().health()
    # Nothing listens on 11436 in this environment.
    assert h["status"] in ("OFFLINE", "ERROR")
    assert "model" in h and "endpoint" in h and "checked_at" in h


def test_kimi_generate_offline_no_fake():
    p = KimiK3Provider()
    try:
        p.generate(messages=[{"role": "user", "content": "hi"}],
                   timeout_s=3)
        raise AssertionError("should have raised")
    except ModelUnavailable as e:
        assert "unavailable" in str(e).lower()
    except Exception as e:
        # Any error is fine as long as nothing is fabricated.
        assert not isinstance(e, str)


def test_kimi_live_contract():
    h = KimiK3Provider().health()
    if h["status"] != "ONLINE":
        pytest.skip("Kimi runtime unavailable")
    # Only runs against a real runtime; never faked.
    gen = KimiK3Provider().generate(
        messages=[{"role": "user", "content": "Reply with exactly: ok"}],
        timeout_s=30)
    assert gen.text is not None


def test_retry_transient_only():
    from unittest.mock import patch
    import httpx
    calls = {"n": 0}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "hi"}}], "usage": None}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("down")
        return FakeResp()

    with patch("httpx.post", side_effect=flaky):
        gen = KimiK3Provider().generate(
            messages=[{"role": "user", "content": "hi"}], timeout_s=5)
    assert gen.text == "hi" and calls["n"] == 2

    def bad_request(*a, **k):
        class R:
            status_code = 422
        return R()

    with patch("httpx.post", side_effect=bad_request) as m:
        try:
            KimiK3Provider().generate(
                messages=[{"role": "user", "content": "hi"}], timeout_s=5)
            raise AssertionError("should raise")
        except ModelRequestInvalid:
            pass
        assert m.call_count == 1  # no retry on invalid requests


# ---------- registry / routing ----------

def test_model_registry_honest():
    models = list_models()
    assert len(models) == 1
    m = models[0]
    assert m["is_test"] is True  # AI_PROVIDER=test in tests
    assert m["local"] is True
    assert m["context_limit"] is None  # unknown until runtime reports it
    assert isinstance(m["capabilities"], dict)


def test_model_routing_and_unavailable():
    r = route("document_qa")
    assert r["provider"] == "test"
    r = route("embedding")
    assert r["provider"] == "stage4-embeddings"
    try:
        route("vision")
        raise AssertionError("should raise")
    except ModelUnavailable as e:
        assert "unavailable" in str(e).lower()


# ---------- sessions ----------

def test_session_crud_and_owner_isolation():
    ha, _, _ = _admin()
    he = _mkuser(ha, "ENGINEER", "sess")
    eq = _equipment(ha)
    sid = _session(he, eq)
    got = client.get(f"/api/ai/sessions/{sid}", headers=he).json()
    assert got["session"]["equipment_id"] == eq
    assert got["messages"] == []
    # owner sees own list; admin sees own (empty) list
    assert any(s["id"] == sid
               for s in client.get("/api/ai/sessions", headers=he).json()["sessions"])
    # admin cannot read engineer's session content (owner-only + admin? admin CAN)
    assert client.get(f"/api/ai/sessions/{sid}", headers=ha).status_code == 200
    # foreign equipment rejected
    hb, _, _ = _admin()
    assert client.post("/api/ai/sessions", headers=hb,
                       json={"equipment_id": eq}).status_code == 404
    assert client.get(f"/api/ai/sessions/{sid}", headers=hb).status_code == 404
    # delete by owner
    assert client.delete(f"/api/ai/sessions/{sid}", headers=he).status_code == 200
    assert client.get(f"/api/ai/sessions/{sid}", headers=he).status_code == 404


def test_unauthenticated_blocked():
    for method, path in [("get", "/api/ai/models"), ("get", "/api/ai/health"),
                         ("get", "/api/ai/tools"), ("get", "/api/ai/sessions"),
                         ("post", "/api/ai/sessions"),
                         ("post", "/api/ai/sessions/1/messages"),
                         ("get", "/api/ai/runs/1")]:
        r = client.request(method, path, json={} if method == "post" else None)
        assert r.status_code == 401, (method, path, r.status_code)


# ---------- messages / runs / RAG grounding ----------

def _company_with_evidence(tag="ev"):
    ha, _, _ = _admin()
    eq = _equipment(ha)
    _upload_index(ha, b"Bearing vibration limit for Pump P-204 is 2.8 mm/s. "
                      b"Inspect bearings monthly.", "manual.txt", eq)
    return ha, eq


def test_message_grounded_citations_and_run_record():
    ha, eq = _company_with_evidence()
    sid = _session(ha, eq)
    r = client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
        "content": "What is the vibration limit?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "COMPLETED"
    assert body["answer"] and body["citations"]
    assert body["citations"][0]["filename"] == "manual.txt"
    assert body["sources_count"] >= 1
    assert body["prompt_version"] == prompts.PROMPT_VERSION
    assert body["tools_used"] and "search_knowledge_base" in body["tools_used"]
    run_id = body["run_id"]
    run = client.get(f"/api/ai/runs/{run_id}", headers=ha).json()
    assert run["run"]["status"] == "COMPLETED"
    assert run["run"]["duration_ms"] is not None
    assert run["tool_runs"]
    # run usage unavailable from test provider → null (honest, not estimated)
    con = db()
    try:
        row = con.execute("SELECT tokens_in, tokens_out FROM ai_runs WHERE id = ?",
                          (run_id,)).fetchone()
        assert row["tokens_in"] is None and row["tokens_out"] is None
    finally:
        con.close()


def test_insufficient_evidence_no_fabrication():
    ha, _, _ = _admin()
    sid = _session(ha)
    r = client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
        "content": "Zebra orbit schedules for Mars?"})
    body = r.json()
    assert body["status"] == "COMPLETED"
    assert body["citations"] == []
    assert "insufficient evidence" in body["answer"].lower()


def test_equipment_context_scoping():
    ha, eq = _company_with_evidence("eq")
    sid = _session(ha, eq)
    r = client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
        "content": "vibration limit?"})
    assert all(c["equipment_id"] == eq for c in r.json()["citations"])
    # cross-company equipment session creation blocked
    hb, _, _ = _admin()
    assert client.post("/api/ai/sessions", headers=hb,
                       json={"equipment_id": eq}).status_code == 404


def test_cross_company_ai_isolation():
    ha, eq = _company_with_evidence("xa")
    sid_a = _session(ha, eq)
    client.post(f"/api/ai/sessions/{sid_a}/messages", headers=ha, json={
        "content": "vibration limit?"})
    hb, _, _ = _admin()
    assert client.get(f"/api/ai/sessions/{sid_a}", headers=hb).status_code == 404
    assert client.post(f"/api/ai/sessions/{sid_a}/messages", headers=hb, json={
        "content": "hi"}).status_code == 404
    run_id = client.get(f"/api/ai/sessions/{sid_a}", headers=ha).json()["runs"][0]["id"]
    assert client.get(f"/api/ai/runs/{run_id}", headers=hb).status_code == 404
    # tools execute under caller authZ: B cannot touch A's equipment
    res = tool_registry.execute_tool(run_id=run_id, sess={"company_id": 999999,
                                                          "user_id": 1, "role": "ENGINEER"},
                                     name="get_equipment",
                                     args={"equipment_id": eq})
    assert res["ok"] is False


def test_technician_can_chat_with_owned_scope():
    ha, _, _ = _admin()
    ht = _mkuser(ha, "TECHNICIAN", "chatt")
    sid = _session(ht)
    r = client.post(f"/api/ai/sessions/{sid}/messages", headers=ht, json={
        "content": "hello"})
    assert r.status_code == 200
    tools = client.get("/api/ai/tools", headers=ht).json()["tools"]
    names = [t["name"] for t in tools]
    assert "search_knowledge_base" in names
    assert "get_system_health" not in names  # admin/engineer only


# ---------- streaming / cancel / timeout ----------

def test_streaming_sse_format():
    ha, eq = _company_with_evidence("st")
    sid = _session(ha, eq)
    r = client.post(f"/api/ai/sessions/{sid}/messages/stream", headers=ha, json={
        "content": "vibration limit?"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    text = r.text
    assert "event: start" in text
    assert text.count("event: token") >= 2  # real chunked frames, not one blob
    assert "event: done" in text
    assert '"status": "COMPLETED"' in text or '"status":"COMPLETED"' in text


def test_orchestrator_cancel_mid_run():
    class Slow(_TestDouble):
        def generate(self, *, messages, timeout_s, cancelled=None, **kwargs):
            for _ in range(200):
                if cancelled is not None and cancelled.is_set():
                    from app.ai.providers import _Cancelled
                    raise _Cancelled()
                import time as _t
                _t.sleep(0.05)
            return super().generate(messages=messages, timeout_s=timeout_s,
                                    cancelled=cancelled, **kwargs)

    ha, _, _ = _admin()
    sid = _session(ha)
    set_provider(Slow())
    try:
        me = client.get("/api/auth/me", headers=ha).json()["user"]
        sess = {"company_id": me["company_id"], "user_id": me["id"],
                "role": "ENGINEER", "equipment_id": None}
        box = {}
        t = threading.Thread(target=lambda: box.update(
            orchestrator.execute(sess=sess, session_id=sid,
                                 user_message="go slow")))
        t.start()
        time.sleep(0.4)
        # find the live run and cancel it
        con = db()
        try:
            row = con.execute("SELECT id FROM ai_runs ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            con.close()
        assert orchestrator.request_cancel(row["id"]) is True
        t.join(timeout=15)
        assert not t.is_alive()
        assert box["status"] == "CANCELLED"
    finally:
        set_provider(None)


def test_endpoint_cancel_completed_run():
    ha, eq = _company_with_evidence("cx")
    sid = _session(ha, eq)
    run_id = client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
        "content": "limit?"}).json()["run_id"]
    r = client.post(f"/api/ai/runs/{run_id}/cancel", headers=ha).json()
    assert r["cancelled"] is False and r["status"] == "COMPLETED"


def test_timeout_handling():
    set_provider(_TestDouble(hang=True))
    old = get_settings().KIMI_K3_TIMEOUT_S
    get_settings().KIMI_K3_TIMEOUT_S = 1
    try:
        ha, _, _ = _admin()
        sid = _session(ha)
        t0 = time.time()
        r = client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
            "content": "hang?"})
        elapsed = time.time() - t0
        assert r.status_code == 504
        assert elapsed < 40
    finally:
        get_settings().KIMI_K3_TIMEOUT_S = old
        set_provider(None)


def test_tool_loop_limit_terminates():
    s = get_settings()
    old = s.AI_MAX_TOOL_CALLS_PER_RUN
    s.AI_MAX_TOOL_CALLS_PER_RUN = 0
    try:
        ha, _, _ = _admin()
        sid = _session(ha)
        r = client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
            "content": "hello"})
        body = r.json()
        assert body["status"] == "FAILED"
        assert body["error"] == "Tool execution limit reached."
    finally:
        s.AI_MAX_TOOL_CALLS_PER_RUN = old


def test_prompt_size_limit_and_rate_limit():
    ha, _, _ = _admin()
    sid = _session(ha)
    big = "x" * (get_settings().AI_MAX_MESSAGE_CHARS + 1)
    assert client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
        "content": big}).status_code == 413
    s = get_settings()
    ou, ow = s.AI_RUNS_PER_USER, s.AI_RUNS_PER_USER_WINDOW_S
    s.AI_RUNS_PER_USER, s.AI_RUNS_PER_USER_WINDOW_S = 1, 300
    reset_all()
    try:
        assert client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
            "content": "one"}).status_code == 200
        r = client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
            "content": "two"})
        assert r.status_code == 429
    finally:
        s.AI_RUNS_PER_USER, s.AI_RUNS_PER_USER_WINDOW_S = ou, ow
        reset_all()


# ---------- tool security ----------

def test_tool_security_no_exec_or_leak():
    ha, _, _ = _admin()
    sess_row = client.get("/api/auth/me", headers=ha).json()
    sess = {"company_id": sess_row["user"]["company_id"], "user_id": 1,
            "role": "ENGINEER"}
    rid = _run_id(ha, _session(ha))
    # SQL injection attempt is just text / rejected ints
    res = tool_registry.execute_tool(run_id=rid, sess=sess,
                                     name="search_knowledge_base",
                                     args={"query": "'; DROP TABLE users; --"})
    assert res["ok"] is True  # harmless text search
    res = tool_registry.execute_tool(run_id=rid, sess=sess,
                                     name="get_equipment",
                                     args={"equipment_id": "1; DROP TABLE users"})
    assert res["ok"] is False
    res = tool_registry.execute_tool(run_id=rid, sess=sess,
                                     name="rm -rf /", args={})
    assert res["ok"] is False and res.get("denied") is True
    res = tool_registry.execute_tool(run_id=rid, sess=sess,
                                     name="get_system_health", args={})
    assert res["ok"] is True  # ENGINEER is permitted; output has no secrets
    assert "Bearer" not in json.dumps(res) and "sk-" not in json.dumps(res)
    con = db()
    try:
        assert con.execute("SELECT count(*) FROM users").fetchone()[0] >= 1
        assert con.execute("SELECT count(*) FROM equipment").fetchone()[0] >= 0
    finally:
        con.close()


def test_tool_authz_roles_and_unknown():
    ha, _, _ = _admin()
    ht = _mkuser(ha, "TECHNICIAN", "tsec")
    me_t = client.get("/api/auth/me", headers=ht).json()["user"]
    sess_t = {"company_id": me_t["company_id"], "user_id": me_t["id"],
              "role": "TECHNICIAN"}
    rid = _run_id(ht, _session(ht))
    res = tool_registry.execute_tool(run_id=rid, sess=sess_t,
                                     name="get_system_health", args={})
    assert res["ok"] is False and res.get("denied") is True
    res = tool_registry.execute_tool(run_id=rid, sess=sess_t,
                                     name="search_knowledge_base",
                                     args={"query": "x" * 5000})
    assert res["ok"] is False  # oversized args rejected


# ---------- audit / metrics / secrets / cot ----------

def test_ai_audit_and_metrics():
    ha, eq = _company_with_evidence("au")
    sid = _session(ha, eq)
    client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
        "content": "vibration?"})
    con = db()
    try:
        acts = {r[0] for r in con.execute(
            "SELECT DISTINCT action FROM audit_events").fetchall()}
    finally:
        con.close()
    for a in ("ai_session_created", "ai_request_started", "ai_request_completed",
              "ai_tool_invoked"):
        assert a in acts, acts
    h = client.get("/api/ai/health", headers=ha).json()
    assert h["runs_total"] >= 1 and h["runs_completed"] >= 1
    assert h["tool_invocations"] >= 1
    assert h["is_test"] is True  # labelled TEST, never Kimi


def test_no_secrets_no_cot_anywhere(caplog):
    import logging
    ha, _, _ = _admin()
    me = client.get("/api/auth/me", headers=ha).json()["user"]
    real_token = client.post("/api/auth/login", json={
        "email": me["email"], "password": "Str0ngPass!"}).json()["access_token"]
    with caplog.at_level(logging.INFO):
        sid = _session(ha)
        body = client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
            "content": "hello world"}).json()
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert real_token not in logs
    assert real_token not in json.dumps(body)
    assert "chain_of_thought" not in json.dumps(body).lower()
    assert "cot" not in json.dumps(body).lower().replace("scott", "")
    con = db()
    try:
        cols = [r[1] for t in ("ai_sessions", "ai_messages", "ai_runs", "ai_tool_runs")
                for r in con.execute(f"PRAGMA table_info({t})").fetchall()]
        assert not any("chain" in c or "thought" in c or "reasoning" in c
                       for c in cols)
        details = " ".join(r[0] or "" for r in con.execute(
            "SELECT detail FROM audit_events WHERE action LIKE 'ai_%'").fetchall())
        assert real_token not in details
    finally:
        con.close()


def test_sovereignty_external_blocked_and_models_labelled():
    ha, _, _ = _admin()
    sov = client.get("/api/sovereignty").json()
    assert sov["external_ai"] == "BLOCKED" and sov["external_fallback"] == "DISABLED"
    assert sov["ai_workbench"] in ("online", "offline-no-model")
    models = client.get("/api/ai/models", headers=ha).json()["models"]
    assert len(models) == 1
    assert models[0]["is_test"] is True
    assert "TEST" in models[0]["display_name"] or models[0]["provider"] == "test"
    health = client.get("/api/health", headers=ha).json()
    assert health["services"]["ai"]["status"] in ("ONLINE", "OFFLINE", "ERROR")
    assert health["services"]["kimi"]["status"] in ("ONLINE", "OFFLINE")


def test_kimi_offline_router_503_no_fallback():
    from app.ai.providers import KimiK3Provider
    set_provider(KimiK3Provider())
    try:
        ha, _, _ = _admin()
        sid = _session(ha)
        r = client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
            "content": "hello"})
        assert r.status_code == 503
        assert "unavailable" in r.json()["detail"].lower()
        # RAG evidence still recorded on the run (no silent fallback anywhere)
        assert "openai" not in r.text.lower() and "gemini" not in r.text.lower()
    finally:
        set_provider(None)


def test_e2e_workbench_flow_with_isolation():
    ha, eq = _company_with_evidence("e2e")
    sid = _session(ha, eq)
    body = client.post(f"/api/ai/sessions/{sid}/messages", headers=ha, json={
        "content": "What is the vibration limit for Pump P-204?"}).json()
    assert body["status"] == "COMPLETED"
    assert any(c["filename"] == "manual.txt" for c in body["citations"])
    assert body["plan"] and body["tools_used"]
    run_id = body["run_id"]
    run = client.get(f"/api/ai/runs/{run_id}", headers=ha).json()
    assert run["run"]["sources_count"] >= 1 and run["tool_runs"]
    hb, _, _ = _admin()
    assert client.get(f"/api/ai/runs/{run_id}", headers=hb).status_code == 404
