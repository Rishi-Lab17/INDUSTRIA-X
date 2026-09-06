"""Stage 8: verification workflow, safety gate, technician actions, human approval."""
from .service import (
    create_verification, list_verifications, get_verification,
    update_verification_status, assign_technician, assign_reviewer,
    start_verification, verify_evidence, add_observation,
    add_measurement, complete_checklist_item, evaluate_safety_gate,
    request_approval, approve_or_reject, escalate,
    invalidate_approval_if_needed, get_safety_gate,
    get_verification_scorecard, get_approval_inbox,
    get_safety_center, get_dashboard_stats,
)
from .router import router
