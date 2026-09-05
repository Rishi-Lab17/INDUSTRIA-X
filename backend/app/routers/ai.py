"""AI Workbench API. All endpoints authenticated + company-scoped; foreign
sessions/runs → 404. Rate-limited per user/company. No raw vectors, no
system prompts, no credentials ever leave the backend."""
import json
import queue
import threading

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from ..agents import orchestrator
from ..agents import tools as tool_registry
from ..ai import prompts
from ..ai.providers import ModelUnavailable, get_provider
from ..ai.registry import cached_health, list_models
from ..audit import log_event
from ..core.config import get_settings
from ..core.deps import get_current_session
from ..core.rate_limit import allow
from ..db import connect as app_connect

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _limited(sess: dict) -> None:
    s = get_settings()
    ok, retry = allow(f"ai:user:{sess['user_id']}", s.AI_RUNS_PER_USER,
                      s.AI_RUNS_PER_USER_WINDOW_S)
    if not ok:
        raise HTTPException(status_code=429,
                            detail="AI request rate limit reached. Try again later.",
                            headers={"Retry-After": str(retry)})
    ok, retry = allow(f"ai:company:{sess['company_id']}", s.AI_RUNS_PER_COMPANY,
                      s.AI_RUNS_PER_COMPANY_WINDOW_S)
    if not ok:
        raise HTTPException(status_code=429,
                            detail="Company AI request rate limit reached.",
                            headers={"Retry-After": str(retry)})


def _owned_session(session_id: int, sess: dict) -> dict:
    con = app_connect()
    try:
        row = con.execute("SELECT * FROM ai_sessions WHERE id = ? AND company_id = ?",
                          (session_id, sess["company_id"])).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(status_code=404, detail="AI session not found")
    return dict(row)


def _owned_run(run_id: int, sess: dict) -> dict:
    con = app_connect()
    try:
        row = con.execute("SELECT * FROM ai_runs WHERE id = ? AND company_id = ?",
                          (run_id, sess["company_id"])).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(status_code=404, detail="AI run not found")
    return dict(row)


def _equipment_owned(equipment_id: int | None, company_id: int) -> None:
    if equipment_id is None:
        return
    con = app_connect()
    try:
        ok = con.execute("SELECT 1 FROM equipment WHERE id = ? AND company_id = ?",
                         (equipment_id, company_id)).fetchone()
    finally:
        con.close()
    if ok is None:
        raise HTTPException(status_code=404, detail="Equipment not found")


class SessionIn(BaseModel):
    equipment_id: int | None = None
    title: str | None = None
    task_type: str = "document_qa"

    @field_validator("task_type")
    @classmethod
    def _task(cls, v: str) -> str:
        if v not in ("reasoning", "document_qa", "tool_planning", "coding"):
            raise ValueError("Unknown task type")
        return v


class MessageIn(BaseModel):
    content: str
    task_type: str = "document_qa"
    prompt_template: str = "document_qa"

    @field_validator("content")
    @classmethod
    def _content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message must not be empty")
        return v


@router.get("/models")
def get_models(sess: dict = Depends(get_current_session)):
    return {"models": list_models()}


@router.get("/health")
def ai_health(sess: dict = Depends(get_current_session)):
    h = cached_health()
    con = app_connect()
    try:
        total = con.execute("SELECT COUNT(*) FROM ai_runs WHERE company_id = ?",
                            (sess["company_id"],)).fetchone()[0]
        ok_n = con.execute("SELECT COUNT(*) FROM ai_runs WHERE company_id = ?"
                           " AND status = 'COMPLETED'", (sess["company_id"],)).fetchone()[0]
        fail_n = con.execute("SELECT COUNT(*) FROM ai_runs WHERE company_id = ?"
                             " AND status IN ('FAILED','TIMEOUT','UNAVAILABLE')",
                             (sess["company_id"],)).fetchone()[0]
        avg = con.execute("SELECT AVG(duration_ms) FROM ai_runs WHERE company_id = ?"
                          " AND duration_ms IS NOT NULL", (sess["company_id"],)).fetchone()[0]
        last_err = con.execute("SELECT error_category, created_at FROM ai_runs"
                               " WHERE company_id = ? AND error_category IS NOT NULL"
                               " ORDER BY id DESC LIMIT 1",
                               (sess["company_id"],)).fetchone()
        tools_n = con.execute("SELECT COUNT(*) FROM ai_tool_runs tr JOIN ai_runs r"
                              " ON r.id = tr.run_id WHERE r.company_id = ?",
                              (sess["company_id"],)).fetchone()[0]
    finally:
        con.close()
    provider = get_provider()
    return {"provider": provider.name, "display": provider.display_name,
            "is_test": provider.is_test, "local": provider.local,
            "status": h.get("status"), "latency_ms": h.get("latency_ms"),
            "detail": h.get("detail"), "model": h.get("model"),
            "runs_total": total, "runs_completed": ok_n, "runs_failed": fail_n,
            "avg_latency_ms": round(avg, 1) if avg else None,
            "last_error": dict(last_err) if last_err else None,
            "tool_invocations": tools_n}


