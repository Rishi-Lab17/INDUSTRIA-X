"""Investigation case management + evidence + timeline + assumptions +
conflicts + health + readiness + copilot.

Prefix /api/cases (Stage 6 multimodal owns /api/investigations/*).
Tenant: company_id from session; workspace filtered when given.
RBAC: create/edit/status = ADMIN+ENGINEER; evidence create = all roles
(technicians restricted to TECHNICIAN/MANUAL types); view = all roles.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from ..audit import log_event
from ..core.deps import get_current_session, require_roles
from ..core.rate_limit import allow
from ..core.security import utcnow_iso
from ..db import connect
from ..investigation.common import (ASSUMPTION_STATUSES, CATEGORIES, EVIDENCE_TYPES,
                                  SEVERITIES, STATUSES, TRANSITIONS, company_settings,
                                  default_workspace, get_owned_investigation,
                                  get_owned_workspace)

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _limited(sess: dict, action: str = "cases") -> None:
    ok, retry = allow(f"{action}:{sess['user_id']}", 60, 60)
    if not ok:
        raise HTTPException(status_code=429, detail="Rate limit reached.",
                            headers={"Retry-After": str(retry)})


def _equipment_owned(con, equipment_id: int, company_id: int) -> dict:
    row = con.execute("SELECT * FROM equipment WHERE id = ? AND company_id = ?"
                      " AND is_active = 1", (equipment_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return dict(row)


def _row_to_case(row) -> dict:
    return {k: row[k] for k in
            ("id", "company_id", "workspace_id", "equipment_id", "title",
             "problem_statement", "category", "severity", "priority", "status",
             "created_by", "assigned_to", "created_at", "updated_at", "closed_at")}


def _row_to_evidence(row) -> dict:
    d = {k: row[k] for k in
         ("id", "investigation_id", "company_id", "equipment_id", "type",
          "source", "title", "description", "content", "confidence",
          "reliability", "timestamp", "created_by", "created_at", "is_active")}
    for k in ("metadata", "provenance"):
        try:
            d[k] = json.loads(row[k] or "{}")
        except (ValueError, TypeError):
            d[k] = {}
    return d


def get_owned_hypothesis(con, hid: int, inv_id: int) -> dict:
    row = con.execute("SELECT * FROM hypotheses WHERE id = ? AND investigation_id = ?",
                      (hid, inv_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Hypothesis not found")
    return dict(row)


# ---------- workspaces ----------

class WorkspaceIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()[:64]
        if not v:
            raise ValueError("Name must not be empty")
        return v


@router.get("/workspaces")
def list_workspaces(sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        rows = con.execute("SELECT * FROM workspaces WHERE company_id = ? ORDER BY id",
                           (sess["company_id"],)).fetchall()
        if not rows:
            default_workspace(con, sess["company_id"])
            rows = con.execute("SELECT * FROM workspaces WHERE company_id = ? ORDER BY id",
                               (sess["company_id"],)).fetchall()
    finally:
        con.close()
    return {"workspaces": [dict(r) for r in rows]}


@router.post("/workspaces", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_workspace(body: WorkspaceIn, request: Request,
                     sess: dict = Depends(get_current_session)):
    _limited(sess, "cases:workspaces")
    con = connect()
    try:
        if con.execute("SELECT 1 FROM workspaces WHERE company_id = ? AND name = ?",
                       (sess["company_id"], body.name)).fetchone():
            raise HTTPException(status_code=409, detail="Workspace already exists")
        cur = con.execute("INSERT INTO workspaces (company_id, name) VALUES (?, ?)",
                          (sess["company_id"], body.name))
        con.commit()
        row = con.execute("SELECT * FROM workspaces WHERE id = ?",
                          (cur.lastrowid,)).fetchone()
    finally:
        con.close()
    log_event("workspace_created", {"workspace_id": row["id"], "name": body.name},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request))
    return dict(row)


# ---------- investigations ----------

class InvestigationIn(BaseModel):
    equipment_id: int
    workspace_id: int | None = None
    title: str
    problem_statement: str
    category: str = "UNKNOWN"
    severity: str = "MEDIUM"
    priority: int = 3
    assigned_to: int | None = None

    @field_validator("title", "problem_statement")
    @classmethod
    def _text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Must not be empty")
        return v[:2000]

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}")
        return v

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        return v

    @field_validator("priority")
    @classmethod
    def _pri(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("priority must be 1..5")
        return v


class InvestigationPatch(BaseModel):
    title: str | None = None
    problem_statement: str | None = None
    category: str | None = None
    severity: str | None = None
    priority: int | None = None
    assigned_to: int | None = None

    @field_validator("title", "problem_statement")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Must not be empty")
        return v[:2000]

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}")
        return v

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        return v

    @field_validator("priority")
    @classmethod
    def _pri(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not 1 <= v <= 5:
            raise ValueError("priority must be 1..5")
        return v


@router.post("", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_investigation(body: InvestigationIn, request: Request,
                         sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        _equipment_owned(con, body.equipment_id, sess["company_id"])
        ws_id = body.workspace_id
        if ws_id is not None:
            get_owned_workspace(con, ws_id, sess["company_id"])
        else:
            ws_id = default_workspace(con, sess["company_id"])["id"]
        assignee = None
        if body.assigned_to is not None:
            u = con.execute("SELECT id FROM users WHERE id = ? AND company_id = ?",
                            (body.assigned_to, sess["company_id"])).fetchone()
            if u is None:
                raise HTTPException(status_code=422, detail="Assignee not in company")
            assignee = body.assigned_to
        cur = con.execute(
            "INSERT INTO investigations (company_id, workspace_id, equipment_id, title,"
            " problem_statement, category, severity, priority, status, created_by,"
            " assigned_to, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,'DRAFT',?,?,?,?)",
            (sess["company_id"], ws_id, body.equipment_id, body.title,
             body.problem_statement, body.category, body.severity, body.priority,
             sess["user_id"], assignee, utcnow_iso(), utcnow_iso()))
        inv_id = cur.lastrowid
        con.commit()
        row = con.execute("SELECT * FROM investigations WHERE id = ?",
                          (inv_id,)).fetchone()
    finally:
        con.close()
    log_event("investigation_created",
              {"investigation_id": inv_id, "title": body.title,
               "equipment_id": body.equipment_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return _row_to_case(row)


@router.get("")
def list_investigations(sess: dict = Depends(get_current_session),
                        status: str | None = None,
                        equipment_id: int | None = None,
                        workspace_id: int | None = None,
                        search: str | None = None,
                        page: int = 1, page_size: int = 20):
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=422, detail="Invalid status")
    page, page_size = max(1, page), max(1, min(page_size, 100))
    q = "SELECT * FROM investigations WHERE company_id = ?"
    params: list = [sess["company_id"]]
    if status:
        q += " AND status = ?"
        params.append(status)
    if equipment_id is not None:
        q += " AND equipment_id = ?"
        params.append(equipment_id)
    if workspace_id is not None:
        q += " AND workspace_id = ?"
        params.append(workspace_id)
    if search and search.strip():
        q += " AND (title LIKE ? OR problem_statement LIKE ?)"
        params += [f"%{search.strip()}%", f"%{search.strip()}%"]
    con = connect()
    try:
        total = con.execute(f"SELECT COUNT(*) FROM ({q})", params).fetchone()[0]
        rows = con.execute(q + " ORDER BY id DESC LIMIT ? OFFSET ?",
                           (*params, page_size, (page - 1) * page_size)).fetchall()
    finally:
        con.close()
    return {"investigations": [_row_to_case(r) for r in rows],
            "total": total, "page": page, "page_size": page_size}


@router.get("/{inv_id}")
def get_investigation(inv_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        eq = con.execute("SELECT id, code, name, type, criticality, status"
                         " FROM equipment WHERE id = ?", (inv["equipment_id"],)).fetchone()
        n_ev = con.execute("SELECT COUNT(*) FROM evidence WHERE investigation_id = ?"
                           " AND is_active = 1", (inv_id,)).fetchone()[0]
        n_hyp = con.execute("SELECT COUNT(*) FROM hypotheses WHERE investigation_id = ?",
                            (inv_id,)).fetchone()[0]
    finally:
        con.close()
    return {"investigation": inv, "equipment": dict(eq) if eq else None,
            "counts": {"evidence": n_ev, "hypotheses": n_hyp}}


@router.patch("/{inv_id}",
              dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def update_investigation(inv_id: int, body: InvestigationPatch, request: Request,
                         sess: dict = Depends(get_current_session)):
    _limited(sess)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        if "assigned_to" in updates:
            u = con.execute("SELECT id FROM users WHERE id = ? AND company_id = ?",
                            (updates["assigned_to"], sess["company_id"])).fetchone()
            if u is None:
                raise HTTPException(status_code=422, detail="Assignee not in company")
        changed = sorted(updates)
        if updates:
            updates["updated_at"] = utcnow_iso()
            sets = ", ".join(f"{k} = ?" for k in updates)
            con.execute(f"UPDATE investigations SET {sets} WHERE id = ?",
                        (*updates.values(), inv_id))
            con.commit()
        row = con.execute("SELECT * FROM investigations WHERE id = ?",
                          (inv_id,)).fetchone()
    finally:
        con.close()
    if changed:
        log_event("investigation_updated",
                  {"investigation_id": inv_id, "changed": changed},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return _row_to_case(row)


class StatusIn(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _st(cls, v: str) -> str:
        if v not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        return v


@router.post("/{inv_id}/status",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def change_status(inv_id: int, body: StatusIn, request: Request,
                  sess: dict = Depends(get_current_session)):
    _limited(sess)
    from . import hypotheses as hyp_mod
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        if body.status not in TRANSITIONS.get(inv["status"], ()):
            raise HTTPException(
                status_code=422,
                detail=f"Illegal transition {inv['status']} → {body.status}")
        if body.status == "READY_FOR_VERIFICATION":
            gate = hyp_mod.readiness_for(con, inv, sess["company_id"])
            if not gate["ready"]:
                raise HTTPException(status_code=422, detail={
                    "message": "Readiness gate failed",
                    "reasons": gate["reasons"]})
        closed = utcnow_iso() if body.status in ("RESOLVED", "CLOSED") else None
        con.execute("UPDATE investigations SET status = ?, updated_at = ?,"
                    " closed_at = COALESCE(?, closed_at) WHERE id = ?",
                    (body.status, utcnow_iso(), closed, inv_id))
        con.commit()
        row = con.execute("SELECT * FROM investigations WHERE id = ?",
                          (inv_id,)).fetchone()
    finally:
        con.close()
    log_event("investigation_status_changed",
              {"investigation_id": inv_id, "from": inv["status"], "to": body.status},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return _row_to_case(row)


# ---------- evidence ----------

TECH_EVIDENCE_TYPES = ("TECHNICIAN", "MANUAL")


class EvidenceIn(BaseModel):
    type: str
    source: str = ""
    title: str
    description: str = ""
    content: str = ""
    confidence: float | None = None
    reliability: float | None = None
    timestamp: float | None = None
    metadata: dict | None = None
    provenance: dict | None = None
    link_existing: dict | None = None

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        from ..investigation.common import EVIDENCE_TYPES as _T
        if v not in _T:
            raise ValueError(f"type must be one of {_T}")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title must not be empty")
        return v.strip()[:500]

    @field_validator("confidence", "reliability")
    @classmethod
    def _score(cls, v: float | None) -> float | None:
        if v is not None and not 0.0 <= v <= 1.0:
            raise ValueError("Scores must be within 0..1")
        return v


def _resolve_link(con, link: dict | None, company_id: int) -> dict:
    """Snapshot an existing artifact (document/dataset/asset/RAG chunk) as
    evidence with real provenance. Unknown kinds/ids → 404/422."""
    if not link:
        return {}
    kind = link.get("kind")
    ref_id = link.get("id")
    if kind not in ("document", "dataset", "asset", "rag_chunk") \
            or not isinstance(ref_id, int):
        raise HTTPException(status_code=422, detail="Invalid link_existing")
    if kind == "document":
        row = con.execute("SELECT * FROM documents WHERE id = ? AND company_id = ?",
                          (ref_id, company_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Linked document not found")
        return {"type": "DOCUMENT", "title": row["original_filename"],
                "equipment_id": row["equipment_id"],
                "provenance": {"document_id": row["id"], "version": row["version"],
                               "file_name": row["original_filename"]}}
    if kind == "dataset":
        row = con.execute("SELECT * FROM sensor_datasets WHERE id = ? AND company_id = ?",
                          (ref_id, company_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Linked dataset not found")
        return {"type": "SENSOR", "title": f"Sensor dataset: {row['name']}",
                "equipment_id": row["equipment_id"],
                "provenance": {"dataset_id": row["id"], "file_name": row["source_filename"],
                               "channels": row["channels"], "row_count": row["row_count"]}}
    if kind == "asset":
        row = con.execute("SELECT * FROM vision_assets WHERE id = ? AND company_id = ?",
                          (ref_id, company_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Linked image not found")
        return {"type": "IMAGE", "title": f"Image: {row['filename']}",
                "equipment_id": row["equipment_id"],
                "provenance": {"image_id": row["id"], "file_name": row["filename"],
                               "width": row["width"], "height": row["height"]}}
    # rag_chunk: validated against the live vector store (company-scoped).
    from ..rag import store as _store
    chunk = _store.get_chunk(str(ref_id))
    if chunk is None or int(chunk["company_id"]) != int(company_id):
        raise HTTPException(status_code=404, detail="Linked chunk not found")
    return {"type": "RAG", "title": f"RAG evidence: {chunk['filename']}",
            "equipment_id": chunk["equipment_id"],
            "provenance": {"document_id": chunk["doc_id"], "chunk_id": chunk["id"],
                           "file_name": chunk["filename"], "page": chunk["page"],
                           "section": chunk["section"],
                           "version": chunk["version"]}}


@router.post("/{inv_id}/evidence", status_code=201)
def add_evidence(inv_id: int, body: EvidenceIn, request: Request,
                 sess: dict = Depends(get_current_session)):
    _limited(sess)
    if sess["role"] == "TECHNICIAN" and body.type not in TECH_EVIDENCE_TYPES:
        raise HTTPException(status_code=403,
                            detail="Technicians may only add observation evidence")
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        snap = _resolve_link(con, body.link_existing, sess["company_id"])
        etype = snap.get("type", body.type)
        title = body.title or snap.get("title", "")
        if not title:
            raise HTTPException(status_code=422, detail="Title must not be empty")
        equipment_id = snap.get("equipment_id", inv["equipment_id"])
        if equipment_id != inv["equipment_id"]:
            # Evidence must belong to the investigation's equipment.
            equipment_id = inv["equipment_id"]
        meta = dict(body.metadata or {})
        prov = {**(snap.get("provenance") or {}), **(body.provenance or {})}
        cur = con.execute(
            "INSERT INTO evidence (investigation_id, company_id, equipment_id, type,"
            " source, title, description, content, confidence, reliability,"
            " timestamp, created_by, metadata, provenance, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (inv_id, sess["company_id"], equipment_id, etype,
             body.source.strip()[:200], title, body.description.strip()[:4000],
             body.content.strip()[:20000], body.confidence, body.reliability,
             body.timestamp, sess["user_id"], json.dumps(meta), json.dumps(prov),
             utcnow_iso()))
        eid = cur.lastrowid
        con.commit()
        row = con.execute("SELECT * FROM evidence WHERE id = ?", (eid,)).fetchone()
    finally:
        con.close()
    log_event("evidence_added",
              {"investigation_id": inv_id, "evidence_id": eid, "type": etype},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return _row_to_evidence(row)


@router.get("/{inv_id}/evidence")
def list_evidence(inv_id: int, sess: dict = Depends(get_current_session),
                  type: str | None = None, search: str | None = None,
                  page: int = 1, page_size: int = 50):
    from ..investigation.common import EVIDENCE_TYPES as _T
    if type is not None and type not in _T:
        raise HTTPException(status_code=422, detail="Invalid type")
    page, page_size = max(1, page), max(1, min(page_size, 100))
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        q = "SELECT * FROM evidence WHERE investigation_id = ? AND is_active = 1"
        params: list = [inv_id]
        if type:
            q += " AND type = ?"
            params.append(type)
        if search and search.strip():
            q += " AND (title LIKE ? OR description LIKE ?)"
            params += [f"%{search.strip()}%", f"%{search.strip()}%"]
        total = con.execute(f"SELECT COUNT(*) FROM ({q})", params).fetchone()[0]
        rows = con.execute(q + " ORDER BY id LIMIT ? OFFSET ?",
                           (*params, page_size, (page - 1) * page_size)).fetchall()
    finally:
        con.close()
    return {"evidence": [_row_to_evidence(r) for r in rows],
            "total": total, "page": page, "page_size": page_size}


@router.get("/{inv_id}/evidence/{eid}")
def get_evidence(inv_id: int, eid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        row = con.execute("SELECT * FROM evidence WHERE id = ? AND investigation_id = ?",
                          (eid, inv_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Evidence not found")
    finally:
        con.close()
    return _row_to_evidence(row)


class EvidencePatch(BaseModel):
    title: str | None = None
    description: str | None = None
    content: str | None = None
    confidence: float | None = None
    reliability: float | None = None
    metadata: dict | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.strip():
            raise ValueError("Title must not be empty")
        return v.strip()[:500]

    @field_validator("confidence", "reliability")
    @classmethod
    def _score(cls, v: float | None) -> float | None:
        if v is not None and not 0.0 <= v <= 1.0:
            raise ValueError("Scores must be within 0..1")
        return v


@router.patch("/{inv_id}/evidence/{eid}")
def update_evidence(inv_id: int, eid: int, body: EvidencePatch, request: Request,
                    sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        row = con.execute("SELECT * FROM evidence WHERE id = ? AND investigation_id = ?",
                          (eid, inv_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Evidence not found")
        if sess["role"] == "TECHNICIAN" and row["created_by"] != sess["user_id"]:
            raise HTTPException(status_code=403, detail="Cannot edit others' evidence")
        if sess["role"] not in ("COMPANY_ADMIN", "ENGINEER") \
                and row["created_by"] != sess["user_id"]:
            raise HTTPException(status_code=403, detail="Insufficient role")
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if "metadata" in updates:
            updates["metadata"] = json.dumps(updates["metadata"])
        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            con.execute(f"UPDATE evidence SET {sets} WHERE id = ?",
                        (*updates.values(), eid))
            con.commit()
        row = con.execute("SELECT * FROM evidence WHERE id = ?", (eid,)).fetchone()
    finally:
        con.close()
    log_event("evidence_updated",
              {"investigation_id": inv_id, "evidence_id": eid},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return _row_to_evidence(row)


@router.post("/{inv_id}/evidence/{eid}/archive",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def archive_evidence(inv_id: int, eid: int, request: Request,
                     sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        row = con.execute("SELECT id FROM evidence WHERE id = ? AND investigation_id = ?",
                          (eid, inv_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Evidence not found")
        con.execute("UPDATE evidence SET is_active = 0 WHERE id = ?", (eid,))
        con.commit()
    finally:
        con.close()
    log_event("evidence_archived",
              {"investigation_id": inv_id, "evidence_id": eid},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return {"message": "Evidence archived"}


# ---------- timeline ----------
@router.get("/{inv_id}/timeline")
def get_timeline(inv_id: int, sess: dict = Depends(get_current_session),
                 page: int = 1, page_size: int = 100):
    page, page_size = max(1, page), max(1, min(page_size, 200))
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        rows = con.execute(
            "SELECT action, detail, user_id, created_at FROM audit_events"
            " WHERE company_id = ? AND ("
            "  (entity_type = 'investigation' AND entity_id = ?)"
            "  OR action IN ('evidence_added','evidence_updated','evidence_archived',"
            "    'hypothesis_created','hypothesis_updated','hypothesis_scored',"
            "    'evidence_linked','evidence_unlinked','recommendation_generated',"
            "    'simulation_executed','conflict_detected','conflict_resolved',"
            "    'assumption_created','assumption_updated','investigation_created',"
            "    'investigation_updated','investigation_status_changed')"
            "  AND (json_extract(detail, '$.investigation_id') = ?"
            "    OR json_extract(detail, '$.investigationId') = ?))",
            (sess["company_id"], inv_id, inv_id, inv_id)).fetchall()
        events = []
        for r in rows:
            try:
                detail = json.loads(r["detail"] or "{}")
            except (ValueError, TypeError):
                detail = {}
            events.append({"action": r["action"], "detail": detail,
                           "user_id": r["user_id"], "created_at": r["created_at"]})
        events.sort(key=lambda e: e["created_at"])
        total = len(events)
        events = events[(page - 1) * page_size:page * page_size]
    finally:
        con.close()
    return {"events": events, "total": total, "page": page, "page_size": page_size}


# ---------- assumptions ----------

class AssumptionPatch(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _st(cls, v: str) -> str:
        if v not in ASSUMPTION_STATUSES:
            raise ValueError(f"status must be one of {ASSUMPTION_STATUSES}")
        return v


@router.get("/{inv_id}/assumptions")
def list_assumptions(inv_id: int, request: Request,
                     sess: dict = Depends(get_current_session)):
    from ..investigation import copilot as copilot_mod
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        stored = [dict(r) for r in con.execute(
            "SELECT * FROM assumptions WHERE investigation_id = ? ORDER BY id",
            (inv_id,)).fetchall()]
        have = {a["text"] for a in stored}
        evidence = [dict(r) for r in con.execute(
            "SELECT * FROM evidence WHERE investigation_id = ? AND is_active = 1",
            (inv_id,)).fetchall()]
        ds_rows = con.execute(
            "SELECT d.id, d.source_filename FROM sensor_datasets d"
            " JOIN evidence e ON e.investigation_id = ?"
            " WHERE d.company_id = ? LIMIT 50",
            (inv_id, sess["company_id"])).fetchall()
        datasets = [{"name": r["source_filename"]} for r in ds_rows]
        fresh = [a for a in copilot_mod.detect_assumptions(
            evidence=evidence, datasets_meta=datasets,
            equipment_id=inv["equipment_id"]) if a["text"] not in have]
        for a in fresh:
            con.execute("INSERT INTO assumptions (investigation_id, company_id, text,"
                        " status, created_by) VALUES (?,?,?,?,?)",
                        (inv_id, sess["company_id"], a["text"], a["status"],
                         sess["user_id"]))
        if fresh:
            con.commit()
            log_event("assumption_created",
                      {"investigation_id": inv_id, "count": len(fresh)},
                      company_id=sess["company_id"], user_id=sess["user_id"],
                      ip=_ip(request),
                      entity_type="investigation", entity_id=inv_id)
        rows = con.execute("SELECT * FROM assumptions WHERE investigation_id = ?"
                           " ORDER BY id", (inv_id,)).fetchall()
    finally:
        con.close()
    return {"assumptions": [dict(r) for r in rows]}


@router.patch("/{inv_id}/assumptions/{aid}",
              dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def update_assumption(inv_id: int, aid: int, body: AssumptionPatch,
                      request: Request, sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        row = con.execute("SELECT * FROM assumptions WHERE id = ? AND investigation_id = ?",
                          (aid, inv_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Assumption not found")
        con.execute("UPDATE assumptions SET status = ?, updated_at = ? WHERE id = ?",
                    (body.status, utcnow_iso(), aid))
        con.commit()
        row = con.execute("SELECT * FROM assumptions WHERE id = ?", (aid,)).fetchone()
    finally:
        con.close()
    log_event("assumption_updated",
              {"investigation_id": inv_id, "assumption_id": aid,
               "status": body.status},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return dict(row)


# ---------- conflicts ----------

@router.get("/{inv_id}/conflicts")
def list_conflicts(inv_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        rows = con.execute("SELECT * FROM conflicts WHERE investigation_id = ?"
                           " ORDER BY id", (inv_id,)).fetchall()
    finally:
        con.close()
    return {"conflicts": [dict(r) for r in rows]}


@router.post("/{inv_id}/conflicts/refresh",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def refresh_conflicts(inv_id: int, request: Request,
                      sess: dict = Depends(get_current_session)):
    from ..investigation import copilot as copilot_mod
    from ..investigation.service import evidence_with_quality as _evq
    _limited(sess)
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        settings = company_settings(con, sess["company_id"])
        evidence = _evq(con, inv_id, settings)
        found = copilot_mod.detect_conflicts(evidence)
        existing = {(r["evidence_a_id"], r["evidence_b_id"]) for r in con.execute(
            "SELECT evidence_a_id, evidence_b_id FROM conflicts"
            " WHERE investigation_id = ?", (inv_id,)).fetchall()}
        created = 0
        for c in found:
            pair = (c["evidence_a_id"], c["evidence_b_id"])
            if pair not in existing and (pair[1], pair[0]) not in existing:
                con.execute("INSERT INTO conflicts (investigation_id, company_id,"
                            " evidence_a_id, evidence_b_id, description, recommendation)"
                            " VALUES (?,?,?,?,?,?)",
                            (inv_id, sess["company_id"], c["evidence_a_id"],
                             c["evidence_b_id"], c["description"], c["recommendation"]))
                created += 1
        con.commit()
        rows = con.execute("SELECT * FROM conflicts WHERE investigation_id = ?"
                           " ORDER BY id", (inv_id,)).fetchall()
    finally:
        con.close()
    if created:
        log_event("conflict_detected",
                  {"investigation_id": inv_id, "new": created},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return {"conflicts": [dict(r) for r in rows], "new": created}


class ConflictPatch(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _st(cls, v: str) -> str:
        if v not in ("OPEN", "RESOLVED"):
            raise ValueError("status must be OPEN or RESOLVED")
        return v


@router.patch("/{inv_id}/conflicts/{cid}",
              dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def update_conflict(inv_id: int, cid: int, body: ConflictPatch,
                    request: Request, sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        row = con.execute("SELECT * FROM conflicts WHERE id = ? AND investigation_id = ?",
                          (cid, inv_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Conflict not found")
        con.execute("UPDATE conflicts SET status = ? WHERE id = ?",
                    (body.status, cid))
        con.commit()
        row = con.execute("SELECT * FROM conflicts WHERE id = ?", (cid,)).fetchone()
    finally:
        con.close()
    if body.status == "RESOLVED":
        log_event("conflict_resolved",
                  {"investigation_id": inv_id, "conflict_id": cid},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return dict(row)


# ---------- health / readiness / copilot ----------

@router.get("/{inv_id}/health")
def investigation_health(inv_id: int, sess: dict = Depends(get_current_session)):
    from . import hypotheses as hyp_mod
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        settings = company_settings(con, sess["company_id"])
        return hyp_mod.health_for(con, inv, settings)
    finally:
        con.close()


@router.get("/{inv_id}/readiness")
def investigation_readiness(inv_id: int, sess: dict = Depends(get_current_session)):
    from . import hypotheses as hyp_mod
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        return hyp_mod.readiness_for(con, inv, sess["company_id"])
    finally:
        con.close()


class CopilotIn(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Question must not be empty")
        return v.strip()[:2000]


@router.post("/{inv_id}/copilot")
def investigation_copilot(inv_id: int, body: CopilotIn, request: Request,
                          sess: dict = Depends(get_current_session)):
    from . import hypotheses as hyp_mod
    from ..investigation import copilot as copilot_mod
    _limited(sess, "cases:copilot")
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        settings = company_settings(con, sess["company_id"])
        view = hyp_mod.full_view(con, inv, settings)
        recs = hyp_mod.stored_recommendations(con, inv_id)
        assumptions = [dict(r) for r in con.execute(
            "SELECT * FROM assumptions WHERE investigation_id = ?", (inv_id,)).fetchall()]
        conflicts = [dict(r) for r in con.execute(
            "SELECT * FROM conflicts WHERE investigation_id = ? AND status = 'OPEN'",
            (inv_id,)).fetchall()]
        health = hyp_mod.health_for(con, inv, settings)
        out = copilot_mod.answer(
            question=body.question, investigation=inv, equipment=view["equipment"],
            evidence=view["evidence"], scored=view["hypotheses"],
            missing=view["missing"], recommendations=recs,
            assumptions=assumptions, conflicts=conflicts, health=health)
    finally:
        con.close()
    return {**out, "investigation_id": inv_id}
