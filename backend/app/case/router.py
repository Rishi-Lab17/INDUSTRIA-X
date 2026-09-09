"""Stage 9: case management API routes."""
import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..core.deps import get_current_session, require_roles
from ..core.rate_limit import allow
from ..core.security import utcnow_iso
from ..db import connect
from ..case.service import (
    STATUSES, PRIORITIES, SEVERITIES, RESOLUTION_STATUSES,
    ACTION_TYPES, ACTION_STATUSES, OUTCOMES, MEMORY_RELIABILITY,
    MEMORY_FEEDBACK,
    create_case, list_cases, get_case, close_case, reopen_case,
    archive_case, get_timeline, get_similar_cases, add_memory,
    add_memory_feedback, add_lineage_node, add_lineage_edge,
    get_safety_center, get_sovereignty_check, get_case_integrity,
    get_dashboard_stats, _owned_case, CaseCreate, CasePatch,
    CaseCloseIn, CaseReopenIn, ActionIn, MemoryIn, MemoryFeedbackIn,
)
from ..case.report_service import get_audit_center, update_sovereignty_config

router = APIRouter(prefix="/api/case", tags=["cases"])
case_router = APIRouter(prefix="/api/case", tags=["cases"])


def _limited(sess: dict, action: str = "case") -> None:
    ok, retry = allow(f"{action}:{sess['user_id']}", 60, 60)
    if not ok:
        raise HTTPException(status_code=429, detail="Rate limit reached.",
                            headers={"Retry-After": str(retry)})


