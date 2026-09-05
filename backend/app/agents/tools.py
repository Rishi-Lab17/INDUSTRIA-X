"""Allowlisted server-side tool registry. The model NEVER touches filesystem,
shell, SQL, network, or Python — it only proposes (name, arguments); THIS
module validates, authorizes (company scope + ownership + role), executes via
existing internal services, bounds outputs, and audits every call/denial."""
import json
import time

from ..audit import log_event
from ..db import connect as app_connect

MAX_OUTPUT_CHARS = 4000


class ToolDenied(Exception):
    pass


class ToolError(Exception):
    pass


def _company_of(sess: dict) -> int:
    return int(sess["company_id"])


def _equipment_owned(equipment_id: int, company_id: int) -> dict | None:
    con = app_connect()
    try:
        row = con.execute("SELECT * FROM equipment WHERE id = ? AND company_id = ?",
                          (equipment_id, company_id)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def _doc_owned(doc_id: int, company_id: int) -> dict | None:
    con = app_connect()
    try:
        row = con.execute("SELECT * FROM documents WHERE id = ? AND company_id = ?",
                          (doc_id, company_id)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def _as_int(value, field: str, *, lo: int = 1, hi: int = 2_000_000_000) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ToolDenied(f"Invalid {field}")
    if not (lo <= v <= hi):
        raise ToolDenied(f"Invalid {field}")
    return v


def _as_text(value, field: str, *, max_len: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolDenied(f"Invalid {field}")
    return value.strip()[:max_len]


def tool_search_knowledge_base(sess: dict, args: dict) -> dict:
    from ..rag.retrieval import hybrid_search
    query = _as_text(args.get("query"), "query")
    equipment_id = args.get("equipment_id")
    if equipment_id is not None:
        equipment_id = _as_int(equipment_id, "equipment_id")
        if _equipment_owned(equipment_id, _company_of(sess)) is None:
            raise ToolDenied("Equipment not found")
    res = hybrid_search(company_id=_company_of(sess), query=query,
                        equipment_id=equipment_id, top_k=6)
    cites = []
    for c in res.get("citations", []):
        cites.append({k: c.get(k) for k in
                      ("document_id", "document_version", "chunk_id", "filename",
                       "page", "section", "equipment_id", "excerpt",
                       "combined_score", "retrieval_method")})
    return {"status": res["status"], "citations": cites,
            "count": res.get("count", 0)}


def tool_get_equipment(sess: dict, args: dict) -> dict:
    eid = _as_int(args.get("equipment_id"), "equipment_id")
    eq = _equipment_owned(eid, _company_of(sess))
    if eq is None:
        raise ToolDenied("Equipment not found")
    eq.pop("created_by", None)
    return eq


def tool_get_equipment_history(sess: dict, args: dict) -> dict:
    eid = _as_int(args.get("equipment_id"), "equipment_id")
    if _equipment_owned(eid, _company_of(sess)) is None:
        raise ToolDenied("Equipment not found")
    con = app_connect()
    try:
        rows = con.execute(
            "SELECT action, detail, created_at FROM audit_events"
            " WHERE company_id = ? AND entity_type = 'equipment' AND entity_id = ?"
            " ORDER BY id DESC LIMIT 20",
            (_company_of(sess), eid)).fetchall()
    finally:
        con.close()
    return {"equipment_id": eid, "events": [dict(r) for r in rows]}


def tool_get_document_metadata(sess: dict, args: dict) -> dict:
    did = _as_int(args.get("document_id"), "document_id")
    doc = _doc_owned(did, _company_of(sess))
    if doc is None:
        raise ToolDenied("Document not found")
    doc.pop("extracted_text", None)
    return doc


def tool_get_document_excerpt(sess: dict, args: dict) -> dict:
    did = _as_int(args.get("document_id"), "document_id")
    doc = _doc_owned(did, _company_of(sess))
    if doc is None:
        raise ToolDenied("Document not found")
    text = (doc.get("extracted_text") or "")[:MAX_OUTPUT_CHARS]
    return {"document_id": did, "filename": doc["original_filename"],
            "excerpt": text, "truncated": len(doc.get("extracted_text") or "") > MAX_OUTPUT_CHARS}


def tool_get_system_health(sess: dict, args: dict) -> dict:
    from ..rag import service as rag_service
    from ..ai.registry import cached_health
    h = cached_health()
    return {"backend": "ONLINE",
            "ai_provider": h.get("status", "UNKNOWN"),
            "documents_ready": rag_service.knowledge_health(
                _company_of(sess)).get("documents_ready")}


def tool_get_current_ai_status(sess: dict, args: dict) -> dict:
    from ..ai.registry import list_models
    models = list_models()
    m = models[0] if models else {}
    return {"provider": m.get("provider"), "model": m.get("id"),
            "status": m.get("status"), "local": m.get("local"),
            "is_test": m.get("is_test")}


TOOLS = {
    "search_knowledge_base": {
        "fn": tool_search_knowledge_base,
        "description": "Search the company's private indexed documents (RAG).",
        "roles": ("COMPANY_ADMIN", "ENGINEER", "TECHNICIAN"),
    },
    "get_equipment": {
        "fn": tool_get_equipment,
        "description": "Read an owned equipment record.",
        "roles": ("COMPANY_ADMIN", "ENGINEER", "TECHNICIAN"),
    },
    "get_equipment_history": {
        "fn": tool_get_equipment_history,
        "description": "Read audit history of an owned equipment record.",
        "roles": ("COMPANY_ADMIN", "ENGINEER", "TECHNICIAN"),
    },
    "get_document_metadata": {
        "fn": tool_get_document_metadata,
        "description": "Read metadata of an owned document (no full text).",
        "roles": ("COMPANY_ADMIN", "ENGINEER", "TECHNICIAN"),
    },
    "get_document_excerpt": {
        "fn": tool_get_document_excerpt,
        "description": "Read a bounded excerpt of an owned document.",
        "roles": ("COMPANY_ADMIN", "ENGINEER", "TECHNICIAN"),
    },
    "get_system_health": {
        "fn": tool_get_system_health,
        "description": "Safe subset of system health (no secrets).",
        "roles": ("COMPANY_ADMIN", "ENGINEER"),
    },
    "get_current_ai_status": {
        "fn": tool_get_current_ai_status,
        "description": "Current AI provider/model status snapshot.",
        "roles": ("COMPANY_ADMIN", "ENGINEER", "TECHNICIAN"),
    },
}


def list_tools(role: str) -> list[dict]:
    return [{"name": n, "description": t["description"]}
            for n, t in TOOLS.items() if role in t["roles"]]


def execute_tool(*, run_id: int, sess: dict, name: str, args: dict) -> dict:
    """Validate → authorize → execute → audit. Returns {ok, output|error}."""
    t0 = time.time()
    spec = TOOLS.get(name)
    if spec is None:
        _audit_tool(sess, run_id, name, args, "denied", "unknown tool")
        _record_tool_run(run_id, name, args, "denied", "unknown tool", 0)
        return {"ok": False, "error": "Unknown tool", "denied": True}
    if sess.get("role") not in spec["roles"]:
        _audit_tool(sess, run_id, name, args, "denied", "role not permitted")
        _record_tool_run(run_id, name, args, "denied", "role not permitted", 0)
        return {"ok": False, "error": "Tool not permitted for this role",
                "denied": True}
    if not isinstance(args, dict) or len(json.dumps(args)) > 4000:
        _audit_tool(sess, run_id, name, {}, "denied", "invalid arguments")
        _record_tool_run(run_id, name, {}, "denied", "invalid arguments", 0)
        return {"ok": False, "error": "Invalid tool arguments", "denied": True}
    try:
        out = spec["fn"](sess, args)
    except ToolDenied as e:
        _audit_tool(sess, run_id, name, args, "denied", str(e))
        _record_tool_run(run_id, name, args, "denied", str(e), 0)
        return {"ok": False, "error": str(e), "denied": True}
    except Exception as e:
        _audit_tool(sess, run_id, name, args, "error", type(e).__name__)
        _record_tool_run(run_id, name, args, "error", type(e).__name__, 0)
        return {"ok": False, "error": "Tool execution failed"}
    ms = int((time.time() - t0) * 1000)
    _audit_tool(sess, run_id, name, args, "ok", None)
    _record_tool_run(run_id, name, args, "ok", None, ms)
    return {"ok": True, "output": out, "duration_ms": ms}


def _audit_tool(sess, run_id, name, args, outcome, error):
    detail = {"run_id": run_id, "tool": name,
              "arg_keys": sorted(args) if isinstance(args, dict) else []}
    if error:
        detail["error"] = error
    log_event("ai_tool_denied" if outcome == "denied" else "ai_tool_invoked",
              detail, company_id=sess.get("company_id"),
              user_id=sess.get("user_id"))


def _record_tool_run(run_id, name, args, status, error, ms):
    con = app_connect()
    try:
        keys = sorted(args) if isinstance(args, dict) else []
        con.execute("INSERT INTO ai_tool_runs (run_id, tool_name, input_json,"
                    " status, error, duration_ms, created_at)"
                    " VALUES (?,?,?,?,?,?,datetime('now'))",
                    (run_id, name, json.dumps({"arg_keys": keys}),
                     status, error, ms))
        con.commit()
    finally:
        con.close()