@router.get("/tools")
def get_tools(sess: dict = Depends(get_current_session)):
    return {"tools": tool_registry.list_tools(sess["role"])}


@router.post("/sessions", status_code=201)
def create_session(body: SessionIn, request: Request,
                   sess: dict = Depends(get_current_session)):
    _equipment_owned(body.equipment_id, sess["company_id"])
    s = get_settings()
    routed = {"provider": get_provider().name,
              "model": s.KIMI_K3_MODEL if not get_provider().is_test else "test"}
    title = (body.title or "").strip()[:80]
    con = app_connect()
    try:
        cur = con.execute(
            "INSERT INTO ai_sessions (company_id, user_id, equipment_id, title,"
            " provider, model, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,'ACTIVE',datetime('now'),datetime('now'))",
            (sess["company_id"], sess["user_id"], body.equipment_id,
             title or "Untitled session", routed["provider"], routed["model"]))
        sid = cur.lastrowid
        con.commit()
        row = con.execute("SELECT * FROM ai_sessions WHERE id = ?", (sid,)).fetchone()
    finally:
        con.close()
    log_event("ai_session_created", {"session_id": sid},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request))
    return dict(row)


@router.get("/sessions")
def list_sessions(sess: dict = Depends(get_current_session)):
    con = app_connect()
    try:
        rows = con.execute("SELECT * FROM ai_sessions WHERE company_id = ?"
                           " AND user_id = ? ORDER BY updated_at DESC LIMIT 50",
                           (sess["company_id"], sess["user_id"])).fetchall()
    finally:
        con.close()
    return {"sessions": [dict(r) for r in rows]}


@router.get("/sessions/{session_id}")
def get_session(session_id: int, sess: dict = Depends(get_current_session)):
    own = _owned_session(session_id, sess)
    if own["user_id"] != sess["user_id"] and sess["role"] not in ("COMPANY_ADMIN",):
        raise HTTPException(status_code=404, detail="AI session not found")
    con = app_connect()
    try:
        msgs = con.execute("SELECT id, role, content, model, tool_name, created_at"
                           " FROM ai_messages WHERE session_id = ? ORDER BY id",
                           (session_id,)).fetchall()
        runs = con.execute("SELECT id, status, task_type, started_at, ended_at,"
                           " duration_ms, sources_count, tools_used, error_category"
                           " FROM ai_runs WHERE session_id = ? ORDER BY id DESC LIMIT 20",
                           (session_id,)).fetchall()
    finally:
        con.close()
    return {"session": own, "messages": [dict(m) for m in msgs],
            "runs": [dict(r) for r in runs]}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, request: Request,
                   sess: dict = Depends(get_current_session)):
    own = _owned_session(session_id, sess)
    if own["user_id"] != sess["user_id"] and sess["role"] not in ("COMPANY_ADMIN",):
        raise HTTPException(status_code=404, detail="AI session not found")
    con = app_connect()
    try:
        con.execute("DELETE FROM ai_messages WHERE session_id = ?", (session_id,))
        con.execute("DELETE FROM ai_runs WHERE session_id = ?", (session_id,))
        con.execute("DELETE FROM ai_sessions WHERE id = ?", (session_id,))
        con.commit()
    finally:
        con.close()
    log_event("ai_session_deleted", {"session_id": session_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request))
    return {"message": "AI session deleted"}


@router.post("/sessions/{session_id}/messages")
def post_message(session_id: int, body: MessageIn, request: Request,
                 sess: dict = Depends(get_current_session)):
    s = get_settings()
    if len(body.content) > s.AI_MAX_MESSAGE_CHARS:
        raise HTTPException(status_code=413,
                            detail=f"Message too long (limit {s.AI_MAX_MESSAGE_CHARS} chars)")
    _limited(sess)
    own = _owned_session(session_id, sess)
    if own["user_id"] != sess["user_id"] and sess["role"] not in ("COMPANY_ADMIN",):
        raise HTTPException(status_code=404, detail="AI session not found")
    run_sess = dict(sess)
    run_sess["equipment_id"] = own["equipment_id"]
    if own["title"] == "Untitled session":
        title = body.content.strip()[:80]
        con = app_connect()
        try:
            con.execute("UPDATE ai_sessions SET title = ? WHERE id = ?",
                        (title, session_id))
            con.commit()
        finally:
            con.close()
    orchestrator._store_message(session_id, "USER", body.content)
    try:
        result = orchestrator.execute(
            sess=run_sess, session_id=session_id, user_message=body.content,
            task_type="document_qa", prompt_template=body.prompt_template
            if body.prompt_template in dict(prompts.TEMPLATES) else "document_qa")
    except ModelUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    if result["status"] == "UNAVAILABLE":
        raise HTTPException(status_code=503, detail=result.get("error")
                            or "Local Kimi K3 is currently unavailable.")
    if result["status"] == "TIMEOUT":
        raise HTTPException(status_code=504, detail=result.get("error") or "AI timed out")
    return _public_result(result)


