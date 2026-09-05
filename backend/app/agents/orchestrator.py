"""AgentOrchestrator: CREATED → PLANNING → RETRIEVING → GENERATING →
COMPLETED, with FAILED / CANCELLED / TIMEOUT / UNAVAILABLE exits.

Every run persists phase transitions, timings, tools used, sources, prompt
template version, and usage (or null). Cancellation is cooperative via a
per-run event checked between phases and during streaming. Tool calls are
bounded (AI_MAX_TOOL_CALLS_PER_RUN). No chain-of-thought is stored or
returned — only plans, evidence, answers, and metrics.
"""
import json
import threading
import time
from datetime import datetime, timezone

from ..ai import context as ctx
from ..ai import prompts
from ..ai.providers import (AIError, Generation, ModelTimeout, ModelUnavailable,
                            _Cancelled, get_provider)
from ..ai.registry import route
from ..audit import log_event
from ..core.config import get_settings
from ..db import connect as app_connect
from . import planner as planner_agent
from . import rag_agent
from . import tools as tool_registry

RUN_STATES = ("QUEUED", "RUNNING", "STREAMING", "COMPLETED", "FAILED",
              "CANCELLED", "TIMEOUT", "UNAVAILABLE")

_registry_lock = threading.Lock()
_cancel_flags: dict[int, threading.Event] = {}


def _flag(run_id: int) -> threading.Event:
    with _registry_lock:
        return _cancel_flags.setdefault(run_id, threading.Event())


def request_cancel(run_id: int) -> bool:
    with _registry_lock:
        flag = _cancel_flags.get(run_id)
    if flag is None:
        return False
    flag.set()
    return True


def _release(run_id: int) -> None:
    with _registry_lock:
        _cancel_flags.pop(run_id, None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run(*, sess: dict, session_id: int, task_type: str,
             prompt_template: str) -> int:
    s = get_settings()
    routed = route(task_type if task_type in
                   ("reasoning", "document_qa", "tool_planning", "coding")
                   else "document_qa")
    con = app_connect()
    try:
        cur = con.execute(
            "INSERT INTO ai_runs (company_id, user_id, session_id, equipment_id,"
            " provider, model, task_type, prompt_template, prompt_version,"
            " status, started_at, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sess["company_id"], sess["user_id"], session_id,
             sess.get("equipment_id"), routed["provider"], routed["model"],
             task_type, prompt_template, prompts.PROMPT_VERSION,
             "QUEUED", _now(), _now()))
        run_id = cur.lastrowid
        con.commit()
    finally:
        con.close()
    log_event("ai_request_started",
              {"run_id": run_id, "session_id": session_id, "task_type": task_type},
              company_id=sess["company_id"], user_id=sess["user_id"])
    return run_id


def _set_run(run_id: int, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    con = app_connect()
    try:
        con.execute(f"UPDATE ai_runs SET {sets} WHERE id = ?",
                    (*fields.values(), run_id))
        con.commit()
    finally:
        con.close()


def _finish(sess: dict, run_id: int, status: str, *, error_category=None,
            duration_ms=None, tokens_in=None, tokens_out=None,
            sources_count=0, tools_used=None, answer_chars=None) -> dict:
    _set_run(run_id, status=status, error_category=error_category,
             ended_at=_now(), duration_ms=duration_ms, tokens_in=tokens_in,
             tokens_out=tokens_out, sources_count=sources_count,
             tools_used=json.dumps(tools_used or []))
    if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "UNAVAILABLE"):
        log_event("ai_request_" + status.lower(),
                  {"run_id": run_id,
                   **({"error": error_category} if error_category else {}),
                   **({"answer_chars": answer_chars}
                      if answer_chars is not None else {})},
                  company_id=sess["company_id"], user_id=sess["user_id"])
    _release(run_id)
    return {"run_id": run_id, "status": status, "error_category": error_category,
            "duration_ms": duration_ms, "sources_count": sources_count,
            "tools_used": tools_used or []}


def _check_cancel(flag: threading.Event) -> None:
    if flag.is_set():
        raise _Cancelled()


