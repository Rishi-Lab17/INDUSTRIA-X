# Stage 9: Enterprise Industrial Case Management

## Status: IMPLEMENTED

Stage 9 introduces enterprise-level case management built on Stage 8 verification infrastructure.

## Features

### Case Lifecycle Management
- Create cases from investigations
- Open, in-progress, verification, safety review workflows
- Close cases with final findings
- Reopen closed cases
- Archive cases

### Case Memory System
- Store reusable case knowledge
- Support for equipment type, failure mode, root cause
- Verification levels: UNVERIFIED, PARTIALLY_VERIFIED, VERIFIED, DISPUTED
- Feedback system for memory items

### Lineage Tracking
- End-to-end data lineage
- Nodes for evidence, sensors, documents
- Directed edges showing relationships
- Nodes can have downstream/upstream connected

### Reports
- Generate reports from closed cases
- Report types: PDF
- Report metadata tracking

### Audit Center
- Full audit trail of all actions
- Searchable by action, entity type
- Pagination support

### Sovereignty Center
- Real-time sovereignty health checks
- Data residency settings
- External AI policy enforcement
- Storage location configuration
- Encryption status reporting

### Safety Integration
- Safety center integration
- Dashboard stats for cases

## API Endpoints

All endpoints are under `/api/cases/case`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | / | Create new case |
| GET | / | List cases |
| GET | /{cid} | Get case details |
| PATCH | /{cid} | Update case fields |
| POST | /{cid}/close | Close a case |
| POST | /{cid}/reopen | Reopen closed case |
| POST | /{cid}/archive | Archive a case |
| GET | /{cid}/timeline | Get case timeline |
| GET | /{cid}/integrity | Check case integrity |
| POST | /{cid}/actions | Add action to case |
| POST | /memory | Create case memory |
| POST | /memory/{mid}/feedback | Add memory feedback |
| GET | /memory | List case memories |
| POST | /{cid}/lineage | Add lineage node |
| POST | /{cid}/lineage/edge | Add lineage edge |
| GET | /{cid}/lineage | Get lineage graph |
| GET | /audit | Get audit events |
| GET | /sovereignty | Get sovereignty status |
| PUT | /sovereignty | Update sovereignty config |
| GET | /dashboard | Get dashboard stats |
| GET | /safety-center | Get safety center stats |
| POST | /{cid}/reports | Generate report |
| GET | /{cid}/reports | List reports |

## Frontend Pages

- `/cases` - Case list dashboard
- `/cases/:id` - Case detail view with tabs: Overview, Timeline, Actions, Memory, Lineage
- `/memory` - Case memory browser
- `/reports` - Generated reports
- `/lineage` - Lineage visualization

## Pydantic Models

```python
case_payload.CaseCreate  # Fields: investigation_id, title, summary, priority, severity, equipment_id
case_payload.CasePatch   # Fields: title, summary, priority, severity, root_cause, root_cause_confidence, root_cause_evidence
case_payload.CaseCloseIn # Fields: final_finding, root_cause, failure_mode, corrective_action, preventive_action, resolution_status, resolution_evidence, technician_conclusion, reviewer_conclusion, final_decision
case_payload.CaseReopenIn # Fields: reason (NEW_EVIDENCE, PREVIOUS_CONCLUSION_CHALLENGED, PROBLEM_RECURRED, AUDIT_REVIEW, CORRECTION_REQUIRED, OTHER)
case_payload.ActionIn    # Fields: action_type (CORRECTIVE/PREVENTIVE), description, owner, priority, due_at
case_payload.MemoryIn    # Fields: equipment_type, component, symptoms, sensor_patterns, visual_findings, failure_mode, root_cause, verified_evidence, corrective_action, preventive_action, outcome, lessons, reliability
case_payload.MemoryFeedbackIn # Fields: feedback (USEFUL/NOT_USEFUL/INCORRECT/NEEDS_REVIEW), reason
```

## Database Tables

- `cases` - Main case records
- `case_assignments` - Case assignments to users
- `case_actions` - Corrective/preventive actions
- `case_outcomes` - Action outcomes
- `case_memory` - Reusable case knowledge
- `case_memory_feedback` - Memory feedback records
- `case_revisions` - Case revision history
- `case_closure` - Closure status and details
- `reports` - Generated reports
- `case_exports` - Case export records
- `lineage_nodes` - Data lineage nodes
- `lineage_edges` - Data lineage relationships

## Tests

Run with:
```bash
python -m pytest tests/test_stage9.py -v
```

## Security

- Cases are company-scoped - users from different companies cannot access each other's cases
- Authentication required for all case endpoints (except public read of closed cases)
- RBAC: CREATE, UPDATE, CLOSE, REOPEN, ARCHIVE require COMPANY_ADMIN or ENGINEER role
- All actions are logged for audit purposes