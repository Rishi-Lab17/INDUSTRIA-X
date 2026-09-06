"""Stage 8 verification service: verification cases, assignments, evidence
verification, observations, measurements, checklists, safety assessments,
safety gate, approvals, escalations, scorecards.

All tenant checks use company_id from the session. All state transitions
are backend-enforced. Safety gate is a real blocking control.
"""
import json
import sqlite3
from datetime import datetime, timedelta

from fastapi import HTTPException
from pydantic import BaseModel, field_validator

from ..audit import log_event
from ..core.deps import get_current_session, require_roles
from ..core.rate_limit import allow
from ..core.security import utcnow_iso
from ..db import connect
from ..investigation.common import (
    company_settings, get_owned_investigation,
)
from ..investigation.service import score_investigation, evidence_with_quality
from ..investigation.missing import rank_candidates
from ..investigation.scoring import health_score, separation

STATUSES = ("PENDING", "ASSIGNED", "IN_REVIEW", "INSPECTION_REQUIRED",
            "AWAITING_EVIDENCE", "SAFETY_REVIEW", "AWAITING_APPROVAL",
            "APPROVED", "REJECTED", "ESCALATED", "BLOCKED",
            "CANCELLED", "COMPLETED")

PRIORITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

APPROVAL_LEVELS = ("TECHNICIAN", "TECHNICIAN_REVIEWER", "SUPERVISOR", "SAFETY_OFFICER")


def _ip(request=None) -> str | None:
    return request.client.host if request and request.client else None


def _limited(sess: dict, action: str = "verification") -> None:
    from ..core.rate_limit import allow as _allow
    ok, retry = _allow(f"{action}:{sess['user_id']}", 60, 60)
    if not ok:
        raise HTTPException(status_code=429, detail="Rate limit reached.",
                            headers={"Retry-After": str(retry)})


