# Stage 8 — Verification + Safety Gate + Technician Workflow + Human Approval

Stage 7 answers: *"What does the available evidence suggest?"*

Stage 8 answers: *"Can this investigation be safely verified and approved by an authorized human?"*

The workflow becomes:

```
Investigation → Stage 7 Readiness Gate → Verification Request →
Technician Assignment → Evidence Review → Technician Inspection →
Technician Observations → Additional Evidence → Safety Assessment →
Safety Gate → Human Review → Approval / Rejection / Escalation →
Audit Trail → Stage 9 Report + Case Memory
```

**Critical principle:** The AI MUST NOT approve its own recommendation.
- AI = decision support
- Human = final authority
- Safety gate = blocking control

## Architecture

```
backend/app/verification/
  __init__.py     · service.py  · router.py
backend/app/routers/cases.py   (Stage 7 - reused)
backend/app/investigation/     (Stage 7 - reused)
```

New API prefix: `/api/verifications`

## Data model

`verifications` — links to Stage 7 `investigations` (UNIQUE per investigation).
`verification_assignments` — tracks all technician/reviewer assignment changes.
`evidence_verifications` — technician confirms/rejects individual evidence items.
`technician_observations` — first-class evidence from inspection.
`technician_measurements` — structured numeric readings with instrument tracking.
`inspection_checklists` + `checklist_items` — configurable verification checklists.
`safety_assessments` + `hazards` + `safety_controls` — risk evaluation.
`isolation_records` — LOTO-style confirmation (workflow recording only).
`permits` — digital permit record with expiry.
`approvals` + `approval_decisions` — human decisions, immutable history.
`escalations` — escalation tracking.
`safety_gate_results` — backend-enforced blocking control results.
`verification_scorecards` — computed decision readiness snapshot.

All records carry `company_id`; tenant is derived from session only.

## Verification workflow statuses

```
PENDING → ASSIGNED → IN_REVIEW → INSPECTION_REQUIRED →
AWAITING_EVIDENCE → SAFETY_REVIEW → AWAITING_APPROVAL →
APPROVED / REJECTED / ESCALATED / BLOCKED / CANCELLED / COMPLETED
```

Status transitions are enforced by the backend. Illegal transitions return 422.

## Safety gate (backend-enforced blocking control)

The safety gate is a REAL backend control, not a UI badge.

Evaluation checks:
1. Required checklist items must pass
2. Safety assessment must exist (critical risk requires safety officer)
3. Isolation must be confirmed if required
4. Safety permit must be valid (not expired)
5. Evidence must be collected
6. Technician observations must exist

When blocked: `blocked: true` with `reasons` list. Approval is rejected with a clear error.

Risk levels: LOW, MEDIUM, HIGH, CRITICAL. Each has configurable blocking rules.

### Risk levels

| Risk | Meaning | Blocking |
|------|---------|----------|
| LOW | May proceed | No |
| MEDIUM | Additional verification required | Conditional |
| HIGH | Supervisor approval required | Yes |
| CRITICAL | Blocked until safety conditions satisfied | Yes |

These are **platform workflow policies**, not universal industrial safety standards.

## Separation of duties

- Investigator ≠ Approver
- Technician ≠ Approver for high-risk decisions
- AI ≠ Human approver

Self-approval is prevented: the person who requested approval cannot approve their own request.

## Technician actions

The technician sees:
- Equipment, problem, priority, AI leading hypothesis
- Evidence list with verification status per item
- Checklist with required/optional items
- Safety status

Actions:
1. **Start Inspection** — transitions to IN_REVIEW
2. **Confirm Evidence** — VERIFY/REJECT individual evidence items
3. **Add Observation** — creates technician_observation record
4. **Record Measurement** — creates technician_measurement record with instrument/calibration tracking
5. **Complete Checklist** — marks checklist items PASS/FAIL/SKIPPED
6. **Report Conflict** — creates conflict record, prevents approval
7. **Request More Evidence** — back to AWAITING_EVIDENCE
8. **Escalate** — creates escalation record, updates verification status

## Measurements and instrument tracking

Structured measurements with:
- Parameter, value, unit (validated)
- Instrument ID, instrument type
- Calibration status (VALID/EXPIRED/UNKNOWN)
- Calibration date and expiry

Unknown calibration is NOT claimed as valid. The system never fabricates calibration data.

## Approval workflow

```
Verification → Safety Gate → Required Evidence Check → Human Review → Decision
```

Approval levels by priority:
- LOW: Technician
- MEDIUM: Technician + Reviewer
- HIGH: Technician + Supervisor
- CRITICAL: Supervisor + Safety Officer

Approval requires:
- Safety gate not blocked
- Required checklist complete
- Mandatory evidence present
- Required reviewer assigned
- No unresolved critical conflict
- Authorization present

High-risk approval requires justification.

## Approval invalidation

If after approval:
- New evidence is added
- Critical evidence is rejected
- Hypothesis changes significantly
- Safety condition changes

Then approval is marked `STALE` and requires re-review.

## Escalation and exceptions