@router.post("/sessions/{session_id}/messages/stream")
def post_message_stream(session_id: int, body: MessageIn, request: Request,
                        sess: dict = Depends(get_current_session)):
    s = get_settings()
    if len(body.content) > s.AI_MAX_MESSAGE_CHARS:
        raise HTTPException(status_code=413,
                            detail=f"Message too long (limit {s.AI_MAX_MESSAGE_CHARS} chars)")
    _limited(sess)
    own = _owned_session(session_id, sess)
    if own["user_id"] != sess["user_id"] and sess["role"] not in ("COMPANY_ADMIN",):
        raise HTTPException(status_code=404, detail="AI session not found")
    run_sess = dict(sess)
    run_sess["equipment_id"] = own["equipment_id"]
    orchestrator._store_message(session_id, "USER", body.content)
    q: queue.Queue = queue.Queue()
    outcome: dict = {}

    def worker():
        try:
            outcome.update(orchestrator.execute(
                sess=run_sess, session_id=session_id, user_message=body.content,
                task_type="document_qa",
                prompt_template=body.prompt_template
                if body.prompt_template in dict(prompts.TEMPLATES) else "document_qa",
                on_token=lambda tok: q.put(("token", tok))))
        except Exception as e:  # noqa: BLE001 — surfaced as SSE error event
            q.put(("error", f"AI run failed ({type(e).__name__})"))
        finally:
            q.put(("done", None))

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        yield 'event: start\ndata: {"status": "RUNNING"}\n\n'
        while True:
            kind, payload = q.get()
            if kind == "token":
                yield f"event: token\ndata: {json.dumps(payload)}\n\n"
            elif kind == "error":
                yield f"event: error\ndata: {json.dumps(payload)}\n\n"
                break
            else:
                yield f"event: done\ndata: {json.dumps(_public_result(outcome))}\n\n"
                break

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _public_result(result: dict) -> dict:
    """Strip anything internal; citations + metrics stay, CoT never exists."""
    return {
        "run_id": result.get("run_id"),
        "status": result.get("status"),
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "plan": result.get("plan", []),
        "streamed": bool(result.get("streamed")),
        "prompt_template": result.get("prompt_template"),
        "prompt_version": result.get("prompt_version"),
        "duration_ms": result.get("duration_ms"),
        "sources_count": result.get("sources_count", 0),
        "tools_used": result.get("tools_used", []),
        "error": result.get("error"),
        "error_category": result.get("error_category"),
        "context_meta": result.get("context_meta"),
    }


@router.get("/runs/{run_id}")
def get_run(run_id: int, sess: dict = Depends(get_current_session)):
    run = _owned_run(run_id, sess)
    if run["user_id"] != sess["user_id"] and sess["role"] not in ("COMPANY_ADMIN",):
        raise HTTPException(status_code=404, detail="AI run not found")
    con = app_connect()
    try:
        tools = con.execute("SELECT tool_name, status, error, duration_ms, created_at"
                            " FROM ai_tool_runs WHERE run_id = ? ORDER BY id",
                            (run_id,)).fetchall()
    finally:
        con.close()
    run["tools_used"] = json.loads(run.get("tools_used") or "[]")
    return {"run": run, "tool_runs": [dict(t) for t in tools]}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: int, request: Request,
               sess: dict = Depends(get_current_session)):
    run = _owned_run(run_id, sess)
    if run["user_id"] != sess["user_id"] and sess["role"] not in ("COMPANY_ADMIN",):
        raise HTTPException(status_code=404, detail="AI run not found")
    if run["status"] in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "UNAVAILABLE"):
        return {"run_id": run_id, "status": run["status"], "cancelled": False}
    accepted = orchestrator.request_cancel(run_id)
    log_event("ai_request_cancelled", {"run_id": run_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request))
    return {"run_id": run_id, "status": run["status"], "cancelled": accepted}