def _run_with_timeout(provider, messages: list[dict], timeout_s: float,
                      flag: threading.Event, **kwargs) -> Generation:
    """Provider call bounded by timeout_s; cancellation checked after."""
    box: dict = {}

    def target():
        try:
            box["gen"] = provider.generate(
                messages=messages, timeout_s=timeout_s, cancelled=flag, **kwargs)
        except Exception as e:  # noqa: BLE001 — re-raised below by category
            box["err"] = e

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    # Join budget covers all bounded attempts (each capped by timeout_s) plus
    # connection setup and retry sleeps, with margin. A genuinely hung
    # provider still trips ModelTimeout instead of hanging the request.
    s = get_settings()
    budget = ((1 + max(0, s.KIMI_MAX_RETRIES))
              * (timeout_s + s.KIMI_CONNECT_TIMEOUT_S) + 5.0)
    worker.join(budget)
    if worker.is_alive():
        raise ModelTimeout(f"AI request timed out after {timeout_s}s")
    if "err" in box:
        raise box["err"]
    _check_cancel(flag)
    return box["gen"]


def _equipment_block(sess: dict, run_id: int) -> tuple[str, dict | None]:
    eid = sess.get("equipment_id")
    if eid is None:
        return "", None
    res = tool_registry.execute_tool(run_id=run_id, sess=sess, name="get_equipment",
                                     args={"equipment_id": eid})
    if not res.get("ok"):
        return "", None
    return ctx.build_equipment_block(res["output"]), res["output"]


def execute(*, sess: dict, session_id: int, user_message: str,
            task_type: str = "document_qa",
            prompt_template: str = "document_qa",
            on_token=None) -> dict:
    """Run one grounded turn. If on_token is given, generation streams deltas
    into it (for SSE); the returned dict is identical either way."""
    s = get_settings()
    run_id = _new_run(sess=sess, session_id=session_id, task_type=task_type,
                      prompt_template=prompt_template)
    flag = _flag(run_id)
    t0 = time.time()
    tools_used: list[str] = []
    citations: list[dict] = []
    ms = lambda: int((time.time() - t0) * 1000)  # noqa: E731
    _set_run(run_id, status="RUNNING")
    try:
        _check_cancel(flag)
        # PLANNING
        planned = planner_agent.plan(company_id=sess["company_id"],
                                     query=user_message,
                                     equipment_id=sess.get("equipment_id"))
        tools_used.append("planner")
        _check_cancel(flag)
        # RETRIEVING (tool-governed: bounded, audited, company-scoped)
        if len(tools_used) - 1 >= s.AI_MAX_TOOL_CALLS_PER_RUN:
            return {**_finish(sess, run_id, "FAILED", error_category="TOOL_DENIED",
                             duration_ms=ms(), tools_used=tools_used),
                    "answer": "", "citations": [], "plan": [],
                    "streamed": False,
                    "error": "Tool execution limit reached."}
        tool_res = tool_registry.execute_tool(
            run_id=run_id, sess=sess, name="search_knowledge_base",
            args={"query": user_message,
                  **({"equipment_id": sess["equipment_id"]}
                     if sess.get("equipment_id") else {})})
        tools_used.append("search_knowledge_base")
        if not tool_res.get("ok"):
            return _finish(sess, run_id, "FAILED", error_category="TOOL_ERROR",
                           duration_ms=ms(), tools_used=tools_used)
        rag = rag_agent.retrieve(
            company_id=sess["company_id"], query=user_message,
            equipment_id=sess.get("equipment_id"))
        citations = rag.get("citations", [])
        _check_cancel(flag)
        # GENERATING
        _set_run(run_id, status="STREAMING" if on_token is not None else "RUNNING")
        eq_block, _ = _equipment_block(sess, run_id)
        evidence = rag.get("context", "") if rag.get("status") == "OK" else ""
        system = prompts.render_system(
            "rag_answer" if evidence else prompt_template,
            equipment_block=eq_block, evidence_block=evidence)
        history = _recent_history(session_id)
        kept, meta = ctx.assemble(system=system, history=history,
                                  user_message=user_message)
        provider = get_provider()
        timeout_s = s.KIMI_K3_TIMEOUT_S
        gen_kwargs = {"evidence_count": len(citations)}
        if on_token is not None:
            text, usage = _stream_into(provider, kept, timeout_s, flag, on_token,
                                       **gen_kwargs)
            answer = text
            streamed = True
        else:
            gen = _run_with_timeout(provider, kept, timeout_s, flag, **gen_kwargs)
            answer, usage, streamed = gen.text, gen.usage, False
        tokens_in = (usage or {}).get("prompt_tokens")
        tokens_out = (usage or {}).get("completion_tokens")
        _store_message(session_id, "ASSISTANT", answer,
                       model=provider.model_name if hasattr(provider, "model_name") else None,
                       run_id=run_id)
        if rag.get("status") != "OK" and not answer.strip():
            answer = ("Insufficient evidence in the current knowledge base. "
                      "Refine the query, select equipment, or upload a relevant document.")
        return {**_finish(sess, run_id, "COMPLETED", duration_ms=ms(),
                          tokens_in=tokens_in, tokens_out=tokens_out,
                          sources_count=len(citations),
                          tools_used=tools_used, answer_chars=len(answer)),
                "answer": answer, "citations": citations,
                "plan": planned["summary"], "streamed": streamed,
                "prompt_template": prompt_template,
                "prompt_version": prompts.PROMPT_VERSION,
                "context_meta": meta}
    except _Cancelled:
        return {**_finish(sess, run_id, "CANCELLED", error_category="CANCELLED",
                          duration_ms=ms(), sources_count=len(citations),
                          tools_used=tools_used),
                "answer": "", "citations": citations, "plan": [],
                "streamed": False}
    except ModelTimeout as e:
        return {**_finish(sess, run_id, "TIMEOUT", error_category="MODEL_TIMEOUT",
                          duration_ms=ms(), sources_count=len(citations),
                          tools_used=tools_used),
                "answer": "", "citations": citations, "plan": [],
                "streamed": False, "error": str(e)}
    except ModelUnavailable as e:
        return {**_finish(sess, run_id, "UNAVAILABLE",
                          error_category="MODEL_UNAVAILABLE",
                          duration_ms=ms(), sources_count=len(citations),
                          tools_used=tools_used),
                "answer": "", "citations": citations, "plan": [],
                "streamed": False, "error": str(e)}
    except AIError as e:
        cat = getattr(e, "category", "MODEL_ERROR")
        return {**_finish(sess, run_id, "FAILED", error_category=cat,
                          duration_ms=ms(), sources_count=len(citations),
                          tools_used=tools_used),
                "answer": "", "citations": citations, "plan": [],
                "streamed": False, "error": str(e)}
    except Exception as e:  # never leak internals
        return {**_finish(sess, run_id, "FAILED", error_category="MODEL_ERROR",
                          duration_ms=ms(), sources_count=len(citations),
                          tools_used=tools_used),
                "answer": "", "citations": citations, "plan": [],
                "streamed": False, "error": f"AI run failed ({type(e).__name__})"}