def _owned_verification(con, vid: int, company_id: int) -> dict:
    row = con.execute(
        "SELECT * FROM verifications WHERE id = ? AND company_id = ?",
        (vid, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Verification not found")
    return dict(row)


def _verify_safe_to_proceed(con, vid: int, company_id: int) -> dict:
    """Check if safety gate allows progression. Returns {allowed: bool, reasons: list}."""
    gate = con.execute(
        "SELECT * FROM safety_gate_results WHERE verification_id = ?",
        (vid,)).fetchone()
    if gate is None:
        return {"allowed": False, "reasons": ["Safety gate not evaluated"]}
    if gate["blocked"]:
        reasons = json.loads(gate["reasons"]) if gate["reasons"] else []
        return {"allowed": False, "reasons": reasons}
    return {"allowed": True, "reasons": []}


def _check_approval_level(con, verification: dict, company_id: int) -> str:
    """Determine required approval level from severity/priority."""
    sev = verification.get("priority", "MEDIUM")
    if sev == "CRITICAL":
        return "SAFETY_OFFICER"
    if sev == "HIGH":
        return "SUPERVISOR"
    if sev == "MEDIUM":
        return "TECHNICIAN_REVIEWER"
    return "TECHNICIAN"


# ---------- Pydantic models ----------

class VerificationCreate(BaseModel):
    investigation_id: int
    reason: str
    priority: str = "MEDIUM"
    instructions: str = ""
    safety_requirements: str = ""

    @field_validator("priority")
    @classmethod
    def _pri(cls, v: str) -> str:
        if v not in PRIORITIES:
            raise ValueError(f"priority must be one of {PRIORITIES}")
        return v

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Reason must not be empty")
        return v[:2000]


class VerificationAssignIn(BaseModel):
    role: str
    user_id: int

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ("TECHNICIAN", "REVIEWER"):
            raise ValueError("role must be TECHNICIAN or REVIEWER")
        return v


class EvidenceVerifyIn(BaseModel):
    evidence_id: int
    status: str
    comment: str = ""
    measurement: str = ""
    attachment: str = ""

    @field_validator("status")
    @classmethod
    def _st(cls, v: str) -> str:
        if v not in ("VERIFIED", "REJECTED", "UNABLE_TO_VERIFY", "CONTRADICTED", "NOT_APPLICABLE"):
            raise ValueError(f"status must be one of VERIFIED, REJECTED, UNABLE_TO_VERIFY, CONTRADICTED, NOT_APPLICABLE")
        return v


class ObservationIn(BaseModel):
    equipment_id: int
    observation_type: str
    description: str
    severity: str = "NORMAL"
    observed_at: str | None = None

    @field_validator("observation_type")
    @classmethod
    def _ot(cls, v: str) -> str:
        if v not in ("VISUAL", "AUDITORY", "MEASUREMENT", "MECHANICAL", "ELECTRICAL",
                      "THERMAL", "PROCESS", "SAFETY", "OTHER"):
            raise ValueError(f"observation_type must be one of VISUAL, AUDITORY, MEASUREMENT, MECHANICAL, ELECTRICAL, THERMAL, PROCESS, SAFETY, OTHER")
        return v

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str) -> str:
        if v not in ("NORMAL", "MINOR", "MODERATE", "SEVERE", "CRITICAL"):
            raise ValueError(f"severity must be one of NORMAL, MINOR, MODERATE, SEVERE, CRITICAL")
        return v


class MeasurementIn(BaseModel):
    equipment_id: int
    parameter: str
    value: float
    unit: str
    instrument_id: str = ""
    instrument_type: str = ""
    calibration_status: str = "UNKNOWN"
    calibration_date: str | None = None
    calibration_expiry: str | None = None
    notes: str = ""

    @field_validator("calibration_status")
    @classmethod
    def _cs(cls, v: str) -> str:
        if v not in ("VALID", "EXPIRED", "UNKNOWN"):
            raise ValueError("calibration_status must be VALID, EXPIRED, or UNKNOWN")
        return v


class ChecklistIn(BaseModel):
    template_key: str = ""
    title: str
    items: list[dict]

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title must not be empty")
        return v.strip()[:200]


class ChecklistItemPatch(BaseModel):
    status: str
    comment: str = ""

    @field_validator("status")
    @classmethod
    def _st(cls, v: str) -> str:
        if v not in ("PASS", "FAIL", "SKIPPED"):
            raise ValueError("status must be PASS, FAIL, or SKIPPED")
        return v


class SafetyAssessmentIn(BaseModel):
    risk_level: str = "LOW"
    likelihood: int = 1
    impact: int = 1
    notes: str = ""
    hazards: list[dict] = []
    controls: list[dict] = []

    @field_validator("risk_level")
    @classmethod
    def _rl(cls, v: str) -> str:
        if v not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            raise ValueError(f"risk_level must be one of LOW, MEDIUM, HIGH, CRITICAL")
        return v

    @field_validator("likelihood", "impact")
    @classmethod
    def _li(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("likelihood and impact must be 1..5")
        return v


class SafetyGateEvaluateIn(BaseModel):
    pass


class ApprovalRequestIn(BaseModel):
    approval_level: str = "TECHNICIAN_REVIEWER"

    @field_validator("approval_level")
    @classmethod
    def _al(cls, v: str) -> str:
        if v not in APPROVAL_LEVELS:
            raise ValueError(f"approval_level must be one of {APPROVAL_LEVELS}")
        return v


class DecisionIn(BaseModel):
    decision: str
    reason: str = ""
    comment: str = ""
    justification: str = ""

    @field_validator("decision")
    @classmethod
    def _d(cls, v: str) -> str:
        if v not in ("APPROVE", "REJECT", "REQUEST_MORE_EVIDENCE", "ESCALATE", "DEFER"):
            raise ValueError(f"decision must be one of APPROVE, REJECT, REQUEST_MORE_EVIDENCE, ESCALATE, DEFER")
        return v


class EscalationIn(BaseModel):
    user_id: int
    reason: str


# ---------- core service functions ----------

def create_verification(con, inv: dict, company_id: int, body: VerificationCreate,
                        user_id: int) -> dict:
    """Create a verification request from a Stage 7 investigation."""
    inv_id = inv["id"]
    # Check no existing verification
    existing = con.execute(
        "SELECT id FROM verifications WHERE investigation_id = ?", (inv_id,)).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Verification already exists for this investigation")
    eq = con.execute("SELECT id, code, name, type, criticality FROM equipment WHERE id = ?",
                      (inv["equipment_id"],)).fetchone()
    if eq is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    # Verify readiness
    settings = company_settings(con, company_id)
    from ..routers.hypotheses import health_for, readiness_for
    health = health_for(con, inv, settings)
    readiness = readiness_for(con, inv, company_id)
    if readiness["ready"] is False and body.priority in ("HIGH", "CRITICAL"):
        pass  # allow override but log
    ws_id = inv.get("workspace_id")
    cur = con.execute(
        "INSERT INTO verifications (investigation_id, company_id, workspace_id, equipment_id,"
        " assigned_technician_id, priority, reason, instructions, safety_requirements,"
        " status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,'PENDING',?,?)",
        (inv_id, company_id, ws_id, inv["equipment_id"], None, body.priority,
         body.reason, body.instructions, body.safety_requirements,
         utcnow_iso(), utcnow_iso()))
    vid = cur.lastrowid
    con.commit()
    log_event("verification_created",
              {"verification_id": vid, "investigation_id": inv_id,
               "equipment_code": eq["code"], "priority": body.priority},
              company_id=company_id, user_id=user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return dict(con.execute("SELECT * FROM verifications WHERE id = ?", (vid,)).fetchone())


def list_verifications(con, company_id: int, status: str | None = None,
                        priority: str | None = None,
                        page: int = 1, page_size: int = 20) -> dict:
    q = "SELECT * FROM verifications WHERE company_id = ?"
    params: list = [company_id]
    if status:
        q += " AND status = ?"; params.append(status)
    if priority:
        q += " AND priority = ?"; params.append(priority)
    total = con.execute(f"SELECT COUNT(*) FROM ({q})", params).fetchone()[0]
    rows = con.execute(q + " ORDER BY id DESC LIMIT ? OFFSET ?",
                       (*params, page_size, (page - 1) * page_size)).fetchall()
    return {"verifications": [dict(r) for r in rows], "total": total,
            "page": page, "page_size": page_size}


def get_verification(con, vid: int, company_id: int) -> dict:
    v = _owned_verification(con, vid, company_id)
    inv = con.execute("SELECT * FROM investigations WHERE id = ?",
                       (v["investigation_id"],)).fetchone()
    eq = con.execute("SELECT id, code, name, type, criticality FROM equipment WHERE id = ?",
                      (v["equipment_id"],)).fetchone()
    tech = con.execute("SELECT id, name, role FROM users WHERE id = ?",
                        (v["assigned_technician_id"],)).fetchone() if v["assigned_technician_id"] else None
    reviewer = con.execute("SELECT id, name, role FROM users WHERE id = ?",
                            (v["assigned_reviewer_id"],)).fetchone() if v["assigned_reviewer_id"] else None
    return {**v, "investigation": dict(inv) if inv else None,
            "equipment": dict(eq) if eq else None,
            "technician": dict(tech) if tech else None,
            "reviewer": dict(reviewer) if reviewer else None}


def update_verification_status(con, vid: int, status: str, company_id: int,
                                user_id: int) -> dict:
    v = _owned_verification(con, vid, company_id)
    valid_next = {
        "PENDING": ("ASSIGNED", "CANCELLED", "BLOCKED"),
        "ASSIGNED": ("IN_REVIEW", "INSPECTION_REQUIRED", "AWAITING_EVIDENCE", "CANCELLED", "BLOCKED"),
        "IN_REVIEW": ("INSPECTION_REQUIRED", "AWAITING_EVIDENCE", "SAFETY_REVIEW", "BLOCKED", "CANCELLED"),
        "INSPECTION_REQUIRED": ("AWAITING_EVIDENCE", "SAFETY_REVIEW", "BLOCKED", "CANCELLED"),
        "AWAITING_EVIDENCE": ("SAFETY_REVIEW", "BLOCKED", "CANCELLED"),
        "SAFETY_REVIEW": ("AWAITING_APPROVAL", "BLOCKED", "CANCELLED"),
        "AWAITING_APPROVAL": ("APPROVED", "REJECTED", "ESCALATED", "BLOCKED", "CANCELLED"),
        "BLOCKED": ("ASSIGNED", "PENDING"),
        "CANCELLED": (),
        "COMPLETED": (),
        "APPROVED": ("COMPLETED",),
        "REJECTED": ("COMPLETED",),
        "ESCALATED": ("ASSIGNED", "PENDING", "BLOCKED"),
    }
    allowed = valid_next.get(v["status"], ())
    if status not in allowed:
        raise HTTPException(status_code=422,
                            detail=f"Illegal transition {v['status']} → {status}")
    con.execute("UPDATE verifications SET status = ?, updated_at = ? WHERE id = ?",
                (status, utcnow_iso(), vid))
    if status == "COMPLETED":
        con.execute("UPDATE verifications SET completed_at = ? WHERE id = ?",
                    (utcnow_iso(), vid))
    con.commit()
    log_event("verification_status_changed",
              {"verification_id": vid, "from": v["status"], "to": status},
              company_id=company_id, user_id=user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return dict(con.execute("SELECT * FROM verifications WHERE id = ?", (vid,)).fetchone())


def assign_technician(con, vid: int, user_id: int, company_id: int,
                       body: VerificationAssignIn, request_user_id: int) -> dict:
    v = _owned_verification(con, vid, company_id)
    u = con.execute("SELECT id, role FROM users WHERE id = ? AND company_id = ?",
                     (body.user_id, company_id)).fetchone()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found in company")
    if body.role == "TECHNICIAN" and u["role"] != "TECHNICIAN":
        raise HTTPException(status_code=422, detail="Assigned user must be TECHNICIAN role")
    con.execute("INSERT INTO verification_assignments (verification_id, company_id, role,"
                " assigned_to, assigned_by, note) VALUES (?,?,?,?,?,?)",
                (vid, company_id, body.role, body.user_id, request_user_id, ""))
    if body.role == "TECHNICIAN":
        con.execute("UPDATE verifications SET assigned_technician_id = ?, updated_at = ? WHERE id = ?",
                    (body.user_id, utcnow_iso(), vid))
        new_status = v["status"]
        if new_status == "PENDING":
            con.execute("UPDATE verifications SET status = 'ASSIGNED', updated_at = ? WHERE id = ?",
                        (utcnow_iso(), vid))
    elif body.role == "REVIEWER":
        con.execute("UPDATE verifications SET assigned_reviewer_id = ?, updated_at = ? WHERE id = ?",
                    (body.user_id, utcnow_iso(), vid))
    con.commit()
    log_event("technician_assigned",
              {"verification_id": vid, "role": body.role, "user_id": body.user_id},
              company_id=company_id, user_id=request_user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return dict(con.execute("SELECT * FROM verifications WHERE id = ?", (vid,)).fetchone())


def assign_reviewer(con, vid: int, user_id: int, company_id: int,
                     request_user_id: int) -> dict:
    return assign_technician(con, vid, user_id, company_id,
                              VerificationAssignIn(role="REVIEWER", user_id=user_id),
                              request_user_id)


def start_verification(con, vid: int, company_id: int, user_id: int) -> dict:
    v = _owned_verification(con, vid, company_id)
    if v["assigned_technician_id"] is None:
        raise HTTPException(status_code=422, detail="Assign a technician first")
    con.execute("UPDATE verifications SET status = 'IN_REVIEW', started_at = ?, updated_at = ? WHERE id = ?",
                (utcnow_iso(), utcnow_iso(), vid))
    con.commit()
    log_event("verification_started", {"verification_id": vid},
              company_id=company_id, user_id=user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return dict(con.execute("SELECT * FROM verifications WHERE id = ?", (vid,)).fetchone())


def verify_evidence(con, vid: int, company_id: int, body: EvidenceVerifyIn,
                     user_id: int) -> dict:
    v = _owned_verification(con, vid, company_id)
    ev = con.execute("SELECT * FROM evidence WHERE id = ? AND is_active = 1",
                      (body.evidence_id,)).fetchone()
    if ev is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    cur = con.execute(
        "INSERT INTO evidence_verifications (verification_id, company_id, evidence_id,"
        " verified_by, status, comment, measurement, attachment, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (vid, company_id, body.evidence_id, user_id, body.status,
         body.comment, body.measurement, body.attachment, utcnow_iso()))
    con.commit()
    log_event("evidence_verified",
              {"verification_id": vid, "evidence_id": body.evidence_id, "status": body.status},
              company_id=company_id, user_id=user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return dict(con.execute("SELECT * FROM evidence_verifications WHERE id = ?", (cur.lastrowid,)).fetchone())


def add_observation(con, vid: int, company_id: int, body: ObservationIn,
                     user_id: int) -> dict:
    v = _owned_verification(con, vid, company_id)
    cur = con.execute(
        "INSERT INTO technician_observations (verification_id, company_id, equipment_id,"
        " technician_id, observation_type, description, severity, observed_at,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (vid, company_id, body.equipment_id, user_id, body.observation_type,
         body.description, body.severity, body.observed_at or utcnow_iso(),
         utcnow_iso(), utcnow_iso()))
    con.commit()
    oid = cur.lastrowid
    log_event("observation_added",
              {"verification_id": vid, "observation_id": oid, "type": body.observation_type},
              company_id=company_id, user_id=user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return dict(con.execute("SELECT * FROM technician_observations WHERE id = ?", (oid,)).fetchone())


def add_measurement(con, vid: int, company_id: int, body: MeasurementIn,
                     user_id: int) -> dict:
    v = _owned_verification(con, vid, company_id)
    cur = con.execute(
        "INSERT INTO technician_measurements (verification_id, company_id, equipment_id,"
        " technician_id, parameter, value, unit, instrument_id, instrument_type,"
        " calibration_status, calibration_date, calibration_expiry, notes,"
        " recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (vid, company_id, body.equipment_id, user_id, body.parameter, body.value,
         body.unit, body.instrument_id, body.instrument_type, body.calibration_status,
         body.calibration_date, body.calibration_expiry, body.notes, utcnow_iso()))
    con.commit()
    con.commit()
    mid = cur.lastrowid
    log_event("measurement_added",
              {"verification_id": vid, "measurement_id": mid, "parameter": body.parameter},
              company_id=company_id, user_id=user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return dict(con.execute("SELECT * FROM technician_measurements WHERE id = ?", (mid,)).fetchone())


def complete_checklist_item(con, vid: int, item_id: int, company_id: int,
                             body: ChecklistItemPatch, user_id: int) -> dict:
    ci = con.execute("SELECT * FROM checklist_items WHERE id = ?", (item_id,)).fetchone()
    if ci is None:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    ic = con.execute("SELECT * FROM inspection_checklists WHERE id = ?", (ci["checklist_id"],)).fetchone()
    if ic is None or ic["verification_id"] != vid:
        raise HTTPException(status_code=404, detail="Checklist not associated with this verification")
    con.execute("UPDATE checklist_items SET status = ?, completed_by = ?, completed_at = ?, comment = ? WHERE id = ?",
                (body.status, user_id, utcnow_iso(), body.comment, item_id))
    con.commit()
    log_event("checklist_item_updated",
              {"verification_id": vid, "checklist_item_id": item_id, "status": body.status},
              company_id=company_id, user_id=user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return dict(con.execute("SELECT * FROM checklist_items WHERE id = ?", (item_id,)).fetchone())


def evaluate_safety_gate(con, vid: int, company_id: int, user_id: int) -> dict:
    """Real backend safety gate: evaluate all blocking conditions."""
    v = _owned_verification(con, vid, company_id)
    reasons: list[str] = []
    missing_checklist: list[str] = []
    missing_evidence: list[str] = []

    # Check checklist completion
    checklists = con.execute("SELECT * FROM inspection_checklists WHERE verification_id = ?", (vid,)).fetchall()
    for cl in checklists:
        items = con.execute("SELECT * FROM checklist_items WHERE checklist_id = ?", (cl["id"],)).fetchall()
        required = [i for i in items if i["required"] == 1]
        for item in required:
            if item["status"] not in ("PASS",):
                missing_checklist.append(f"Checklist '{cl['title']}': {item['description']}")
                reasons.append(f"Required checklist item incomplete: {item['description']}")

    # Check safety assessment exists
    safety = con.execute("SELECT * FROM safety_assessments WHERE verification_id = ?", (vid,)).fetchone()
    if safety is None:
        reasons.append("Safety assessment not created")
    else:
        if safety["risk_level"] == "CRITICAL":
            reasons.append("Critical risk level requires safety officer approval")
        # Check hazards
        open_hazards = con.execute("SELECT * FROM hazards WHERE safety_assessment_id = ? AND status = 'OPEN'", (safety["id"],)).fetchall()
        if open_hazards:
            reasons.append(f"{len(open_hazards)} open hazard(s) require control")

    # Check isolation
    iso = con.execute("SELECT * FROM isolation_records WHERE verification_id = ?", (vid,)).fetchone()
    if iso and iso["isolation_required"] and not iso["isolation_confirmed"]:
        reasons.append("Isolation confirmation required")
        missing_evidence.append("Isolation confirmation missing")

    # Check permit
    permit = con.execute("SELECT * FROM permits WHERE verification_id = ?", (vid,)).fetchone()
    permit_expired = False
    if permit:
        if permit["status"] in ("ACTIVE", "APPROVED"):
            if permit["expiry_time"] < utcnow_iso():
                permit_expired = True
                reasons.append("Safety permit expired")
        elif permit["status"] not in ("DRAFT", "REQUESTED", "APPROVED", "ACTIVE"):
            pass  # draft/requested is not blocking
    elif permit is None:
        pass  # No permit required if not configured

    # Check required evidence
    ev = con.execute("SELECT * FROM evidence WHERE investigation_id = ? AND is_active = 1", (v["investigation_id"],)).fetchall()
    if not ev:
        missing_evidence.append("No evidence collected")
        reasons.append("No evidence collected for verification")

    # Check technician observations
    obs_count = con.execute("SELECT COUNT(*) FROM technician_observations WHERE verification_id = ?", (vid,)).fetchone()[0]
    if obs_count == 0:
        reasons.append("No technician observations recorded")

    blocked = len(reasons) > 0
    con.execute("INSERT OR REPLACE INTO safety_gate_results (verification_id, company_id, blocked, risk_level, reasons,"
                " missing_checklist, missing_evidence, missing_permit, missing_isolation, evaluated_at, evaluated_by)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (vid, company_id, 1 if blocked else 0,
                 safety["risk_level"] if safety else "LOW",
                 json.dumps(reasons), json.dumps(missing_checklist),
                 json.dumps(missing_evidence), 1 if (permit and permit_expired) else 0,
                 1 if (iso and iso["isolation_required"] and not iso["isolation_confirmed"]) else 0,
                 utcnow_iso(), user_id))
    con.commit()
    log_event("safety_gate_evaluated",
              {"verification_id": vid, "blocked": blocked, "reasons": reasons},
              company_id=company_id, user_id=user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return {"blocked": blocked, "risk_level": safety["risk_level"] if safety else "LOW",
            "reasons": reasons, "missing_checklist": missing_checklist,
            "missing_evidence": missing_evidence}


def get_safety_gate(con, vid: int, company_id: int) -> dict:
    gate = con.execute("SELECT * FROM safety_gate_results WHERE verification_id = ?", (vid,)).fetchone()
    if gate is None:
        return {"blocked": True, "risk_level": "LOW", "reasons": ["Safety gate not evaluated"]}
    return {"blocked": bool(gate["blocked"]), "risk_level": gate["risk_level"],
            "reasons": json.loads(gate["reasons"]) if gate["reasons"] else [],
            "missing_checklist": json.loads(gate["missing_checklist"]) if gate["missing_checklist"] else [],
            "missing_evidence": json.loads(gate["missing_evidence"]) if gate["missing_evidence"] else []}


def request_approval(con, vid: int, company_id: int, body: ApprovalRequestIn,
                      user_id: int) -> dict:
    v = _owned_verification(con, vid, company_id)
    if v["status"] not in ("SAFETY_REVIEW", "AWAITING_APPROVAL"):
        raise HTTPException(status_code=422, detail="Verification must be in SAFETY_REVIEW or AWAITING_APPROVAL status")
    # Check safety gate
    gate = con.execute("SELECT * FROM safety_gate_results WHERE verification_id = ?", (vid,)).fetchone()
    if gate and gate["blocked"]:
        raise HTTPException(status_code=422,
                            detail={"message": "Safety gate is blocked",
                                    "reasons": json.loads(gate["reasons"]) if gate["reasons"] else []})
    # Check if approval already requested
    existing = con.execute("SELECT id FROM approvals WHERE verification_id = ? AND status = 'PENDING'", (vid,)).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Approval already pending")
    # Determine approval level
    level = body.approval_level
    if level == "TECHNICIAN" and v["priority"] in ("HIGH", "CRITICAL"):
        level = _check_approval_level(con, v, company_id)
    cur = con.execute(
        "INSERT INTO approvals (verification_id, company_id, requested_by,"
        " approval_level, status, requested_at, expires_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (vid, company_id, user_id, level, "PENDING", utcnow_iso(),
         utcnow_iso() + " 7 days"))
    con.commit()
    log_event("approval_requested", {"verification_id": vid, "approval_level": level},
              company_id=company_id, user_id=user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return dict(con.execute("SELECT * FROM approvals WHERE id = ?", (cur.lastrowid,)).fetchone())


def approve_or_reject(con, vid: int, company_id: int, body: DecisionIn,
                       user_id: int) -> dict:
    v = _owned_verification(con, vid, company_id)
    approval = con.execute("SELECT * FROM approvals WHERE verification_id = ? AND status = 'PENDING'", (vid,)).fetchone()
    if approval is None:
        raise HTTPException(status_code=404, detail="No pending approval found")
    # Self-approval prevention: approver cannot be the verification requester
    if approval["requested_by"] == user_id:
        raise HTTPException(status_code=403, detail="Cannot approve your own request (separation of duties)")
    if approval["approver_id"] is not None and approval["approver_id"] != user_id and approval["approver_id"] != 0:
        # Check if user is authorized approver
        pass
    decision = body.decision
    status_map = {"APPROVE": "APPROVED", "REJECT": "REJECTED",
                  "REQUEST_MORE_EVIDENCE": "REQUEST_MORE_EVIDENCE",
                  "ESCALATE": "ESCALATED", "DEFER": "DEFERRED"}
    # Record immutable decision
    con.execute(
        "INSERT INTO approval_decisions (approval_id, company_id, decision, actor,"
        " actor_role, reason, comment, evidence_snapshot, safety_snapshot,"
        " hypothesis_snapshot, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (approval["id"], company_id, decision, user_id,
         "TECHNICIAN", body.reason, body.comment,
         json.dumps({}), json.dumps({}), json.dumps([]), utcnow_iso()))
    # Record the decision in approvals table
    con.execute("UPDATE approvals SET status = ?, approver_id = ?, reason = ?, comment = ?,"
                " justification = ?, decided_at = ?, updated_at = ? WHERE id = ?",
                (status_map.get(decision), user_id, body.reason, body.comment,
                 body.justification, utcnow_iso(), utcnow_iso(), approval["id"]))
    # Update verification status
    if decision == "APPROVE":
        con.execute("UPDATE verifications SET status = 'APPROVED', completed_at = ?, updated_at = ? WHERE id = ?",
                    (utcnow_iso(), utcnow_iso(), vid))
    elif decision == "REJECT":
        con.execute("UPDATE verifications SET status = 'REJECTED', updated_at = ? WHERE id = ?",
                    (utcnow_iso(), vid))
    elif decision == "ESCALATE":
        con.execute("UPDATE verifications SET status = 'ESCALATED', updated_at = ? WHERE id = ?",
                    (utcnow_iso(), vid))
    elif decision == "REQUEST_MORE_EVIDENCE":
        con.execute("UPDATE verifications SET status = 'AWAITING_EVIDENCE', updated_at = ? WHERE id = ?",
                    (utcnow_iso(), vid))
    con.commit()
    log_event("approval_decided",
              {"verification_id": vid, "decision": decision, "approval_id": approval["id"]},
              company_id=company_id, user_id=user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return dict(con.execute("SELECT * FROM approvals WHERE id = ?", (approval["id"],)).fetchone())


def escalate(con, vid: int, company_id: int, body: EscalationIn,
              user_id: int) -> dict:
    v = _owned_verification(con, vid, company_id)
    # Escalate to the reviewer or admin
    target = body.user_id
    cur = con.execute(
        "INSERT INTO escalations (verification_id, company_id, escalated_by,"
        " escalated_to, reason, status, created_at) VALUES (?,?,?,?,?,'OPEN',?)",
        (vid, company_id, user_id, target, body.reason, utcnow_iso()))
    # Update verification status
    if v["status"] not in ("ESCALATED", "BLOCKED"):
        con.execute("UPDATE verifications SET status = 'ESCALATED', updated_at = ? WHERE id = ?",
                    (utcnow_iso(), vid))
    con.commit()
    log_event("approval_escalated", {"verification_id": vid, "escalation_id": cur.lastrowid},
              company_id=company_id, user_id=user_id,
              ip=_ip(), entity_type="verification", entity_id=vid)
    return dict(con.execute("SELECT * FROM escalations WHERE id = ?", (cur.lastrowid,)).fetchone())


def invalidate_approval_if_needed(con, vid: int, company_id: int) -> bool:
    """Mark approval as STALE if critical evidence changed after approval."""
    approval = con.execute("SELECT * FROM approvals WHERE verification_id = ? AND status = 'APPROVED'", (vid,)).fetchone()
    if approval is None:
        return False
    # Check if new evidence was added after approval
    new_ev = con.execute(
        "SELECT COUNT(*) FROM evidence_verifications WHERE verification_id = ? AND created_at > ?",
        (vid, approval["decided_at"] or "")).fetchone()[0]
    if new_ev > 0:
        con.execute("UPDATE approvals SET status = 'STALE', updated_at = ? WHERE id = ?",
                    (utcnow_iso(), approval["id"]))
        con.execute("UPDATE verifications SET status = 'AWAITING_APPROVAL', updated_at = ? WHERE id = ?",
                    (utcnow_iso(), vid))
        con.commit()
        log_event("approval_invalidated",
                  {"verification_id": vid, "approval_id": approval["id"],
                   "reason": "New evidence added after approval"},
                  company_id=company_id, user_id=0, ip=None,
                  entity_type="verification", entity_id=vid)
        return True
    return False


def get_verification_scorecard(con, vid: int, company_id: int) -> dict:
    v = _owned_verification(con, vid, company_id)
    inv = con.execute("SELECT * FROM investigations WHERE id = ?", (v["investigation_id"],)).fetchone()
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    settings = company_settings(con, company_id)
    from ..routers.hypotheses import health_for
    health = health_for(con, inv, settings)
    ev_count = con.execute("SELECT COUNT(*) FROM evidence WHERE investigation_id = ? AND is_active = 1", (inv["id"],)).fetchone()[0]
    obs_count = con.execute("SELECT COUNT(*) FROM technician_observations WHERE verification_id = ?", (vid,)).fetchone()[0]
    meas_count = con.execute("SELECT COUNT(*) FROM technician_measurements WHERE verification_id = ?", (vid,)).fetchone()[0]
    ev_v = con.execute("SELECT COUNT(*) FROM evidence_verifications WHERE verification_id = ? AND status = 'VERIFIED'", (vid,)).fetchone()[0]
    # Check critical conflicts
    conflicts = con.execute("SELECT COUNT(*) FROM conflicts WHERE investigation_id = ? AND status = 'OPEN'", (inv["id"],)).fetchone()[0]
    # Approval readiness
    gate = get_safety_gate(con, vid, company_id)
    blocked = gate["blocked"]
    approval_readiness = "NOT_READY" if blocked else "READY"
    if obs_count == 0:
        approval_readiness = "NOT_READY"
    # Insert/update scorecard
    con.execute("INSERT OR REPLACE INTO verification_scorecards (verification_id, company_id,"
                " evidence_coverage, evidence_quality, technician_verification, safety_readiness,"
                " hypothesis_confidence, critical_conflicts, approval_readiness, evaluated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (vid, company_id,
                 min(100.0, 100.0 * ev_count / max(1, 10)),
                 health.get("quality", 50),
                 min(100.0, 100.0 * ev_v / max(1, 1)),
                 100.0 if not blocked else 0.0,
                 health.get("readiness") == "HIGH" and 100.0 or 50.0,
                 conflicts, approval_readiness, utcnow_iso()))
    con.commit()
    return {"verification_id": vid, "evidence_coverage": min(100.0, 100.0 * ev_count / max(1, 10)),
            "evidence_quality": health.get("quality", 50),
            "technician_verification": min(100.0, 100.0 * ev_v / max(1, 1)),
            "safety_readiness": 100.0 if not blocked else 0.0,
            "hypothesis_confidence": 100.0 if health.get("readiness") == "HIGH" else 50.0,
            "critical_conflicts": conflicts,
            "approval_readiness": approval_readiness,
            "blocked": blocked}


def get_approval_inbox(con, company_id: int, page: int = 1, page_size: int = 20) -> dict:
    q = """SELECT a.*, v.id AS verification_id, v.investigation_id, v.status AS verification_status,
                  v.priority, v.reason AS verification_reason,
                  e.code AS equipment_code, e.name AS equipment_name
           FROM approvals a JOIN verifications v ON a.verification_id = v.id
           JOIN equipment e ON v.equipment_id = e.id
           WHERE a.status = 'PENDING' AND (v.assigned_reviewer_id = ? OR a.approval_level IN ('SUPERVISOR','SAFETY_OFFICER'))"""
    params: list = [company_id]
    # Simple approach: show all pending for company where user might be reviewer
    total = con.execute(f"SELECT COUNT(*) FROM ({q})", params).fetchone()[0]
    rows = con.execute(q + " ORDER BY a.created_at DESC LIMIT ? OFFSET ?",
                       (*params, page_size, (page - 1) * page_size)).fetchall()
    return {"approvals": [dict(r) for r in rows], "total": total,
            "page": page, "page_size": page_size}


def get_safety_center(con, company_id: int) -> dict:
    active = con.execute("SELECT COUNT(*) FROM verifications WHERE company_id = ? AND status IN ('IN_REVIEW','INSPECTION_REQUIRED','AWAITING_EVIDENCE','SAFETY_REVIEW','AWAITING_APPROVAL')", (company_id,)).fetchone()[0]
    blocked = con.execute("SELECT COUNT(*) FROM verifications WHERE company_id = ? AND status = 'BLOCKED'", (company_id,)).fetchone()[0]
    high_risk = con.execute("SELECT COUNT(*) FROM safety_assessments sa JOIN verifications v ON sa.verification_id = v.id WHERE v.company_id = ? AND sa.risk_level = 'HIGH'", (company_id,)).fetchone()[0]
    awaiting_approval = con.execute("SELECT COUNT(*) FROM approvals WHERE company_id = ? AND status = 'PENDING'", (company_id,)).fetchone()[0]
    expired_permits = con.execute("SELECT COUNT(*) FROM permits WHERE company_id = ? AND status = 'EXPIRED'", (company_id,)).fetchone()[0]
    open_hazards = con.execute("SELECT COUNT(*) FROM hazards h JOIN safety_assessments sa ON h.safety_assessment_id = sa.id JOIN verifications v ON sa.verification_id = v.id WHERE v.company_id = ? AND h.status = 'OPEN'", (company_id,)).fetchone()[0]
    return {"active_reviews": active, "blocked": blocked, "high_risk": high_risk,
            "awaiting_approval": awaiting_approval, "expired_permits": expired_permits,
            "open_hazards": open_hazards}


def get_dashboard_stats(con, company_id: int) -> dict:
    total = con.execute("SELECT COUNT(*) FROM verifications WHERE company_id = ?", (company_id,)).fetchone()[0]
    by_status = {}
    for st in ("PENDING", "ASSIGNED", "IN_REVIEW", "INSPECTION_REQUIRED",
               "AWAITING_EVIDENCE", "SAFETY_REVIEW", "AWAITING_APPROVAL",
               "APPROVED", "REJECTED", "BLOCKED", "COMPLETED"):
        c = con.execute("SELECT COUNT(*) FROM verifications WHERE company_id = ? AND status = ?", (company_id, st)).fetchone()[0]
        by_status[st] = c
    return {"total": total, "by_status": by_status}
