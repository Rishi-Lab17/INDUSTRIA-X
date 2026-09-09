"""Stage 9: case management service — case lifecycle, memory, lineage, sovereignty."""
import json
import hashlib
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from pydantic import BaseModel, field_validator

from ..audit import log_event
from ..core.deps import get_current_session
from ..core.security import utcnow_iso
from ..db import connect
from ..investigation.common import company_settings, get_owned_investigation
from ..verification.service import _owned_verification

STATUSES = ("OPEN", "INVESTIGATING", "VERIFICATION", "SAFETY_REVIEW",
            "AWAITING_APPROVAL", "APPROVED", "ACTION_IN_PROGRESS",
            "RESOLVED", "CLOSED", "REOPENED", "ARCHIVED")

PRIORITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
SEVERITIES = ("INFORMATIONAL", "MINOR", "MODERATE", "MAJOR", "CRITICAL")
ROOT_CAUSE_CONFIDENCE = ("CONFIRMED", "PROBABLE", "UNKNOWN", "DISPUTED")
RESOLUTION_STATUSES = ("RESOLVED", "PARTIALLY_RESOLVED", "NOT_RESOLVED", "UNKNOWN")
ACTION_TYPES = ("CORRECTIVE", "PREVENTIVE")
ACTION_STATUSES = ("OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED", "BLOCKED")
OUTCOMES = ("RESOLVED", "PARTIALLY_RESOLVED", "NOT_RESOLVED", "UNKNOWN")
MEMORY_RELIABILITY = ("VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "DISPUTED")
MEMORY_FEEDBACK = ("USEFUL", "NOT_USEFUL", "INCORRECT", "NEEDS_REVIEW")


def _generate_case_number(con, company_id: int) -> str:
    year = datetime.now().strftime("%Y")
    count = con.execute(
        "SELECT COUNT(*) FROM cases WHERE company_id = ? AND strftime('%Y', opened_at) = ?",
        (company_id, year)).fetchone()[0]
    return f"INDX-{year}-{count + 1:06d}"


def _owned_case(con, cid: int, company_id: int) -> dict:
    row = con.execute("SELECT * FROM cases WHERE id = ? AND company_id = ?", (cid, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return dict(row)


def _row_to_case(row) -> dict:
    return {k: row[k] for k in
            ("id", "case_number", "company_id", "workspace_id", "investigation_id",
             "equipment_id", "title", "summary", "priority", "severity", "status",
             "root_cause", "root_cause_confidence", "root_cause_evidence",
             "resolution_status", "resolution_evidence",
             "opened_by", "closed_by", "opened_at", "resolved_at",
             "closed_at", "archived_at", "created_at", "updated_at")}


# ---------- Pydantic models ----------

class CaseCreate(BaseModel):
    investigation_id: int
    title: str
    summary: str = ""
    priority: str = "MEDIUM"
    severity: str = "INFORMATIONAL"
    equipment_id: int | None = None

    @field_validator("priority")
    @classmethod
    def _pri(cls, v: str) -> str:
        if v not in PRIORITIES: raise ValueError(f"priority must be one of {PRIORITIES}")
        return v

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str) -> str:
        if v not in SEVERITIES: raise ValueError(f"severity must be one of {SEVERITIES}")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = v.strip()
        if not v: raise ValueError("Title must not be empty")
        return v[:500]

    @field_validator("summary")
    @classmethod
    def _summary(cls, v: str) -> str:
        return v.strip()[:4000] if v else ""


class CasePatch(BaseModel):
    title: str | None = None
    summary: str | None = None
    priority: str | None = None
    severity: str | None = None
    root_cause: str | None = None
    root_cause_confidence: str | None = None
    root_cause_evidence: str | None = None

    @field_validator("root_cause_confidence")
    @classmethod
    def _rcc(cls, v: str | None) -> str | None:
        if v and v not in ROOT_CAUSE_CONFIDENCE:
            raise ValueError(f"root_cause_confidence must be one of {ROOT_CAUSE_CONFIDENCE}")
        return v


class CaseCloseIn(BaseModel):
    final_finding: str = ""
    root_cause: str = ""
    failure_mode: str = ""
    corrective_action: str = ""
    preventive_action: str = ""
    resolution_status: str = "UNKNOWN"
    resolution_evidence: str = ""
    technician_conclusion: str = ""
    reviewer_conclusion: str = ""
    final_decision: str = ""

    @field_validator("resolution_status")
    @classmethod
    def _rs(cls, v: str) -> str:
        if v not in RESOLUTION_STATUSES: raise ValueError(f"resolution_status must be one of {RESOLUTION_STATUSES}")
        return v


class CaseReopenIn(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        if not v.strip(): raise ValueError("Reason must not be empty")
        if v not in ("NEW_EVIDENCE", "PREVIOUS_CONCLUSION_CHALLENGED", "PROBLEM_RECURRED", "AUDIT_REVIEW", "CORRECTION_REQUIRED", "OTHER"):
            raise ValueError(f"reason must be one of NEW_EVIDENCE, PREVIOUS_CONCLUSION_CHALLENGED, PROBLEM_RECURRED, AUDIT_REVIEW, CORRECTION_REQUIRED, OTHER")
        return v


class ActionIn(BaseModel):
    action_type: str
    description: str
    owner: str = ""
    priority: str = "MEDIUM"
    due_at: str | None = None

    @field_validator("action_type")
    @classmethod
    def _at(cls, v: str) -> str:
        if v not in ACTION_TYPES: raise ValueError(f"action_type must be one of {ACTION_TYPES}")
        return v

    @field_validator("priority")
    @classmethod
    def _pri(cls, v: str) -> str:
        if v not in PRIORITIES: raise ValueError(f"priority must be one of {PRIORITIES}")
        return v


class MemoryIn(BaseModel):
    equipment_type: str = ""
    component: str = ""
    symptoms: str = ""
    sensor_patterns: str = ""
    visual_findings: str = ""
    failure_mode: str = ""
    root_cause: str = ""
    verified_evidence: list = []
    corrective_action: str = ""
    preventive_action: str = ""
    outcome: str = ""
    lessons: str = ""
    reliability: str = "UNVERIFIED"

    @field_validator("reliability")
    @classmethod
    def _rel(cls, v: str) -> str:
        if v not in MEMORY_RELIABILITY: raise ValueError(f"reliability must be one of {MEMORY_RELIABILITY}")
        return v


class MemoryFeedbackIn(BaseModel):
    feedback: str
    reason: str = ""

    @field_validator("feedback")
    @classmethod
    def _fb(cls, v: str) -> str:
        if v not in MEMORY_FEEDBACK: raise ValueError(f"feedback must be one of {MEMORY_FEEDBACK}")
        return v


# ---------- core service functions ----------

def create_case(con, body: CaseCreate, company_id: int, user_id: int) -> dict:
    inv = get_owned_investigation(con, body.investigation_id, company_id)
    case_number = _generate_case_number(con, company_id)
    eq_id = body.equipment_id or inv["equipment_id"]
    cur = con.execute(
        "INSERT INTO cases (case_number, company_id, workspace_id, investigation_id,"
        " equipment_id, title, summary, priority, severity, status,"
        " opened_by, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (case_number, company_id, inv["workspace_id"], body.investigation_id,
         eq_id, body.title, body.summary, body.priority, body.severity, "OPEN",
         user_id, utcnow_iso(), utcnow_iso()))
    cid = cur.lastrowid
    con.execute(
        "INSERT INTO case_closure (case_id, company_id, closure_status)"
        " VALUES (?,?,?)", (cid, company_id, "NOT_CLOSED"))
    con.execute(
        "INSERT INTO case_revisions (case_id, company_id, investigation_id,"
        " revision_number, description, created_by)"
        " VALUES (?,?,?,1,'Initial case created',?)",
        (cid, company_id, body.investigation_id, user_id))
    con.commit()
    log_event("case_created",
              {"case_id": cid, "case_number": case_number, "investigation_id": body.investigation_id},
              company_id=company_id, user_id=user_id,
              ip=None, entity_type="case", entity_id=cid)
    return dict(con.execute("SELECT * FROM cases WHERE id = ?", (cid,)).fetchone())


def list_cases(con, company_id: int, status: str | None = None,
                  priority: str | None = None, severity: str | None = None,
                  equipment_id: int | None = None, page: int = 1,
                  page_size: int = 20) -> dict:
    q = "SELECT * FROM cases WHERE company_id = ?"
    params: list = [company_id]
    if status:
        q += " AND status = ?"; params.append(status)
    if priority:
        q += " AND priority = ?"; params.append(priority)
    if severity:
        q += " AND severity = ?"; params.append(severity)
    if equipment_id:
        q += " AND equipment_id = ?"; params.append(equipment_id)
    total = con.execute(f"SELECT COUNT(*) FROM ({q})", params).fetchone()[0]
    rows = con.execute(q + " ORDER BY id DESC LIMIT ? OFFSET ?",
                       (*params, page_size, (page - 1) * page_size)).fetchall()
    return {"cases": [_row_to_case(r) for r in rows], "total": total,
            "page": page, "page_size": page_size}


def get_case(con, cid: int, company_id: int) -> dict:
    c = _owned_case(con, cid, company_id)
    inv = con.execute("SELECT * FROM investigations WHERE id = ?", (c["investigation_id"],)).fetchone() if c["investigation_id"] else None
    eq = con.execute("SELECT id, code, name, type, criticality FROM equipment WHERE id = ?", (c["equipment_id"],)).fetchone() if c["equipment_id"] else None
    closure = con.execute("SELECT * FROM case_closure WHERE case_id = ?", (cid,)).fetchone()
    return {**c, "investigation": dict(inv) if inv else None,
            "equipment": dict(eq) if eq else None,
            "closure": dict(closure) if closure else None}


def close_case(con, cid: int, body: CaseCloseIn, company_id: int, user_id: int) -> dict:
    c = _owned_case(con, cid, company_id)
    if c["status"] in ("CLOSED", "ARCHIVED"):
        raise HTTPException(status_code=422, detail="Case already closed or archived")
    closure = con.execute("SELECT * FROM case_closure WHERE case_id = ?", (cid,)).fetchone()
    if closure is None:
        raise HTTPException(status_code=404, detail="Closure record not found")
    con.execute(
        "UPDATE case_closure SET closure_status = 'CLOSED', final_finding = ?, root_cause = ?,"
        " failure_mode = ?, corrective_action = ?, preventive_action = ?,"
        " resolution_status = ?, resolution_evidence = ?, technician_conclusion = ?,"
        " reviewer_conclusion = ?, final_decision = ?, closed_by = ?, closed_at = ?"
        " WHERE case_id = ?",
        (body.final_finding, body.root_cause, body.failure_mode,
         body.corrective_action, body.preventive_action, body.resolution_status,
         body.resolution_evidence, body.technician_conclusion,
         body.reviewer_conclusion, body.final_decision, user_id, utcnow_iso(), cid))
    con.execute("UPDATE cases SET status = 'CLOSED', closed_by = ?, closed_at = ?, updated_at = ? WHERE id = ?",
                (user_id, utcnow_iso(), utcnow_iso(), cid))
    con.commit()
    log_event("case_closed", {"case_id": cid, "case_number": c["case_number"]},
              company_id=company_id, user_id=user_id,
              ip=None, entity_type="case", entity_id=cid)
    return dict(con.execute("SELECT * FROM cases WHERE id = ?", (cid,)).fetchone())


def reopen_case(con, cid: int, body: CaseReopenIn, company_id: int, user_id: int) -> dict:
    c = _owned_case(con, cid, company_id)
    if c["status"] != "CLOSED":
        raise HTTPException(status_code=422, detail="Case is not closed")
    con.execute("UPDATE cases SET status = 'REOPENED', updated_at = ? WHERE id = ?", (utcnow_iso(), cid))
    con.execute("UPDATE case_closure SET closure_status = 'REOPENED', reopened_reason = ?, reopened_by = ?, reopened_at = ? WHERE case_id = ?",
                (body.reason, user_id, utcnow_iso(), cid))
    con.commit()
    log_event("case_reopened",
              {"case_id": cid, "case_number": c["case_number"], "reason": body.reason},
              company_id=company_id, user_id=user_id,
              ip=None, entity_type="case", entity_id=cid)
    return dict(con.execute("SELECT * FROM cases WHERE id = ?", (cid,)).fetchone())


def archive_case(con, cid: int, company_id: int, user_id: int) -> dict:
    c = _owned_case(con, cid, company_id)
    con.execute("UPDATE cases SET status = 'ARCHIVED', archived_at = ?, updated_at = ? WHERE id = ?",
                (utcnow_iso(), utcnow_iso(), cid))
    con.execute("UPDATE case_closure SET closure_status = 'ARCHIVED' WHERE case_id = ?", (cid,))
    con.commit()
    log_event("case_archived", {"case_id": cid, "case_number": c["case_number"]},
              company_id=company_id, user_id=user_id,
              ip=None, entity_type="case", entity_id=cid)
    return dict(con.execute("SELECT * FROM cases WHERE id = ?", (cid,)).fetchone())


def get_timeline(con, cid: int, company_id: int, page: int = 1, page_size: int = 100) -> dict:
    c = _owned_case(con, cid, company_id)
    rows = con.execute(
        "SELECT action, detail, user_id, created_at, entity_type, entity_id FROM audit_events"
        " WHERE company_id = ? AND entity_id = ? AND entity_type = 'case'"
        " ORDER BY created_at LIMIT ? OFFSET ?",
        (company_id, cid, page_size, (page - 1) * page_size)).fetchall()
    events = []
    for r in rows:
        try: detail = json.loads(r["detail"] or "{}")
        except (ValueError, TypeError): detail = {}
        events.append({"action": r["action"], "detail": detail,
                        "user_id": r["user_id"], "created_at": r["created_at"]})
    return {"events": events, "total": len(events), "page": page, "page_size": page_size}


def get_similar_cases(con, company_id: int, equipment_type: str = "",
                         failure_mode: str = "", page: int = 1,
                         page_size: int = 10) -> dict:
    q = "SELECT * FROM case_memory WHERE company_id = ? AND reliability = 'VERIFIED'"
    params: list = [company_id]
    if equipment_type:
        q += " AND equipment_type LIKE ?"; params.append(f"%{equipment_type}%")
    if failure_mode:
        q += " AND failure_mode LIKE ?"; params.append(f"%{failure_mode}%")
    total = con.execute(f"SELECT COUNT(*) FROM ({q})", params).fetchone()[0]
    rows = con.execute(q + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                       (*params, page_size, (page - 1) * page_size)).fetchall()
    return {"memories": [dict(r) for r in rows], "total": total,
            "page": page, "page_size": page_size}


def add_memory(con, company_id: int, body: MemoryIn, user_id: int) -> dict:
    cur = con.execute(
        "INSERT INTO case_memory (company_id, equipment_type, component, symptoms,"
        " sensor_patterns, visual_findings, failure_mode, root_cause,"
        " verified_evidence, corrective_action, preventive_action,"
        " outcome, lessons, reliability, status, verified_by)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (company_id, body.equipment_type, body.component, body.symptoms,
         body.sensor_patterns, body.visual_findings, body.failure_mode,
         body.root_cause, json.dumps(body.verified_evidence),
         body.corrective_action, body.preventive_action, body.outcome,
         body.lessons, body.reliability, "DRAFT", user_id))
    con.commit()
    log_event("case_memory_created",
              {"memory_id": cur.lastrowid, "company_id": company_id},
              company_id=company_id, user_id=user_id,
              ip=None, entity_type="case_memory", entity_id=cur.lastrowid)
    return dict(con.execute("SELECT * FROM case_memory WHERE id = ?", (cur.lastrowid,)).fetchone())


def add_memory_feedback(con, memory_id: int, company_id: int,
                           body: MemoryFeedbackIn, user_id: int) -> dict:
    row = con.execute("SELECT * FROM case_memory WHERE id = ? AND company_id = ?", (memory_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    cur = con.execute(
        "INSERT INTO case_memory_feedback (memory_id, company_id, user_id, feedback, reason)"
        " VALUES (?,?,?,?,?)", (memory_id, company_id, user_id, body.feedback, body.reason))
    con.commit()
    return dict(con.execute("SELECT * FROM case_memory_feedback WHERE id = ?", (cur.lastrowid,)).fetchone())


def add_lineage_node(con, case_id: int, company_id: int, node_id: str,
                        node_type: str, label: str, metadata: dict = {}) -> dict:
    row = con.execute("SELECT id FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if row:
        raise HTTPException(status_code=409, detail="Lineage node already exists")
    cur = con.execute(
        "INSERT INTO lineage_nodes (case_id, company_id, node_id, node_type, label,"
        " metadata, created_at) VALUES (?,?,?,?,?,?,?)",
        (case_id, company_id, node_id, node_type, label, json.dumps(metadata), utcnow_iso()))
    con.commit()
    return dict(con.execute("SELECT * FROM lineage_nodes WHERE id = ?", (cur.lastrowid,)).fetchone())


def add_lineage_edge(con, case_id: int, company_id: int, from_node: str,
                        to_node: str, relation: str) -> dict:
    from_row = con.execute("SELECT id FROM lineage_nodes WHERE node_id = ?", (from_node,)).fetchone()
    to_row = con.execute("SELECT id FROM lineage_nodes WHERE node_id = ?", (to_node,)).fetchone()
    if from_row is None or to_row is None:
        raise HTTPException(status_code=404, detail="Lineage node not found")
    con.execute(
        "UPDATE lineage_nodes SET downstream_node_ids = CASE WHEN id = ? THEN"
        " json_insert(downstream_node_ids, '$[#]', ?) ELSE downstream_node_ids END"
        " WHERE node_id = ?", (from_row["id"], to_node, from_row["id"]))
    con.execute(
        "UPDATE lineage_nodes SET upstream_node_ids = CASE WHEN id = ? THEN"
        " json_insert(upstream_node_ids, '$[#]', ?) ELSE upstream_node_ids END"
        " WHERE node_id = ?", (to_row["id"], from_node, to_row["id"]))
    con.commit()
    return {"from": from_node, "to": to_node, "relation": relation}


def get_safety_center(con, company_id: int) -> int:
    return con.execute(
        "SELECT COUNT(*) as active_reviews FROM verifications WHERE company_id = ? AND status IN ('IN_REVIEW','INSPECTION_REQUIRED','AWAITING_EVIDENCE','SAFETY_REVIEW','AWAITING_APPROVAL')",
        (company_id,)).fetchone()[0]


def get_sovereignty_check(con, company_id: int) -> dict:
    config = con.execute("SELECT * FROM sovereignty_config WHERE company_id = ?", (company_id,)).fetchone()
    if config is None:
        con.execute(
            "INSERT INTO sovereignty_config (company_id, data_residency, external_ai_policy,"
            " external_network_policy, vector_db_location, document_storage,"
            " encryption_status, retention_documents, retention_evidence,"
            " retention_reports, retention_audit, retention_memory)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (company_id, "UNKNOWN", "BLOCKED", "DISABLED", "LOCAL", "LOCAL",
             "NOT_CONFIGURED", "UNCONFIGURED", "UNCONFIGURED",
             "UNCONFIGURED", "UNCONFIGURED", "UNCONFIGURED"))
        con.commit()
        config = con.execute("SELECT * FROM sovereignty_config WHERE company_id = ?", (company_id,)).fetchone()
    checks = con.execute("SELECT * FROM sovereignty_health WHERE company_id = ?", (company_id,)).fetchall()
    overall = "PASS"
    for ch in checks:
        if ch["status"] == "BLOCKED":
            overall = "BLOCKED"
            break
        elif ch["status"] == "WARNING" and overall != "BLOCKED":
            overall = "WARNING"
    return {"status": overall, "config": dict(config), "checks": [dict(c) for c in checks]}


def get_case_integrity(con, cid: int, company_id: int) -> dict:
    c = _owned_case(con, cid, company_id)
    issues: list[str] = []
    if c["investigation_id"]:
        inv = con.execute("SELECT id FROM investigations WHERE id = ? AND company_id = ?", (c["investigation_id"], company_id)).fetchone()
        if inv is None: issues.append("Investigation reference broken")
    if c["equipment_id"]:
        eq = con.execute("SELECT id FROM equipment WHERE id = ? AND company_id = ?", (c["equipment_id"], company_id)).fetchone()
        if eq is None: issues.append("Equipment reference broken")
    closure = con.execute("SELECT * FROM case_closure WHERE case_id = ?", (cid,)).fetchone()
    if closure is None: issues.append("Missing closure record")
    status = "PASS" if not issues else ("WARNING" if len(issues) < 3 else "ERROR")
    return {"case_id": cid, "case_number": c["case_number"],
            "status": status, "issues": issues,
            "investigation_exists": c["investigation_id"] is None or inv is not None if c["investigation_id"] else True,
            "equipment_exists": c["equipment_id"] is None or eq is not None if c["equipment_id"] else True,
            "closure_exists": closure is not None}


def get_dashboard_stats(con, company_id: int) -> dict:
    by_status = {}
    for st in STATUSES:
        by_status[st] = con.execute("SELECT COUNT(*) FROM cases WHERE company_id = ? AND status = ?", (company_id, st)).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM cases WHERE company_id = ?", (company_id,)).fetchone()[0]
    memory_count = con.execute("SELECT COUNT(*) FROM case_memory WHERE company_id = ? AND reliability = 'VERIFIED'", (company_id,)).fetchone()[0]
    report_count = con.execute("SELECT COUNT(*) FROM reports WHERE company_id = ?", (company_id,)).fetchone()[0]
    return {"total_cases": total, "by_status": by_status,
            "verified_memory": memory_count, "reports": report_count}


def update_sovereignty_config(con, company_id: int, body: dict, user_id: int) -> dict:
    existing = con.execute("SELECT id FROM sovereignty_config WHERE company_id = ?", (company_id,)).fetchone()
    if existing:
        con.execute("UPDATE sovereignty_config SET data_residency = ?, external_ai_policy = ?,"
                    " external_network_policy = ?, vector_db_location = ?, document_storage = ?,"
                    " encryption_status = ?, retention_documents = ?, retention_evidence = ?,"
                    " retention_reports = ?, retention_audit = ?, retention_memory = ?,"
                    " backup_enabled = ?, audit_enabled = ?, updated_at = ? WHERE company_id = ?",
                    (body.get("data_residency", "UNKNOWN"), body.get("external_ai_policy", "BLOCKED"),
                     body.get("external_network_policy", "DISABLED"), body.get("vector_db_location", "LOCAL"),
                     body.get("document_storage", "LOCAL"), body.get("encryption_status", "NOT_CONFIGURED"),
                     body.get("retention_documents", "UNCONFIGURED"), body.get("retention_evidence", "UNCONFIGURED"),
                     body.get("retention_reports", "UNCONFIGURED"), body.get("retention_audit", "UNCONFIGURED"),
                     body.get("retention_memory", "UNCONFIGURED"), body.get("backup_enabled", 0),
                     body.get("audit_enabled", 1), utcnow_iso(), company_id))
    else:
        con.execute(
            "INSERT INTO sovereignty_config (company_id, data_residency, external_ai_policy,"
            " external_network_policy, vector_db_location, document_storage,"
            " encryption_status, retention_documents, retention_evidence,"
            " retention_reports, retention_audit, retention_memory, backup_enabled, audit_enabled)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (company_id, body.get("data_residency", "UNKNOWN"), body.get("external_ai_policy", "BLOCKED"),
             body.get("external_network_policy", "DISABLED"), body.get("vector_db_location", "LOCAL"),
             body.get("document_storage", "LOCAL"), body.get("encryption_status", "NOT_CONFIGURED"),
             body.get("retention_documents", "UNCONFIGURED"), body.get("retention_evidence", "UNCONFIGURED"),
             body.get("retention_reports", "UNCONFIGURED"), body.get("retention_audit", "UNCONFIGURED"),
             body.get("retention_memory", "UNCONFIGURED"), body.get("backup_enabled", 0),
             body.get("audit_enabled", 1)))
    con.commit()
    log_event("sovereignty_config_updated", {"company_id": company_id},
              company_id=company_id, user_id=user_id,
              ip=None, entity_type="sovereignty", entity_id=company_id)
    return dict(con.execute("SELECT * FROM sovereignty_config WHERE company_id = ?", (company_id,)).fetchone())