def _stream_into(provider, messages, timeout_s, flag, on_token=None,
                 **kwargs) -> tuple[str, dict | None]:
    t0 = time.time()
    parts: list[str] = []
    usage = None
    try:
        for delta in provider.stream(messages=messages, timeout_s=timeout_s,
                                     cancelled=flag, **kwargs):
            parts.append(delta)
            if on_token is not None:
                try:
                    on_token(delta)
                except Exception:
                    pass
    except _Cancelled:
        raise
    except AIError:
        raise
    except Exception as e:
        raise ModelUnavailable(
            f"Local Kimi K3 is currently unavailable ({type(e).__name__})") from e
    _ = time.time() - t0
    return "".join(parts), usage


def _recent_history(session_id: int) -> list[dict]:
    s = get_settings()
    con = app_connect()
    try:
        rows = con.execute("SELECT role, content FROM ai_messages"
                           " WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                           (session_id, s.AI_MEMORY_MESSAGES)).fetchall()
        return [{"role": r["role"], "content": r["content"]}
                for r in reversed(rows)]
    finally:
        con.close()


def _store_message(session_id: int, role: str, content: str, *,
                   model=None, run_id=None, tool_name=None) -> int:
    s = get_settings()
    content = content[: s.AI_MAX_MESSAGE_CHARS * 4]
    con = app_connect()
    try:
        cur = con.execute("INSERT INTO ai_messages (session_id, role, content,"
                          " model, tool_name, run_id, created_at)"
                          " VALUES (?,?,?,?,?,?,datetime('now'))",
                          (session_id, role, content, model, tool_name, run_id))
        con.execute("UPDATE ai_sessions SET updated_at = datetime('now')"
                    " WHERE id = ?", (session_id,))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()
