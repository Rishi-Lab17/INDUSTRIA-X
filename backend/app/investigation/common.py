"""Shared constants, validation sets, and ownership helpers for Stage 7."""
from fastapi import HTTPException

from ..db import connect

STATUSES = ("DRAFT", "OPEN", "ANALYZING", "AWAITING_EVIDENCE",
            "TECHNICIAN_REVIEW", "VERIFICATION", "APPROVAL",
            "RESOLVED", "CLOSED", "ARCHIVED", "READY_FOR_VERIFICATION")

# Legal forward transitions (plus ARCHIVED from any non-closed state).
TRANSITIONS = {
    "DRAFT": ("OPEN", "ARCHIVED"),
    "OPEN": ("ANALYZING", "AWAITING_EVIDENCE", "ARCHIVED"),
    "ANALYZING": ("AWAITING_EVIDENCE", "TECHNICIAN_REVIEW", "OPEN", "ARCHIVED"),
    "AWAITING_EVIDENCE": ("ANALYZING", "TECHNICIAN_REVIEW", "ARCHIVED"),
    "TECHNICIAN_REVIEW": ("ANALYZING", "VERIFICATION", "ARCHIVED"),
    "VERIFICATION": ("APPROVAL", "ANALYZING", "ARCHIVED"),
    "APPROVAL": ("RESOLVED", "VERIFICATION", "ARCHIVED"),
    "READY_FOR_VERIFICATION": ("VERIFICATION", "APPROVAL", "ARCHIVED"),
    "RESOLVED": ("CLOSED",),
    "CLOSED": (),
    "ARCHIVED": (),
}

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

CATEGORIES = ("MECHANICAL", "ELECTRICAL", "THERMAL", "HYDRAULIC", "PNEUMATIC",
              "PROCESS", "SENSOR", "SOFTWARE", "UNKNOWN", "OTHER")

HYP_STATUSES = ("ACTIVE", "SUPPORTED", "WEAKENED", "REJECTED", "CONFIRMED", "UNKNOWN")

EVIDENCE_TYPES = ("SENSOR", "DOCUMENT", "IMAGE", "OCR", "RAG", "TECHNICIAN",
                  "MANUAL", "MAINTENANCE_HISTORY", "INSPECTION", "SYSTEM",
                  "EXTERNAL_INTEGRATION")

RELATIONS = ("SUPPORTS", "CONTRADICTS", "NEUTRAL")

GRAPH_RELATIONS = ("SUPPORTS", "CONTRADICTS", "DERIVED_FROM", "RELATED_TO",
                   "MEASURES", "OBSERVED_ON", "SIMILAR_TO", "REQUIRES", "VERIFIES")

ASSUMPTION_STATUSES = ("VERIFIED", "UNVERIFIED", "CONTRADICTED", "UNKNOWN")

FRESHNESS_BANDS = ("Fresh", "Recent", "Aging", "Stale", "Unknown")

# Default source-trust hierarchy (weights 0..1). Overridable per company via
# companies.settings JSON key "source_trust". Documented as a prior, not truth.
DEFAULT_TRUST = {
    "SENSOR": 0.90,
    "TECHNICIAN": 0.80,
    "INSPECTION": 0.80,
    "MAINTENANCE_HISTORY": 0.75,
    "DOCUMENT": 0.70,
    "RAG": 0.65,
    "IMAGE": 0.65,
    "OCR": 0.55,
    "MANUAL": 0.60,
    "SYSTEM": 0.70,
    "EXTERNAL_INTEGRATION": 0.50,
}

# Freshness policy: (max age seconds, band). Company override via
# settings key "freshness_policy" (same shape).
DEFAULT_FRESHNESS = [
    (86400, "Fresh"),
    (7 * 86400, "Recent"),
    (30 * 86400, "Aging"),
    (float("inf"), "Stale"),
]

# Readiness gate thresholds (spec §39). Company override via settings key
# "readiness_gate".
DEFAULT_GATE = {
    "min_separation": 15.0,
    "require_technician_verification": True,
}


def get_owned_investigation(con, inv_id: int, company_id: int) -> dict:
    row = con.execute("SELECT * FROM investigations WHERE id = ? AND company_id = ?",
                      (inv_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return dict(row)


def get_owned_workspace(con, workspace_id: int, company_id: int) -> dict:
    row = con.execute("SELECT * FROM workspaces WHERE id = ? AND company_id = ?",
                      (workspace_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return dict(row)


def default_workspace(con, company_id: int) -> dict:
    """Lazily provision the per-company 'Default' workspace (no auth changes)."""
    row = con.execute("SELECT * FROM workspaces WHERE company_id = ? AND name = 'Default'",
                      (company_id,)).fetchone()
    if row is None:
        cur = con.execute("INSERT INTO workspaces (company_id, name) VALUES (?, 'Default')",
                          (company_id,))
        con.commit()
        row = con.execute("SELECT * FROM workspaces WHERE id = ?",
                          (cur.lastrowid,)).fetchone()
    return dict(row)


def company_settings(con, company_id: int) -> dict:
    import json
    row = con.execute("SELECT settings FROM companies WHERE id = ?",
                      (company_id,)).fetchone()
    if not row or not row["settings"]:
        return {}
    try:
        return json.loads(row["settings"])
    except (ValueError, TypeError):
        return {}


def trust_for(settings: dict, evidence_type: str) -> float:
    table = settings.get("source_trust") or {}
    try:
        return float(table.get(evidence_type, DEFAULT_TRUST.get(evidence_type, 0.5)))
    except (TypeError, ValueError):
        return DEFAULT_TRUST.get(evidence_type, 0.5)