def _parse_model(parsed_model, body: dict):
    try:
        return parsed_model(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


# ---------- case CRUD ----------

@case_router.post("", status_code=201,
                  dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_case_endpoint(body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    parsed = _parse_model(CaseCreate, body)
    con = connect()
    try:
        return create_case(con, parsed, sess["company_id"], sess["user_id"])
    finally:
        con.close()


@case_router.get("")
def list_cases_endpoint(sess: dict = Depends(get_current_session),
                            status: str | None = None,
                            priority: str | None = None,
                            severity: str | None = None,
                            equipment_id: int | None = None,
                            page: int = 1, page_size: int = 20):
    if status and status not in STATUSES: raise HTTPException(status_code=422, detail="Invalid status")
    if priority and priority not in PRIORITIES: raise HTTPException(status_code=422, detail="Invalid priority")
    if severity and severity not in SEVERITIES: raise HTTPException(status_code=422, detail="Invalid severity")
    con = connect()
    try:
        return list_cases(con, sess["company_id"], status, priority, severity, equipment_id, page, page_size)
    finally:
        con.close()


# ---------- static routes MUST come before /{cid} ----------


# ---------- memory ----------

@case_router.post("/memory", status_code=201,
                  dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def add_memory_endpoint(body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    parsed = _parse_model(MemoryIn, body)
    con = connect()
    try:
        return add_memory(con, sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()


@case_router.get("/memory")
def list_memory_endpoint(sess: dict = Depends(get_current_session),
                             equipment_type: str | None = None,
                             failure_mode: str | None = None,
                             page: int = 1, page_size: int = 20):
    con = connect()
    try:
        return get_similar_cases(con, sess["company_id"], equipment_type or "", failure_mode or "", page, page_size)
    finally:
        con.close()


# ---------- audit center ----------

@case_router.get("/audit")
def audit_center_endpoint(sess: dict = Depends(get_current_session),
                              action: str | None = None,
                              entity_type: str | None = None,
                              page: int = 1, page_size: int = 100):
    con = connect()
    try:
        return get_audit_center(con, sess["company_id"], action, entity_type, page, page_size)
    finally:
        con.close()


# ---------- sovereignty ----------

@case_router.get("/sovereignty")
def sovereignty_endpoint(sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        return get_sovereignty_check(con, sess["company_id"])
    finally:
        con.close()


@case_router.put("/sovereignty")
def update_sovereignty_endpoint(body: dict, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        return update_sovereignty_config(con, sess["company_id"], body, sess["user_id"])
    finally:
        con.close()


# ---------- dashboard ----------

@case_router.get("/dashboard")
def dashboard_endpoint(sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        return get_dashboard_stats(con, sess["company_id"])
    finally:
        con.close()


# ---------- safety center ----------

@case_router.get("/safety-center")
def safety_center_endpoint(sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        return {"active_reviews": get_safety_center(con, sess["company_id"])}
    finally:
        con.close()


# ---------- case detail (dynamic) ----------

@case_router.get("/{cid}")
def get_case_endpoint(cid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        return get_case(con, cid, sess["company_id"])
    finally:
        con.close()


@case_router.patch("/{cid}",
                   dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def patch_case_endpoint(cid: int, body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    parsed = _parse_model(CasePatch, body)
    con = connect()
    try:
        c = _owned_case(con, cid, sess["company_id"])
        updates = {k: v for k, v in parsed.model_dump().items() if v is not None}
        if updates:
            con.execute("UPDATE cases SET updated_at = ?, " + ", ".join(f"{k} = ?" for k in updates) + " WHERE id = ?",
                        (utcnow_iso(), *updates.values(), cid))
            con.commit()
        result = dict(con.execute("SELECT * FROM cases WHERE id = ?", (cid,)).fetchone())
        from ..audit import log_event
        log_event("case_updated", {"case_id": cid, "changed": list(updates)},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=None, entity_type="case", entity_id=cid)
        return result
    finally:
        con.close()


@case_router.post("/{cid}/close",
                  dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def close_case_endpoint(cid: int, body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    parsed = _parse_model(CaseCloseIn, body)
    con = connect()
    try:
        return close_case(con, cid, parsed, sess["company_id"], sess["user_id"])
    finally:
        con.close()


@case_router.post("/{cid}/reopen",
                  dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def reopen_case_endpoint(cid: int, body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    parsed = _parse_model(CaseReopenIn, body)
    con = connect()
    try:
        return reopen_case(con, cid, parsed, sess["company_id"], sess["user_id"])
    finally:
        con.close()


@case_router.post("/{cid}/archive",
                  dependencies=[Depends(require_roles("COMPANY_ADMIN"))])
def archive_case_endpoint(cid: int, sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        return archive_case(con, cid, sess["company_id"], sess["user_id"])
    finally:
        con.close()


@case_router.get("/{cid}/timeline")
def timeline_endpoint(cid: int, sess: dict = Depends(get_current_session),
                         page: int = 1, page_size: int = 100):
    con = connect()
    try:
        return get_timeline(con, cid, sess["company_id"], page, page_size)
    finally:
        con.close()


@case_router.get("/{cid}/integrity")
def integrity_endpoint(cid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        return get_case_integrity(con, cid, sess["company_id"])
    finally:
        con.close()


@case_router.post("/{cid}/revisions",
                  dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_revision_endpoint(cid: int, body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        c = _owned_case(con, cid, sess["company_id"])
        revs = con.execute("SELECT COUNT(*) FROM case_revisions WHERE case_id = ?", (cid,)).fetchone()[0]
        cur = con.execute(
            "INSERT INTO case_revisions (case_id, company_id, investigation_id,"
            " revision_number, description, created_by)"
            " VALUES (?,?,?,?,?,?)",
            (cid, sess["company_id"], c["investigation_id"], revs + 1,
             body.get("description", "Manual revision"), sess["user_id"]))
        con.commit()
        from ..audit import log_event
        log_event("case_revision_created", {"case_id": cid, "revision": revs + 1},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=None, entity_type="case", entity_id=cid)
        return dict(con.execute("SELECT * FROM case_revisions WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        con.close()


# ---------- actions ----------

@case_router.post("/{cid}/actions", status_code=201,
                  dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def add_action_endpoint(cid: int, body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    parsed = _parse_model(ActionIn, body)
    con = connect()
    try:
        _owned_case(con, cid, sess["company_id"])
        cur = con.execute(
            "INSERT INTO case_actions (case_id, company_id, action_type, description,"
            " owner, priority, due_at, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cid, sess["company_id"], parsed.action_type, parsed.description,
             parsed.owner, parsed.priority, parsed.due_at or "",
             "OPEN", utcnow_iso(), utcnow_iso()))
        con.commit()
        from ..audit import log_event
        log_event("case_action_added", {"case_id": cid, "action_id": cur.lastrowid},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=None, entity_type="case", entity_id=cid)
        return dict(con.execute("SELECT * FROM case_actions WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        con.close()


@case_router.post("/memory/{mid}/feedback", status_code=201)
def memory_feedback_endpoint(mid: int, body: dict, sess: dict = Depends(get_current_session)):
    parsed = _parse_model(MemoryFeedbackIn, body)
    con = connect()
    try:
        return add_memory_feedback(con, mid, sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()


# ---------- lineage ----------

@case_router.post("/{cid}/lineage", status_code=201,
                  dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def add_lineage_node_endpoint(cid: int, body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    node_id = body.get("node_id", f"node-{cid}-{body.get('node_type', 'EVIDENCE')}-{uuid.uuid4().hex[:8]}")
    con = connect()
    try:
        return add_lineage_node(con, cid, sess["company_id"],
                                   node_id, body.get("node_type", "EVIDENCE"),
                                   body.get("label", ""), body.get("metadata", {}))
    finally:
        con.close()


@case_router.post("/{cid}/lineage/edge", status_code=201,
                  dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def add_lineage_edge_endpoint(cid: int, body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        return add_lineage_edge(con, cid, sess["company_id"],
                                   body.get("from_node", ""), body.get("to_node", ""),
                                   body.get("relation", "RELATED_TO"))
    finally:
        con.close()


@case_router.get("/{cid}/lineage")
def lineage_endpoint(cid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _owned_case(con, cid, sess["company_id"])
        nodes = con.execute("SELECT * FROM lineage_nodes WHERE case_id = ?", (cid,)).fetchall()
        return {"nodes": [dict(n) for n in nodes], "node_count": len(nodes)}
    finally:
        con.close()


# ---------- assignment ----------

@case_router.post("/{cid}/assign",
                  dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def assign_case_endpoint(cid: int, body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        c = _owned_case(con, cid, sess["company_id"])
        u = con.execute("SELECT id, role FROM users WHERE id = ? AND company_id = ?", (body["user_id"], sess["company_id"])).fetchone()
        if u is None: raise HTTPException(status_code=404, detail="User not found")
        cur = con.execute(
            "INSERT INTO case_assignments (case_id, company_id, role, assigned_to, assigned_by)"
            " VALUES (?,?,?,?,?)", (cid, sess["company_id"], body["role"], body["user_id"], sess["user_id"]))
        con.commit()
        from ..audit import log_event
        log_event("case_assigned", {"case_id": cid, "role": body["role"], "user_id": body["user_id"]},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=None, entity_type="case", entity_id=cid)
        return dict(con.execute("SELECT * FROM case_assignments WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        con.close()


# ---------- comments ----------

@case_router.post("/{cid}/comments", status_code=201)
def add_comment_endpoint(cid: int, body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        _owned_case(con, cid, sess["company_id"])
        cur = con.execute(
            "INSERT INTO comments (case_id, company_id, author_id, message, parent_id)"
            " VALUES (?,?,?,?,?)",
            (cid, sess["company_id"], sess["user_id"], body.get("message", "").strip()[:4000], body.get("parent_id") or None))
        con.commit()
        from ..audit import log_event
        log_event("case_comment_added", {"case_id": cid, "comment_id": cur.lastrowid},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=None, entity_type="case", entity_id=cid)
        return dict(con.execute("SELECT * FROM comments WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        con.close()


@case_router.get("/{cid}/comments")
def list_comments_endpoint(cid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _owned_case(con, cid, sess["company_id"])
        rows = con.execute("SELECT * FROM comments WHERE case_id = ? ORDER BY created_at", (cid,)).fetchall()
        return {"comments": [dict(r) for r in rows]}
    finally:
        con.close()


# ---------- reports ----------

@case_router.post("/{cid}/reports", status_code=201,
                  dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def generate_report_endpoint(cid: int, body: dict, sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        from ..case.report_service import generate_report
        return generate_report(con, cid, sess["company_id"], sess["user_id"], body.get("format", "PDF"))
    finally:
        con.close()


@case_router.get("/{cid}/reports")
def list_reports_endpoint(cid: int, sess: dict = Depends(get_current_session),
                              page: int = 1, page_size: int = 10):
    con = connect()
    try:
        from ..case.report_service import get_reports
        return get_reports(con, cid, sess["company_id"], page, page_size)
    finally:
        con.close()