Escalation reasons: safety concern, insufficient evidence, technician uncertainty,
conflicting evidence, critical equipment, authorization issue, AI uncertainty,
operational urgency.

Exception workflow: authorized humans can proceed despite warnings with explicit
supervisor approval. All exception events are audited.

## Emergency mode

Emergency Investigation flag does NOT bypass safety controls. Instead:
- Higher priority
- Escalation
- Shortened SLA
- Required supervisor review
- Prominent safety warnings

## Audit trail

Every workflow transition produces an audit event via `backend/app/audit.py::log_event`.

Events include: verification_created, technician_assigned, verification_started,
evidence_verified, evidence_rejected, observation_added, measurement_added,
safety_assessment_created, safety_gate_blocked, safety_gate_passed,
approval_requested, approval_approved, approval_rejected, approval_escalated,
approval_invalidated, checklist_item_updated, escalation_created.

## Decision history

Decisions are immutable — append-only. If a decision changes, a new decision record
is created. Both remain visible.

Approval decisions store a snapshot of: hypothesis state, evidence state, safety
state, technician findings, and relevant recommendation.

## API summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/verifications | Create verification |
| GET | /api/verifications | List verifications |
| GET | /api/verifications/{id} | Get verification |
| PATCH | /api/verifications/{id}/status | Update status |
| POST | /api/verifications/{id}/assign | Assign technician |
| POST | /api/verifications/{id}/reviewer | Assign reviewer |
| POST | /api/verifications/{id}/start | Start verification |
| POST | /api/verifications/{id}/evidence-verify | Verify evidence |
| POST | /api/verifications/{id}/observations | Add observation |
| POST | /api/verifications/{id}/measurements | Add measurement |
| POST | /api/verifications/{id}/checklists | Create checklist |
| PATCH | /api/verifications/{id}/checklists/{cid}/items/{iid} | Complete checklist item |
| POST | /api/verifications/{id}/safety-assessment | Create safety assessment |
| GET | /api/verifications/{id}/safety | Get safety data |
| POST | /api/verifications/{id}/safety-gate/evaluate | Evaluate safety gate |
| GET | /api/verifications/{id}/safety-gate | Get safety gate |
| POST | /api/verifications/{id}/request-approval | Request approval |
| POST | /api/verifications/{id}/approve | Approve |
| POST | /api/verifications/{id}/reject | Reject |
| POST | /api/verifications/{id}/escalate | Escalate |
| POST | /api/verifications/{id}/isolation | Record isolation |
| POST | /api/verifications/{id}/permit | Create permit |
| GET | /api/verifications/{id}/scorecard | Get scorecard |
| GET | /api/verifications/approvals | Approval inbox |
| GET | /api/verifications/safety-center | Safety center |
| GET | /api/verifications/dashboard | Dashboard stats |
| GET | /api/verifications/{id}/decisions | Decision history |
| GET | /api/verifications/{id}/escalations | Escalation history |

## Testing

Run from root: `python -m pytest tests/ -q`

- 12 new Stage 8 tests: `tests/test_stage8_verification.py`
- All 146 tests pass (134 original + 12 Stage 8)
- 1 skipped (live Kimi, by design)
- 0 regressions

Test coverage: verification CRUD, state transitions, assignment, evidence
verification, observations, measurements, checklists, safety assessment,
safety gate, approval workflow, self-approval prevention, separation of duties,
stale approval invalidation, escalation, company isolation, RBAC.

## Demo workflow

1. Login as admin
2. Open investigation → click "Send for Verification"
3. Assign technician
4. Technician opens verification workspace
5. Technician verifies evidence items
6. Technician records measurements
7. Technician completes checklist
8. Evaluate safety gate (backend-enforced)
9. Request approval
10. Approver reviews: AI recommendation, evidence, technician findings, safety status
11. Approver approves (or rejects with reason)
12. Timeline updates, audit event appears
13. Investigation ready for Stage 9

## Safety language

Do NOT say: "INDUSTRIA-X guarantees equipment safety."

Say: "INDUSTRIA-X provides configurable safety workflow controls and human approval gates."

Do NOT say: "AI guarantees the correct diagnosis."

Say: "AI provides evidence-grounded decision support with uncertainty."

## Limitations

- Kimi offline here: AI review hook returns honest UNAVAILABLE; deterministic
  engines carry the stage (verified by tests)
- No WebSocket/SSE live updates (polling; documented)
- No un-archive for evidence; no case delete (ARCHIVED terminal state)
- Freshness policy + trust hierarchy use documented defaults
- Isolation confirmation is workflow recording only, NOT physical equipment control
- No complex template engine for checklists (MVP: clean, extensible)
- Multi-process deployment needs Redis for rate limiting (tracked for Stage 10)

## Stage 9 handoff contract

Stage 8 provides clean event structures for Stage 9 replay:

```
Investigation → Verification → Technician → Safety → Approval → Decision
```

Timeline events are stored in `audit_events` with `entity_type = 'verification'`.
Decision snapshots are stored in `approval_decisions`.
Safety gate results are stored in `safety_gate_results`.
All events are queryable by company_id and entity_id.
```
