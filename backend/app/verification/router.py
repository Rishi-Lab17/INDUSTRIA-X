"""Stage 8: verification, safety gate, technician workflow, human approval APIs."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..audit import log_event
from ..core.deps import get_current_session, require_roles
from ..core.rate_limit import allow
from ..core.security import utcnow_iso
from ..db import connect
from ..verification.service import (
    STATUSES, PRIORITIES,
    create_verification, list_verifications, get_verification,
    update_verification_status, assign_technician, assign_reviewer,
    start_verification, verify_evidence, add_observation,
    add_measurement, complete_checklist_item, evaluate_safety_gate,
    get_safety_gate, request_approval, approve_or_reject,
    escalate, invalidate_approval_if_needed, get_verification_scorecard,
    get_approval_inbox, get_safety_center, get_dashboard_stats,
    _owned_verification,
)
from ..investigation.common import get_owned_investigation

router = APIRouter(prefix="/api/verifications", tags=["verifications"])


def _limited(sess: dict, action: str = "verification") -> None:
    from ..core.rate_limit import allow as _allow
    ok, retry = _allow(f"{action}:{sess['user_id']}", 60, 60)
    if not ok:
        raise HTTPException(status_code=429, detail="Rate limit reached.",
                            headers={"Retry-After": str(retry)})


def _row_to_v(row) -> dict:
    return {k: row[k] for k in
            ("id", "investigation_id", "company_id", "workspace_id",
             "equipment_id", "assigned_technician_id", "assigned_reviewer_id",
             "status", "priority", "reason", "instructions",
             "safety_requirements", "due_at", "started_at", "completed_at",
             "created_at", "updated_at")}


# ---------- verification CRUD ----------

@router.post("", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_verification_endpoint(body: dict, request: Request,
                                  sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        from pydantic import BaseModel, field_validator
        class VB(BaseModel):
            investigation_id: int
            reason: str
            priority: str = "MEDIUM"
            instructions: str = ""
            safety_requirements: str = ""
            @field_validator("priority")
            @classmethod
            def _pri(cls, v: str) -> str:
                if v not in PRIORITIES: raise ValueError(f"priority must be one of {PRIORITIES}")
                return v
            @field_validator("reason")
            @classmethod
            def _reason(cls, v: str) -> str:
                v = v.strip()
                if not v: raise ValueError("Reason must not be empty")
                return v[:2000]
        try:
            parsed = VB(**body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))
        inv = get_owned_investigation(con, parsed.investigation_id, sess["company_id"])
        from ..verification.service import create_verification as _cv
        result = _cv(con, inv, sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()
    return _row_to_v(result)


@router.get("")
def list_verifications_endpoint(sess: dict = Depends(get_current_session),
                                  status: str | None = None,
                                  priority: str | None = None,
                                  page: int = 1, page_size: int = 20):
    if status and status not in STATUSES:
        raise HTTPException(status_code=422, detail="Invalid status")
    if priority and priority not in PRIORITIES:
        raise HTTPException(status_code=422, detail="Invalid priority")
    con = connect()
    try:
        return list_verifications(con, sess["company_id"], status, priority, page, page_size)
    finally:
        con.close()


# Static routes must come before dynamic /{vid} to avoid path-param shadowing (safety-center/approvals/dashboard)
@router.get("/approvals")
def approval_inbox_endpoint(sess: dict = Depends(get_current_session),
                              page: int = 1, page_size: int = 20):
    con = connect()
    try:
        return get_approval_inbox(con, sess["company_id"], page, page_size)
    finally:
        con.close()


@router.get("/safety-center")
def safety_center_endpoint(sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        return get_safety_center(con, sess["company_id"])
    finally:
        con.close()


@router.get("/dashboard")
def dashboard_stats_endpoint(sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        return get_dashboard_stats(con, sess["company_id"])
    finally:
        con.close()


@router.get("/{vid}")
def get_verification_endpoint(vid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        return get_verification(con, vid, sess["company_id"])
    finally:
        con.close()


@router.patch("/{vid}/status",
              dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def update_verification_status_endpoint(vid: int, body: dict,
                                          request: Request,
                                          sess: dict = Depends(get_current_session)):
    if "status" not in body or body["status"] not in STATUSES:
        raise HTTPException(status_code=422, detail="Invalid status")
    _limited(sess)
    con = connect()
    try:
        result = update_verification_status(con, vid, body["status"], sess["company_id"], sess["user_id"])
    finally:
        con.close()
    return _row_to_v(result)


# ---------- technician assignment ----------

@router.post("/{vid}/assign",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def assign_tech_endpoint(vid: int, body: dict, request: Request,
                          sess: dict = Depends(get_current_session)):
    from ..verification.service import VerificationAssignIn
    try:
        parsed = VerificationAssignIn(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    _limited(sess)
    con = connect()
    try:
        result = assign_technician(con, vid, sess["user_id"], sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()
    return _row_to_v(result)


@router.post("/{vid}/reviewer",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def assign_reviewer_endpoint(vid: int, body: dict, request: Request,
                              sess: dict = Depends(get_current_session)):
    from ..verification.service import VerificationAssignIn
    try:
        parsed = VerificationAssignIn(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    _limited(sess)
    con = connect()
    try:
        result = assign_reviewer(con, vid, sess["user_id"], sess["company_id"], sess["user_id"])
    finally:
        con.close()
    return _row_to_v(result)


@router.post("/{vid}/start",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def start_verification_endpoint(vid: int, request: Request,
                                 sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        result = start_verification(con, vid, sess["company_id"], sess["user_id"])
    finally:
        con.close()
    return _row_to_v(result)


# ---------- evidence verification ----------

@router.post("/{vid}/evidence-verify", status_code=201)
def verify_evidence_endpoint(vid: int, body: dict, request: Request,
                              sess: dict = Depends(get_current_session)):
    from ..verification.service import EvidenceVerifyIn
    try:
        parsed = EvidenceVerifyIn(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    _limited(sess)
    con = connect()
    try:
        result = verify_evidence(con, vid, sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()
    return result


# ---------- technician observations ----------

@router.post("/{vid}/observations", status_code=201)
def add_observation_endpoint(vid: int, body: dict, request: Request,
                              sess: dict = Depends(get_current_session)):
    from ..verification.service import ObservationIn
    try:
        parsed = ObservationIn(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    _limited(sess)
    con = connect()
    try:
        result = add_observation(con, vid, sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()
    return result


# ---------- technician measurements ----------

@router.post("/{vid}/measurements", status_code=201)
def add_measurement_endpoint(vid: int, body: dict, request: Request,
                              sess: dict = Depends(get_current_session)):
    from ..verification.service import MeasurementIn
    try:
        parsed = MeasurementIn(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    _limited(sess)
    con = connect()
    try:
        result = add_measurement(con, vid, sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()
    return result


# ---------- checklists ----------

@router.post("/{vid}/checklists", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_checklist_endpoint(vid: int, body: dict, request: Request,
                               sess: dict = Depends(get_current_session)):
    from ..verification.service import ChecklistIn
    try:
        parsed = ChecklistIn(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    _limited(sess)
    con = connect()
    try:
        _owned_verification(con, vid, sess["company_id"])
        cur = con.execute(
            "INSERT INTO inspection_checklists (verification_id, company_id, template_key, title, created_by)"
            " VALUES (?,?,?,?,?)", (vid, sess["company_id"], parsed.template_key, parsed.title, sess["user_id"]))
        cl_id = cur.lastrowid
        for item in parsed.items:
            con.execute(
                "INSERT INTO checklist_items (checklist_id, description, required, status)"
                " VALUES (?,?,?,?)", (cl_id, item.get("description", ""),
                                      item.get("required", 0), "PENDING"))
        con.commit()
        log_event("checklist_created", {"verification_id": vid, "checklist_id": cl_id},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=None, entity_type="verification", entity_id=vid)
        return {"checklist_id": cl_id, "items_count": len(parsed.items)}
    finally:
        con.close()


@router.patch("/{vid}/checklists/{cid}/items/{iid}")
def complete_checklist_item_endpoint(vid: int, cid: int, iid: int, body: dict,
                                      request: Request,
                                      sess: dict = Depends(get_current_session)):
    from ..verification.service import ChecklistItemPatch
    try:
        parsed = ChecklistItemPatch(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    _limited(sess)
    con = connect()
    try:
        result = complete_checklist_item(con, vid, iid, sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()
    return result


@router.get("/{vid}/checklists")
def list_checklists_endpoint(vid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _owned_verification(con, vid, sess["company_id"])
        rows = con.execute("SELECT * FROM inspection_checklists WHERE verification_id = ?", (vid,)).fetchall()
        out = []
        for r in rows:
            items = con.execute("SELECT * FROM checklist_items WHERE checklist_id = ?", (r["id"],)).fetchall()
            out.append({**dict(r), "items": [dict(i) for i in items]})
        return {"checklists": out}
    finally:
        con.close()


# ---------- safety assessment ----------

@router.post("/{vid}/safety-assessment", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_safety_assessment_endpoint(vid: int, body: dict, request: Request,
                                       sess: dict = Depends(get_current_session)):
    from ..verification.service import SafetyAssessmentIn
    try:
        parsed = SafetyAssessmentIn(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    _limited(sess)
    con = connect()
    try:
        _owned_verification(con, vid, sess["company_id"])
        # Check for existing assessment
        existing = con.execute("SELECT id FROM safety_assessments WHERE verification_id = ?", (vid,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Safety assessment already exists")
        cur = con.execute(
            "INSERT INTO safety_assessments (verification_id, company_id, risk_level,"
            " likelihood, impact, assessor, notes, assessed_at, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (vid, sess["company_id"], parsed.risk_level, parsed.likelihood,
             parsed.impact, sess["user_id"], parsed.notes, utcnow_iso(), utcnow_iso()))
        sa_id = cur.lastrowid
        # Insert hazards
        for h in parsed.hazards:
            con.execute(
                "INSERT INTO hazards (safety_assessment_id, company_id, hazard_type, severity,"
                " likelihood, control, status, owner, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (sa_id, sess["company_id"], h.get("hazard_type", "OTHER"),
                 h.get("severity", "MEDIUM"), h.get("likelihood", 1),
                 h.get("control", ""), "OPEN", h.get("owner", ""), utcnow_iso()))
        # Insert controls
        for c in parsed.controls:
            con.execute(
                "INSERT INTO safety_controls (safety_assessment_id, company_id, control_type,"
                " description, required, status, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (sa_id, sess["company_id"], c.get("control_type", "GENERAL"),
                 c.get("description", ""), c.get("required", 1), "PENDING", utcnow_iso()))
        con.commit()
        log_event("safety_assessment_created",
                  {"verification_id": vid, "risk_level": parsed.risk_level},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=None, entity_type="verification", entity_id=vid)
        return {"safety_assessment_id": sa_id,
                "risk_level": parsed.risk_level,
                "hazards_count": len(parsed.hazards),
                "controls_count": len(parsed.controls)}
    finally:
        con.close()


@router.get("/{vid}/safety")
def get_safety_endpoint(vid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _owned_verification(con, vid, sess["company_id"])
        sa = con.execute("SELECT * FROM safety_assessments WHERE verification_id = ?", (vid,)).fetchone()
        if sa is None:
            return {"assessment": None, "hazards": [], "controls": []}
        hazards = con.execute("SELECT * FROM hazards WHERE safety_assessment_id = ?", (sa["id"],)).fetchall()
        controls = con.execute("SELECT * FROM safety_controls WHERE safety_assessment_id = ?", (sa["id"],)).fetchall()
        return {"assessment": dict(sa),
                "hazards": [dict(h) for h in hazards],
                "controls": [dict(c) for c in controls]}
    finally:
        con.close()


# ---------- safety gate ----------

@router.post("/{vid}/safety-gate/evaluate")
def evaluate_safety_gate_endpoint(vid: int, request: Request,
                                   sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        _owned_verification(con, vid, sess["company_id"])
        result = evaluate_safety_gate(con, vid, sess["company_id"], sess["user_id"])
    finally:
        con.close()
    return result


@router.get("/{vid}/safety-gate")
def get_safety_gate_endpoint(vid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _owned_verification(con, vid, sess["company_id"])
        return get_safety_gate(con, vid, sess["company_id"])
    finally:
        con.close()


# ---------- approval workflow ----------

@router.post("/{vid}/request-approval",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def request_approval_endpoint(vid: int, body: dict, request: Request,
                               sess: dict = Depends(get_current_session)):
    from ..verification.service import ApprovalRequestIn
    try:
        parsed = ApprovalRequestIn(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    _limited(sess)
    con = connect()
    try:
        result = request_approval(con, vid, sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()
    return result


@router.post("/{vid}/approve",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER", "TECHNICIAN"))])
def approve_endpoint(vid: int, body: dict, request: Request,
                      sess: dict = Depends(get_current_session)):
    from ..verification.service import DecisionIn
    try:
        parsed = DecisionIn(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    _limited(sess)
    con = connect()
    try:
        result = approve_or_reject(con, vid, sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()
    return result


@router.post("/{vid}/reject",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER", "TECHNICIAN"))])
def reject_endpoint(vid: int, body: dict, request: Request,
                     sess: dict = Depends(get_current_session)):
    from ..verification.service import DecisionIn
    try:
        parsed = DecisionIn(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    parsed.decision = "REJECT"
    _limited(sess)
    con = connect()
    try:
        result = approve_or_reject(con, vid, sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()
    return result


@router.post("/{vid}/escalate",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def escalate_endpoint(vid: int, body: dict, request: Request,
                       sess: dict = Depends(get_current_session)):
    from ..verification.service import EscalationIn
    try:
        parsed = EscalationIn(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    _limited(sess)
    con = connect()
    try:
        result = escalate(con, vid, sess["company_id"], parsed, sess["user_id"])
    finally:
        con.close()
    return result


# ---------- isolation ----------

@router.post("/{vid}/isolation", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_isolation_endpoint(vid: int, body: dict, request: Request,
                               sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        _owned_verification(con, vid, sess["company_id"])
        existing = con.execute("SELECT id FROM isolation_records WHERE verification_id = ?", (vid,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Isolation record already exists")
        con.execute(
            "INSERT INTO isolation_records (verification_id, company_id,"
            " isolation_required, isolation_confirmed, method, notes, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (vid, sess["company_id"],
             1 if body.get("isolation_required") else 0,
             1 if body.get("isolation_confirmed") else 0,
             body.get("method", ""), body.get("notes", ""), utcnow_iso()))
        con.commit()
        result = dict(con.execute("SELECT * FROM isolation_records WHERE verification_id = ?", (vid,)).fetchone())
        log_event("isolation_recorded", {"verification_id": vid},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=None, entity_type="verification", entity_id=vid)
        return result
    finally:
        con.close()


# ---------- permit ----------

@router.post("/{vid}/permit", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_permit_endpoint(vid: int, body: dict, request: Request,
                            sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        _owned_verification(con, vid, sess["company_id"])
        eq = con.execute("SELECT equipment_id FROM verifications WHERE id = ?", (vid,)).fetchone()
        cur = con.execute(
            "INSERT INTO permits (verification_id, company_id, permit_id, equipment_id,"
            " requested_by, authorized_by, start_time, expiry_time, hazards, controls,"
            " status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (vid, sess["company_id"], body.get("permit_id", f"PERM-{vid}"),
             eq["equipment_id"] if eq else 0, sess["user_id"],
             body.get("authorized_by", sess["user_id"]),
             body.get("start_time", utcnow_iso()), body.get("expiry_time", ""),
             body.get("hazards", ""), body.get("controls", ""),
             body.get("status", "DRAFT"), utcnow_iso()))
        con.commit()
        result = dict(con.execute("SELECT * FROM permits WHERE id = ?", (cur.lastrowid,)).fetchone())
        log_event("permit_created", {"verification_id": vid},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=None, entity_type="verification", entity_id=vid)
        return result
    finally:
        con.close()


# ---------- scorecard ----------

@router.get("/{vid}/scorecard")
def scorecard_endpoint(vid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _owned_verification(con, vid, sess["company_id"])
        return get_verification_scorecard(con, vid, sess["company_id"])
    finally:
        con.close()


# ---------- decision history ----------

@router.get("/{vid}/decisions")
def decision_history_endpoint(vid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _owned_verification(con, vid, sess["company_id"])
        rows = con.execute("""SELECT ad.*, a.approval_level, a.status as approval_status,
                                     u.name as actor_name, u.role as actor_role
                              FROM approval_decisions ad
                              JOIN approvals a ON ad.approval_id = a.id
                              JOIN users u ON ad.actor = u.id
                              WHERE a.verification_id = ?
                              ORDER BY ad.created_at""", (vid,)).fetchall()
        return {"decisions": [dict(r) for r in rows]}
    finally:
        con.close()


# ---------- escalation history ----------

@router.get("/{vid}/escalations")
def escalation_history_endpoint(vid: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _owned_verification(con, vid, sess["company_id"])
        rows = con.execute("SELECT * FROM escalations WHERE verification_id = ? ORDER BY created_at", (vid,)).fetchall()
        return {"escalations": [dict(r) for r in rows]}
    finally:
        con.close()
