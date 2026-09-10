-- Stage 1 schema (SQLite, WAL). Single source of truth; applied by backend/app/db.py.
-- Multi-tenancy: every company-owned row carries company_id. Never trust
-- company_id from the client — the backend derives it from the session.

CREATE TABLE IF NOT EXISTS companies (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,
  settings    TEXT NOT NULL DEFAULT '{}',
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id    INTEGER NOT NULL REFERENCES companies(id),
  name          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('COMPANY_ADMIN','ENGINEER','TECHNICIAN')),
  is_active     INTEGER NOT NULL DEFAULT 0,
  email_verified INTEGER NOT NULL DEFAULT 0,
  phone         TEXT,
  phone_verified INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS sessions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  jti         TEXT NOT NULL UNIQUE,
  user_id     INTEGER NOT NULL REFERENCES users(id),
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  expires_at  TEXT NOT NULL,
  revoked     INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sessions_jti ON sessions(jti);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS audit_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id  INTEGER REFERENCES companies(id),
  user_id     INTEGER REFERENCES users(id),
  action      TEXT NOT NULL,
  detail      TEXT NOT NULL DEFAULT '{}',
  entity_type TEXT,
  entity_id   INTEGER,
  ip          TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_company ON audit_events(company_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_type, entity_id);

-- Stage 2: equipment assets. Tenant-scoped via company_id; human-readable
-- code unique per company (e.g. P-204). Deletion is soft (is_active=0) so
-- history/audit survive.
CREATE TABLE IF NOT EXISTS equipment (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id      INTEGER NOT NULL REFERENCES companies(id),
  code            TEXT NOT NULL,
  name            TEXT NOT NULL,
  type            TEXT NOT NULL,
  manufacturer    TEXT NOT NULL DEFAULT '',
  model           TEXT NOT NULL DEFAULT '',
  serial_number   TEXT NOT NULL DEFAULT '',
  location        TEXT NOT NULL DEFAULT '',
  criticality     TEXT NOT NULL CHECK (criticality IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  status          TEXT NOT NULL DEFAULT 'OPERATIONAL'
                  CHECK (status IN ('OPERATIONAL','DEGRADED','UNDER_MAINTENANCE','DECOMMISSIONED')),
  installed_at    TEXT,
  commissioned_at TEXT,
  metadata        TEXT NOT NULL DEFAULT '{}',
  created_by      INTEGER REFERENCES users(id),
  is_active       INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(company_id, code)
);
CREATE INDEX IF NOT EXISTS idx_equipment_company ON equipment(company_id);
CREATE INDEX IF NOT EXISTS idx_equipment_code ON equipment(company_id, code);

-- Stage 3: knowledge-base documents. Tenant-scoped via company_id; files live
-- under storage/documents|images/{company_id}/{document_id}/, never by raw
-- filename. Versions chain via parent_document_id; retry never versions.
CREATE TABLE IF NOT EXISTS documents (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id          INTEGER NOT NULL REFERENCES companies(id),
  equipment_id        INTEGER REFERENCES equipment(id),
  uploaded_by         INTEGER REFERENCES users(id),
  original_filename   TEXT NOT NULL,
  storage_key         TEXT NOT NULL,
  file_type           TEXT NOT NULL CHECK (file_type IN
                      ('PDF','DOCX','TXT','CSV','XLSX','JPG','JPEG','PNG')),
  mime_type           TEXT NOT NULL,
  file_size           INTEGER NOT NULL,
  sha256_hash         TEXT NOT NULL,
  version             INTEGER NOT NULL DEFAULT 1,
  parent_document_id  INTEGER REFERENCES documents(id),
  processing_status   TEXT NOT NULL DEFAULT 'UPLOADED' CHECK (processing_status IN
                      ('UPLOADED','QUEUED','PROCESSING','COMPLETED','FAILED','RETRYING','ARCHIVED')),
  processing_started_at   TEXT,
  processing_completed_at TEXT,
  processing_error    TEXT,
  processing_note     TEXT,
  extracted_text      TEXT NOT NULL DEFAULT '',
  extracted_json      TEXT NOT NULL DEFAULT '{}',
  page_count          INTEGER,
  ocr_used            INTEGER NOT NULL DEFAULT 0,
  is_archived         INTEGER NOT NULL DEFAULT 0,
  index_status        TEXT NOT NULL DEFAULT 'NOT_INDEXED' CHECK (index_status IN
                      ('NOT_INDEXED','INDEXING','INDEXED','INDEX_FAILED','STALE','REINDEX_REQUIRED')),
  indexed_version     INTEGER,
  indexed_at          TEXT,
  index_error         TEXT,
  chunk_count         INTEGER NOT NULL DEFAULT 0,
  embedding_model     TEXT,
  indexed_checksum    TEXT,
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_company ON documents(company_id);
CREATE INDEX IF NOT EXISTS idx_documents_equipment ON documents(equipment_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(processing_status);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(company_id, sha256_hash);

-- Stage 6: multimodal. Raw sensor bytes live under storage/sensor_data/;
-- readings are normalized long-format rows. Images under storage/images/.
CREATE TABLE IF NOT EXISTS sensor_datasets (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id      INTEGER NOT NULL REFERENCES companies(id),
  equipment_id    INTEGER NOT NULL REFERENCES equipment(id),
  uploaded_by     INTEGER REFERENCES users(id),
  name            TEXT NOT NULL,
  source_filename TEXT NOT NULL,
  storage_key     TEXT NOT NULL,
  sha256_hash     TEXT NOT NULL,
  channels        TEXT NOT NULL DEFAULT '[]',
  row_count       INTEGER NOT NULL DEFAULT 0,
  time_start      REAL,
  time_end        REAL,
  sample_interval_s REAL,
  quality_status  TEXT NOT NULL DEFAULT 'INVALID',
  quality_score   REAL,
  quality_detail  TEXT NOT NULL DEFAULT '{}',
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sensor_datasets_company ON sensor_datasets(company_id);
CREATE INDEX IF NOT EXISTS idx_sensor_datasets_equipment ON sensor_datasets(equipment_id);

CREATE TABLE IF NOT EXISTS sensor_readings (
  dataset_id INTEGER NOT NULL REFERENCES sensor_datasets(id),
  ts         REAL NOT NULL,
  channel    TEXT NOT NULL,
  value      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_lookup
  ON sensor_readings(dataset_id, channel, ts);

CREATE TABLE IF NOT EXISTS analysis_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id    INTEGER NOT NULL REFERENCES companies(id),
  equipment_id  INTEGER REFERENCES equipment(id),
  kind          TEXT NOT NULL CHECK (kind IN ('sensor','vision','multimodal')),
  input_ref     TEXT NOT NULL DEFAULT '{}',
  method        TEXT NOT NULL,
  params        TEXT NOT NULL DEFAULT '{}',
  result_summary TEXT NOT NULL DEFAULT '{}',
  warnings      TEXT NOT NULL DEFAULT '[]',
  created_by    INTEGER REFERENCES users(id),
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_company ON analysis_runs(company_id);

CREATE TABLE IF NOT EXISTS vision_assets (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id    INTEGER NOT NULL REFERENCES companies(id),
  equipment_id  INTEGER NOT NULL REFERENCES equipment(id),
  uploaded_by   INTEGER REFERENCES users(id),
  filename      TEXT NOT NULL,
  storage_key   TEXT NOT NULL,
  mime_type     TEXT NOT NULL,
  file_size     INTEGER NOT NULL,
  width         INTEGER NOT NULL,
  height        INTEGER NOT NULL,
  sha256_hash   TEXT NOT NULL,
  quality_status TEXT NOT NULL DEFAULT 'POOR',
  quality_detail TEXT NOT NULL DEFAULT '{}',
  ocr_status    TEXT NOT NULL DEFAULT 'NOT_ATTEMPTED',
  ocr_text      TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vision_assets_company ON vision_assets(company_id);
CREATE INDEX IF NOT EXISTS idx_vision_assets_equipment ON vision_assets(equipment_id);

CREATE TABLE IF NOT EXISTS vision_annotations (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id    INTEGER NOT NULL REFERENCES vision_assets(id),
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  x           REAL NOT NULL,
  y           REAL NOT NULL,
  w           REAL NOT NULL,
  h           REAL NOT NULL,
  label       TEXT NOT NULL,
  note        TEXT NOT NULL DEFAULT '',
  created_by  INTEGER REFERENCES users(id),
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vision_annotations_asset ON vision_annotations(asset_id);

CREATE TABLE IF NOT EXISTS multimodal_investigations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id    INTEGER NOT NULL REFERENCES companies(id),
  equipment_id  INTEGER NOT NULL REFERENCES equipment(id),
  question      TEXT NOT NULL,
  config        TEXT NOT NULL DEFAULT '{}',
  results       TEXT NOT NULL DEFAULT '{}',
  created_by    INTEGER REFERENCES users(id),
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mm_investigations_company
  ON multimodal_investigations(company_id);

-- Stage 5: AI workbench. All rows company-scoped. No chain-of-thought stored.
CREATE TABLE IF NOT EXISTS ai_sessions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  user_id     INTEGER NOT NULL REFERENCES users(id),
  equipment_id INTEGER REFERENCES equipment(id),
  title       TEXT NOT NULL,
  provider    TEXT NOT NULL,
  model       TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_sessions_company ON ai_sessions(company_id);
CREATE INDEX IF NOT EXISTS idx_ai_sessions_user ON ai_sessions(user_id);

CREATE TABLE IF NOT EXISTS ai_messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER NOT NULL REFERENCES ai_sessions(id),
  role        TEXT NOT NULL CHECK (role IN ('USER','ASSISTANT','SYSTEM','TOOL')),
  content     TEXT NOT NULL,
  model       TEXT,
  tool_name   TEXT,
  run_id      INTEGER,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_messages_session ON ai_messages(session_id);

CREATE TABLE IF NOT EXISTS ai_runs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id      INTEGER NOT NULL REFERENCES companies(id),
  user_id         INTEGER NOT NULL REFERENCES users(id),
  session_id      INTEGER NOT NULL REFERENCES ai_sessions(id),
  equipment_id    INTEGER REFERENCES equipment(id),
  provider        TEXT NOT NULL,
  model           TEXT NOT NULL,
  task_type       TEXT NOT NULL,
  prompt_template TEXT NOT NULL DEFAULT 'industrial_assistant',
  prompt_version  TEXT NOT NULL DEFAULT 'stage5-v1',
  status          TEXT NOT NULL DEFAULT 'QUEUED',
  error_category  TEXT,
  started_at      TEXT,
  ended_at        TEXT,
  duration_ms     INTEGER,
  tokens_in       INTEGER,
  tokens_out      INTEGER,
  sources_count   INTEGER NOT NULL DEFAULT 0,
  tools_used      TEXT NOT NULL DEFAULT '[]',
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_runs_session ON ai_runs(session_id);
CREATE INDEX IF NOT EXISTS idx_ai_runs_company ON ai_runs(company_id);

CREATE TABLE IF NOT EXISTS ai_tool_runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id      INTEGER NOT NULL REFERENCES ai_runs(id),
  tool_name   TEXT NOT NULL,
  input_json  TEXT NOT NULL DEFAULT '{}',
  status      TEXT NOT NULL,
  error       TEXT,
  duration_ms INTEGER,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_tool_runs_run ON ai_tool_runs(run_id);

-- Stage 7: investigation case management. workspaces are lightweight
-- company partitions (a "Default" workspace is lazily provisioned per
-- company; company isolation remains the primary boundary).
CREATE TABLE IF NOT EXISTS workspaces (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  name        TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(company_id, name)
);
CREATE INDEX IF NOT EXISTS idx_workspaces_company ON workspaces(company_id);

CREATE TABLE IF NOT EXISTS investigations (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id        INTEGER NOT NULL REFERENCES companies(id),
  workspace_id      INTEGER REFERENCES workspaces(id),
  equipment_id      INTEGER NOT NULL REFERENCES equipment(id),
  title             TEXT NOT NULL,
  problem_statement TEXT NOT NULL,
  category          TEXT NOT NULL DEFAULT 'UNKNOWN',
  severity          TEXT NOT NULL DEFAULT 'MEDIUM',
  priority          INTEGER NOT NULL DEFAULT 3,
  status            TEXT NOT NULL DEFAULT 'DRAFT',
  created_by        INTEGER REFERENCES users(id),
  assigned_to       INTEGER REFERENCES users(id),
  created_at        TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
  closed_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_investigations_company ON investigations(company_id);
CREATE INDEX IF NOT EXISTS idx_investigations_equipment ON investigations(equipment_id);
CREATE INDEX IF NOT EXISTS idx_investigations_status ON investigations(company_id, status);

CREATE TABLE IF NOT EXISTS evidence (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  investigation_id INTEGER NOT NULL REFERENCES investigations(id),
  company_id      INTEGER NOT NULL REFERENCES companies(id),
  equipment_id    INTEGER REFERENCES equipment(id),
  type            TEXT NOT NULL,
  source          TEXT NOT NULL DEFAULT '',
  title           TEXT NOT NULL,
  description     TEXT NOT NULL DEFAULT '',
  content         TEXT NOT NULL DEFAULT '',
  confidence      REAL,
  reliability     REAL,
  timestamp       TEXT,
  created_by      INTEGER REFERENCES users(id),
  metadata        TEXT NOT NULL DEFAULT '{}',
  provenance      TEXT NOT NULL DEFAULT '{}',
  is_active       INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_evidence_investigation ON evidence(investigation_id);
CREATE INDEX IF NOT EXISTS idx_evidence_company ON evidence(company_id);

CREATE TABLE IF NOT EXISTS hypotheses (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  investigation_id INTEGER NOT NULL REFERENCES investigations(id),
  company_id       INTEGER NOT NULL REFERENCES companies(id),
  title            TEXT NOT NULL,
  description      TEXT NOT NULL DEFAULT '',
  category         TEXT NOT NULL DEFAULT 'UNKNOWN',
  status           TEXT NOT NULL DEFAULT 'ACTIVE',
  created_by       INTEGER REFERENCES users(id),
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_hypotheses_investigation ON hypotheses(investigation_id);

CREATE TABLE IF NOT EXISTS evidence_links (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  hypothesis_id INTEGER NOT NULL REFERENCES hypotheses(id),
  evidence_id   INTEGER NOT NULL REFERENCES evidence(id),
  relation      TEXT NOT NULL,
  weight        REAL NOT NULL DEFAULT 1.0,
  created_by    INTEGER REFERENCES users(id),
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(hypothesis_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_links_hyp ON evidence_links(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_evidence_links_ev ON evidence_links(evidence_id);

CREATE TABLE IF NOT EXISTS evidence_relations (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id  INTEGER NOT NULL REFERENCES companies(id),
  from_type   TEXT NOT NULL,
  from_id     INTEGER NOT NULL,
  to_type     TEXT NOT NULL,
  to_id       INTEGER NOT NULL,
  relation    TEXT NOT NULL,
  created_by  INTEGER REFERENCES users(id),
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_evidence_relations_from
  ON evidence_relations(company_id, from_type, from_id);

CREATE TABLE IF NOT EXISTS hypothesis_scores (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  hypothesis_id   INTEGER NOT NULL REFERENCES hypotheses(id),
  support_score   REAL NOT NULL,
  contradiction_score REAL NOT NULL,
  completeness    REAL NOT NULL,
  confidence_band TEXT NOT NULL,
  trigger         TEXT NOT NULL DEFAULT 'manual',
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_hypothesis_scores_hyp ON hypothesis_scores(hypothesis_id);

CREATE TABLE IF NOT EXISTS evidence_recommendations (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  investigation_id INTEGER NOT NULL REFERENCES investigations(id),
  company_id      INTEGER NOT NULL REFERENCES companies(id),
  rank            INTEGER NOT NULL,
  kind            TEXT NOT NULL,
  slot            TEXT NOT NULL DEFAULT '',
  title           TEXT NOT NULL,
  rationale       TEXT NOT NULL DEFAULT '{}',
  expected_value  TEXT NOT NULL DEFAULT 'MEDIUM',
  priority        TEXT NOT NULL DEFAULT 'MEDIUM',
  effort          TEXT NOT NULL DEFAULT 'MEDIUM',
  safety          TEXT NOT NULL DEFAULT 'LOW',
  status          TEXT NOT NULL DEFAULT 'PENDING',
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_evidence_recs_inv ON evidence_recommendations(investigation_id);

CREATE TABLE IF NOT EXISTS assumptions (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  investigation_id INTEGER NOT NULL REFERENCES investigations(id),
  company_id       INTEGER NOT NULL REFERENCES companies(id),
  text             TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'UNVERIFIED',
  created_by       INTEGER REFERENCES users(id),
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_assumptions_inv ON assumptions(investigation_id);

CREATE TABLE IF NOT EXISTS conflicts (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  investigation_id INTEGER NOT NULL REFERENCES investigations(id),
  company_id       INTEGER NOT NULL REFERENCES companies(id),
  evidence_a_id    INTEGER NOT NULL REFERENCES evidence(id),
  evidence_b_id    INTEGER NOT NULL REFERENCES evidence(id),
  description      TEXT NOT NULL,
  recommendation   TEXT NOT NULL DEFAULT '',
  status           TEXT NOT NULL DEFAULT 'OPEN',
  created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
  CREATE INDEX IF NOT EXISTS idx_conflicts_inv ON conflicts(investigation_id);

  -- Stage 8: verification + safety gate + technician workflow + human approval.
  -- Every record carries company_id; tenant derived from session only.

  -- VerificationCase: formal verification request linked to a Stage 7 investigation.
  CREATE TABLE IF NOT EXISTS verifications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id    INTEGER NOT NULL REFERENCES investigations(id),
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    workspace_id        INTEGER REFERENCES workspaces(id),
    equipment_id        INTEGER NOT NULL REFERENCES equipment(id),
    assigned_technician_id INTEGER REFERENCES users(id),
    assigned_reviewer_id   INTEGER REFERENCES users(id),
    status              TEXT NOT NULL DEFAULT 'PENDING'
      CHECK (status IN ('PENDING','ASSIGNED','IN_REVIEW','INSPECTION_REQUIRED',
                        'AWAITING_EVIDENCE','SAFETY_REVIEW','AWAITING_APPROVAL',
                        'APPROVED','REJECTED','ESCALATED','BLOCKED',
                        'CANCELLED','COMPLETED')),
    priority            TEXT NOT NULL DEFAULT 'MEDIUM'
      CHECK (priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    reason              TEXT NOT NULL DEFAULT '',
    instructions        TEXT NOT NULL DEFAULT '',
    safety_requirements TEXT NOT NULL DEFAULT '',
    due_at              TEXT,
    started_at          TEXT,
    completed_at        TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(investigation_id)
  );
  CREATE INDEX IF NOT EXISTS idx_verifications_company ON verifications(company_id);
  CREATE INDEX IF NOT EXISTS idx_verifications_investigation ON verifications(investigation_id);
  CREATE INDEX IF NOT EXISTS idx_verifications_status ON verifications(company_id, status);

  -- Verification assignment history (tracks all assignment changes).
  CREATE TABLE IF NOT EXISTS verification_assignments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL REFERENCES verifications(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    role            TEXT NOT NULL CHECK (role IN ('TECHNICIAN','REVIEWER')),
    assigned_to     INTEGER NOT NULL REFERENCES users(id),
    assigned_by     INTEGER REFERENCES users(id),
    assigned_at     TEXT NOT NULL DEFAULT (datetime('now')),
    note            TEXT NOT NULL DEFAULT ''
  );
  CREATE INDEX IF NOT EXISTS idx_va_verification ON verification_assignments(verification_id);

  -- Evidence verification: technician confirms/rejects individual evidence items.
  CREATE TABLE IF NOT EXISTS evidence_verifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL REFERENCES verifications(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    evidence_id     INTEGER NOT NULL REFERENCES evidence(id),
    verified_by     INTEGER NOT NULL REFERENCES users(id),
    status          TEXT NOT NULL CHECK (status IN ('VERIFIED','REJECTED','UNABLE_TO_VERIFY','CONTRADICTED','NOT_APPLICABLE')),
    comment         TEXT NOT NULL DEFAULT '',
    measurement     TEXT NOT NULL DEFAULT '',
    attachment      TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_ev_verification ON evidence_verifications(verification_id);
  CREATE INDEX IF NOT EXISTS idx_ev_evidence ON evidence_verifications(evidence_id);

  -- Technician observations: first-class evidence from inspection.
  CREATE TABLE IF NOT EXISTS technician_observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL REFERENCES verifications(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    equipment_id    INTEGER NOT NULL REFERENCES equipment(id),
    technician_id   INTEGER NOT NULL REFERENCES users(id),
    observation_type TEXT NOT NULL CHECK (observation_type IN ('VISUAL','AUDITORY','MEASUREMENT','MECHANICAL','ELECTRICAL','THERMAL','PROCESS','SAFETY','OTHER')),
    description     TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'NORMAL'
      CHECK (severity IN ('NORMAL','MINOR','MODERATE','SEVERE','CRITICAL')),
    observed_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_to_verification ON technician_observations(verification_id);
  CREATE INDEX IF NOT EXISTS idx_to_equipment ON technician_observations(equipment_id);

  -- Technician measurements: structured numeric readings.
  CREATE TABLE IF NOT EXISTS technician_measurements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL REFERENCES verifications(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    equipment_id    INTEGER NOT NULL REFERENCES equipment(id),
    technician_id   INTEGER NOT NULL REFERENCES users(id),
    parameter       TEXT NOT NULL,
    value           REAL NOT NULL,
    unit            TEXT NOT NULL,
    instrument_id   TEXT NOT NULL DEFAULT '',
    instrument_type TEXT NOT NULL DEFAULT '',
    calibration_status TEXT NOT NULL DEFAULT 'UNKNOWN'
      CHECK (calibration_status IN ('VALID','EXPIRED','UNKNOWN')),
    calibration_date TEXT,
    calibration_expiry TEXT,
    notes           TEXT NOT NULL DEFAULT '',
    recorded_at     TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_tm_verification ON technician_measurements(verification_id);

  -- Inspection checklists: configurable per equipment type/failure category.
  CREATE TABLE IF NOT EXISTS inspection_checklists (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL REFERENCES verifications(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    template_key    TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_ic_verification ON inspection_checklists(verification_id);

  CREATE TABLE IF NOT EXISTS checklist_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    checklist_id    INTEGER NOT NULL REFERENCES inspection_checklists(id),
    description     TEXT NOT NULL,
    required        INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'PENDING'
      CHECK (status IN ('PENDING','PASS','FAIL','SKIPPED')),
    completed_by    INTEGER REFERENCES users(id),
    completed_at    TEXT,
    comment         TEXT NOT NULL DEFAULT ''
  );
  CREATE INDEX IF NOT EXISTS idx_ci_checklist ON checklist_items(checklist_id);

  -- Safety assessment: risk evaluation per verification.
  CREATE TABLE IF NOT EXISTS safety_assessments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id     INTEGER NOT NULL REFERENCES verifications(id),
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    risk_level          TEXT NOT NULL DEFAULT 'LOW'
      CHECK (risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    likelihood          INTEGER NOT NULL DEFAULT 1 CHECK (likelihood BETWEEN 1 AND 5),
    impact              INTEGER NOT NULL DEFAULT 1 CHECK (impact BETWEEN 1 AND 5),
    assessor            INTEGER REFERENCES users(id),
    assessed_at         TEXT NOT NULL DEFAULT (datetime('now')),
    notes               TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_sa_verification ON safety_assessments(verification_id);

  -- Hazards within a safety assessment.
  CREATE TABLE IF NOT EXISTS hazards (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    safety_assessment_id INTEGER NOT NULL REFERENCES safety_assessments(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    hazard_type     TEXT NOT NULL CHECK (hazard_type IN ('ROTATING_EQUIPMENT','ELECTRICAL','THERMAL','PRESSURE','CHEMICAL','CONFINED_SPACE','FIRE','OTHER')),
    severity        TEXT NOT NULL DEFAULT 'MEDIUM'
      CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    likelihood      INTEGER NOT NULL DEFAULT 1 CHECK (likelihood BETWEEN 1 AND 5),
    control         TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'OPEN'
      CHECK (status IN ('OPEN','CONTROLLED','CLOSED')),
    owner           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_hazards_safety ON hazards(safety_assessment_id);

  -- Safety controls associated with a safety assessment.
  CREATE TABLE IF NOT EXISTS safety_controls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    safety_assessment_id INTEGER NOT NULL REFERENCES safety_assessments(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    control_type    TEXT NOT NULL,
    description     TEXT NOT NULL,
    required        INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'PENDING'
      CHECK (status IN ('PENDING','ACTIVE','VERIFIED','EXPIRED')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_sc_safety ON safety_controls(safety_assessment_id);

  -- Isolation / LOTO-style confirmation (workflow recording only, NOT physical control).
  CREATE TABLE IF NOT EXISTS isolation_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL REFERENCES verifications(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    isolation_required INTEGER NOT NULL DEFAULT 0,
    isolation_confirmed INTEGER NOT NULL DEFAULT 0,
    confirmed_by    INTEGER REFERENCES users(id),
    confirmed_at    TEXT,
    method          TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_ir_verification ON isolation_records(verification_id);

  -- Digital permit record.
  CREATE TABLE IF NOT EXISTS permits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL REFERENCES verifications(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    permit_id       TEXT NOT NULL,
    equipment_id    INTEGER NOT NULL REFERENCES equipment(id),
    requested_by    INTEGER NOT NULL REFERENCES users(id),
    authorized_by   INTEGER REFERENCES users(id),
    start_time      TEXT NOT NULL,
    expiry_time     TEXT NOT NULL,
    hazards         TEXT NOT NULL DEFAULT '',
    controls        TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'DRAFT'
      CHECK (status IN ('DRAFT','REQUESTED','APPROVED','ACTIVE','EXPIRED','CANCELLED')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE UNIQUE INDEX IF NOT EXISTS idx_permits_verification ON permits(verification_id);
  CREATE INDEX IF NOT EXISTS idx_permits_company ON permits(company_id);

  -- Approval workflow: human decisions on verifications.
  CREATE TABLE IF NOT EXISTS approvals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL REFERENCES verifications(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    requested_by    INTEGER NOT NULL REFERENCES users(id),
    approver_id     INTEGER REFERENCES users(id),
    approval_level  TEXT NOT NULL DEFAULT 'TECHNICIAN'
      CHECK (approval_level IN ('TECHNICIAN','TECHNICIAN_REVIEWER','SUPERVISOR','SAFETY_OFFICER')),
    status          TEXT NOT NULL DEFAULT 'PENDING'
      CHECK (status IN ('PENDING','APPROVED','REJECTED','REQUEST_MORE_EVIDENCE','ESCALATED','DEFERRED','INVALIDATED','STALE')),
    reason          TEXT NOT NULL DEFAULT '',
    comment         TEXT NOT NULL DEFAULT '',
    justification   TEXT NOT NULL DEFAULT '',
    requested_at    TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at      TEXT,
    expires_at      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_approvals_verification ON approvals(verification_id);
  CREATE INDEX IF NOT EXISTS idx_approvals_company ON approvals(company_id);

  -- Immutable decision history (append-only; never overwrite).
  CREATE TABLE IF NOT EXISTS approval_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_id     INTEGER NOT NULL REFERENCES approvals(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    decision        TEXT NOT NULL CHECK (decision IN ('APPROVE','REJECT','REQUEST_MORE_EVIDENCE','ESCALATE','DEFER')),
    actor           INTEGER NOT NULL REFERENCES users(id),
    actor_role      TEXT NOT NULL,
    reason          TEXT NOT NULL DEFAULT '',
    comment         TEXT NOT NULL DEFAULT '',
    evidence_snapshot TEXT NOT NULL DEFAULT '{}',
    safety_snapshot TEXT NOT NULL DEFAULT '{}',
    hypothesis_snapshot TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_ad_approval ON approval_decisions(approval_id);

  -- Escalation tracking.
  CREATE TABLE IF NOT EXISTS escalations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL REFERENCES verifications(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    escalated_by    INTEGER NOT NULL REFERENCES users(id),
    escalated_to    INTEGER NOT NULL REFERENCES users(id),
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'OPEN'
      CHECK (status IN ('OPEN','RESOLVED','CANCELLED')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_escalation_verification ON escalations(verification_id);

  -- Safety gate evaluation results (backend-enforced blocking control).
  CREATE TABLE IF NOT EXISTS safety_gate_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL REFERENCES verifications(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    blocked         INTEGER NOT NULL DEFAULT 0,
    risk_level      TEXT NOT NULL DEFAULT 'LOW',
    reasons         TEXT NOT NULL DEFAULT '[]',
    missing_checklist TEXT NOT NULL DEFAULT '[]',
    missing_evidence TEXT NOT NULL DEFAULT '[]',
    missing_permit  INTEGER NOT NULL DEFAULT 0,
    missing_isolation INTEGER NOT NULL DEFAULT 0,
    evaluated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    evaluated_by    INTEGER REFERENCES users(id)
  );
  CREATE UNIQUE INDEX IF NOT EXISTS idx_sgr_verification ON safety_gate_results(verification_id);

  -- Verification scorecard (computed snapshot for decision readiness).
  CREATE TABLE IF NOT EXISTS verification_scorecards (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id INTEGER NOT NULL REFERENCES verifications(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    evidence_coverage REAL NOT NULL DEFAULT 0,
    evidence_quality REAL NOT NULL DEFAULT 0,
    technician_verification REAL NOT NULL DEFAULT 0,
    safety_readiness REAL NOT NULL DEFAULT 0,
    hypothesis_confidence REAL NOT NULL DEFAULT 0,
    critical_conflicts INTEGER NOT NULL DEFAULT 0,
    approval_readiness TEXT NOT NULL DEFAULT 'NOT_READY',
    evaluated_at    TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE UNIQUE INDEX IF NOT EXISTS idx_vs_verification ON verification_scorecards(verification_id);

  -- Stage 9: enterprise case management, reporting, memory, replay, lineage, audit, sovereignty.
  -- Every record carries company_id; tenant derived from session only.

  -- Case: persistent case management layer around investigation.
  CREATE TABLE IF NOT EXISTS cases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_number     TEXT NOT NULL,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    workspace_id    INTEGER REFERENCES workspaces(id),
    investigation_id INTEGER REFERENCES investigations(id),
    equipment_id    INTEGER NOT NULL REFERENCES equipment(id),
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    priority        TEXT NOT NULL DEFAULT 'MEDIUM' CHECK (priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    severity        TEXT NOT NULL DEFAULT 'INFORMATIONAL' CHECK (severity IN ('INFORMATIONAL','MINOR','MODERATE','MAJOR','CRITICAL')),
    status          TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','INVESTIGATING','VERIFICATION','SAFETY_REVIEW','AWAITING_APPROVAL','APPROVED','ACTION_IN_PROGRESS','RESOLVED','CLOSED','REOPENED','ARCHIVED')),
    root_cause      TEXT NOT NULL DEFAULT '',
    root_cause_confidence TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (root_cause_confidence IN ('CONFIRMED','PROBABLE','UNKNOWN','DISPUTED')),
    root_cause_evidence TEXT NOT NULL DEFAULT '[]',
    resolution_status TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (resolution_status IN ('RESOLVED','PARTIALLY_RESOLVED','NOT_RESOLVED','UNKNOWN')),
    resolution_evidence TEXT NOT NULL DEFAULT '',
    opened_by       INTEGER REFERENCES users(id),
    closed_by       INTEGER REFERENCES users(id),
    opened_at       TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at     TEXT,
    closed_at       TEXT,
    archived_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_cases_company ON cases(company_id);
  CREATE INDEX IF NOT EXISTS idx_cases_investigation ON cases(investigation_id);
  CREATE INDEX IF NOT EXISTS idx_cases_equipment ON cases(equipment_id);
  CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(company_id, status);
  CREATE INDEX IF NOT EXISTS idx_cases_number ON cases(company_id, case_number);

  -- Case assignment history.
  CREATE TABLE IF NOT EXISTS case_assignments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES cases(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    role            TEXT NOT NULL CHECK (role IN ('OWNER','INVESTIGATOR','TECHNICIAN','REVIEWER','APPROVER')),
    assigned_to     INTEGER NOT NULL REFERENCES users(id),
    assigned_by     INTEGER REFERENCES users(id),
    assigned_at     TEXT NOT NULL DEFAULT (datetime('now')),
    note            TEXT NOT NULL DEFAULT ''
  );
  CREATE INDEX IF NOT EXISTS idx_ca_case ON case_assignments(case_id);

  -- Corrective/preventive actions.
  CREATE TABLE IF NOT EXISTS case_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES cases(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    action_type     TEXT NOT NULL CHECK (action_type IN ('CORRECTIVE','PREVENTIVE')),
    description     TEXT NOT NULL,
    owner           TEXT NOT NULL DEFAULT '',
    priority        TEXT NOT NULL DEFAULT 'MEDIUM' CHECK (priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    status          TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','IN_PROGRESS','COMPLETED','CANCELLED','BLOCKED')),
    due_at          TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    completion_notes TEXT NOT NULL DEFAULT '',
    completion_evidence TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_ca_case ON case_actions(case_id);

  -- Action verification results.
  CREATE TABLE IF NOT EXISTS case_action_verifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id       INTEGER NOT NULL REFERENCES case_actions(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    verified_by     INTEGER NOT NULL REFERENCES users(id),
    result          TEXT NOT NULL CHECK (result IN ('RESOLVED','PARTIALLY_RESOLVED','NOT_RESOLVED','UNKNOWN')),
    notes           TEXT NOT NULL DEFAULT '',
    verified_at     TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_cav_action ON case_action_verifications(action_id);

  -- Case outcome tracking.
  CREATE TABLE IF NOT EXISTS case_outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES cases(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    outcome         TEXT NOT NULL CHECK (outcome IN ('RESOLVED','PARTIALLY_RESOLVED','NOT_RESOLVED','UNKNOWN')),
    evidence        TEXT NOT NULL DEFAULT '',
    verified_by     INTEGER REFERENCES users(id),
    verified_at     TEXT NOT NULL DEFAULT (datetime('now')),
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_co_case ON case_outcomes(case_id);

  -- Case memory: reusable organizational knowledge from verified cases.
  CREATE TABLE IF NOT EXISTS case_memory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER REFERENCES cases(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    equipment_type  TEXT NOT NULL DEFAULT '',
    component       TEXT NOT NULL DEFAULT '',
    symptoms        TEXT NOT NULL DEFAULT '',
    sensor_patterns TEXT NOT NULL DEFAULT '',
    visual_findings TEXT NOT NULL DEFAULT '',
    failure_mode    TEXT NOT NULL DEFAULT '',
    root_cause      TEXT NOT NULL DEFAULT '',
    verified_evidence TEXT NOT NULL DEFAULT '[]',
    corrective_action TEXT NOT NULL DEFAULT '',
    preventive_action TEXT NOT NULL DEFAULT '',
    outcome         TEXT NOT NULL DEFAULT '',
    lessons         TEXT NOT NULL DEFAULT '',
    reliability     TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (reliability IN ('VERIFIED','PARTIALLY_VERIFIED','UNVERIFIED','DISPUTED')),
    verified_by     INTEGER REFERENCES users(id),
    verified_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','VERIFIED','PARTIALLY_VERIFIED','UNVERIFIED','DISPUTED')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_cm_company ON case_memory(company_id);
  CREATE INDEX IF NOT EXISTS idx_cm_equipment ON case_memory(equipment_type);
  CREATE INDEX IF NOT EXISTS idx_cm_failure ON case_memory(failure_mode);

  -- Case memory feedback (prevents silent rewriting of history).
  CREATE TABLE IF NOT EXISTS case_memory_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id       INTEGER NOT NULL REFERENCES case_memory(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    user_id         INTEGER NOT NULL REFERENCES users(id),
    feedback        TEXT NOT NULL CHECK (feedback IN ('USEFUL','NOT_USEFUL','INCORRECT','NEEDS_REVIEW')),
    reason          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_cmf_memory ON case_memory_feedback(memory_id);

  -- Case revisions (meaningful investigation revisions).
  CREATE TABLE IF NOT EXISTS case_revisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES cases(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    investigation_id INTEGER REFERENCES investigations(id),
    revision_number INTEGER NOT NULL,
    description     TEXT NOT NULL,
    evidence_state  TEXT NOT NULL DEFAULT '{}',
    hypothesis_state TEXT NOT NULL DEFAULT '[]',
    verification_state TEXT NOT NULL DEFAULT '{}',
    safety_state    TEXT NOT NULL DEFAULT '{}',
    approval_state  TEXT NOT NULL DEFAULT '{}',
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_cr_case ON case_revisions(case_id);

  -- Case closure tracking.
  CREATE TABLE IF NOT EXISTS case_closure (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES cases(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    closure_status  TEXT NOT NULL DEFAULT 'NOT_CLOSED' CHECK (closure_status IN ('NOT_CLOSED','READY','BLOCKED','CLOSED','REOPENED','ARCHIVED')),
    final_finding   TEXT NOT NULL DEFAULT '',
    root_cause      TEXT NOT NULL DEFAULT '',
    failure_mode    TEXT NOT NULL DEFAULT '',
    corrective_action TEXT NOT NULL DEFAULT '',
    preventive_action TEXT NOT NULL DEFAULT '',
    resolution_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    resolution_evidence TEXT NOT NULL DEFAULT '',
    technician_conclusion TEXT NOT NULL DEFAULT '',
    reviewer_conclusion TEXT NOT NULL DEFAULT '',
    final_decision  TEXT NOT NULL DEFAULT '',
    closed_by       INTEGER REFERENCES users(id),
    closed_at       TEXT,
    reopened_reason TEXT,
    reopened_by     INTEGER REFERENCES users(id),
    reopened_at     TEXT,
    archived_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE UNIQUE INDEX IF NOT EXISTS idx_cc_case ON case_closure(case_id);

  -- Reports (generated investigation reports).
  CREATE TABLE IF NOT EXISTS reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES cases(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    report_id       TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    generated_by    INTEGER NOT NULL REFERENCES users(id),
    status          TEXT NOT NULL DEFAULT 'CURRENT' CHECK (status IN ('CURRENT','STALE','ARCHIVED')),
    integrity_hash  TEXT NOT NULL DEFAULT '',
    format          TEXT NOT NULL DEFAULT 'PDF' CHECK (format IN ('PDF','JSON','CSV')),
    file_path       TEXT NOT NULL DEFAULT '',
    file_size       INTEGER NOT NULL DEFAULT 0,
    report_data     TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    generated_at    TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_reports_case ON reports(case_id);
  CREATE INDEX IF NOT EXISTS idx_reports_company ON reports(company_id);
  CREATE INDEX IF NOT EXISTS idx_reports_id ON reports(report_id);

  -- Case exports (authorized export tracking).
  CREATE TABLE IF NOT EXISTS case_exports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES cases(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    export_id       TEXT NOT NULL,
    exported_by     INTEGER NOT NULL REFERENCES users(id),
    format          TEXT NOT NULL DEFAULT 'PACKAGE' CHECK (format IN ('PDF','JSON','PACKAGE')),
    manifest        TEXT NOT NULL DEFAULT '{}',
    manifest_hash   TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('COMPLETED','FAILED','CANCELLED')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_ce_case ON case_exports(case_id);

  -- Data lineage nodes.
  CREATE TABLE IF NOT EXISTS lineage_nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES cases(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    node_id         TEXT NOT NULL,
    node_type       TEXT NOT NULL CHECK (node_type IN ('SOURCE','PROCESSING','DOCUMENT','CHUNK','EMBEDDING','SENSOR_DATA','IMAGE','FINDING','EVIDENCE','HYPOTHESIS','VERIFICATION','SAFETY','DECISION','ACTION','OUTCOME','REPORT')),
    label           TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}',
    upstream_node_ids TEXT NOT NULL DEFAULT '[]',
    downstream_node_ids TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_ln_case ON lineage_nodes(case_id);
  CREATE INDEX IF NOT EXISTS idx_ln_node ON lineage_nodes(node_id);

  -- Case comments (internal operational commentary).
  CREATE TABLE IF NOT EXISTS comments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES cases(id),
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    author_id       INTEGER NOT NULL REFERENCES users(id),
    message         TEXT NOT NULL,
    parent_id       INTEGER REFERENCES comments(id),
    edited_at       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_comments_case ON comments(case_id);

  -- Sovereignty configuration (actual deployment state).
  CREATE TABLE IF NOT EXISTS sovereignty_config (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    data_residency  TEXT NOT NULL DEFAULT 'UNKNOWN',
    external_ai_policy TEXT NOT NULL DEFAULT 'BLOCKED',
    external_network_policy TEXT NOT NULL DEFAULT 'DISABLED',
    vector_db_location TEXT NOT NULL DEFAULT 'LOCAL',
    document_storage TEXT NOT NULL DEFAULT 'LOCAL',
    encryption_status TEXT NOT NULL DEFAULT 'NOT_CONFIGURED',
    retention_documents TEXT NOT NULL DEFAULT 'UNCONFIGURED',
    retention_evidence TEXT NOT NULL DEFAULT 'UNCONFIGURED',
    retention_reports TEXT NOT NULL DEFAULT 'UNCONFIGURED',
    retention_audit TEXT NOT NULL DEFAULT 'UNCONFIGURED',
    retention_memory TEXT NOT NULL DEFAULT 'UNCONFIGURED',
    backup_enabled  INTEGER NOT NULL DEFAULT 0,
    audit_enabled   INTEGER NOT NULL DEFAULT 1,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE UNIQUE INDEX IF NOT EXISTS idx_sc_company ON sovereignty_config(company_id);

  -- Sovereignty health check results.
  CREATE TABLE IF NOT EXISTS sovereignty_health (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    check_name      TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('PASS','WARNING','BLOCKED','UNKNOWN')),
    detail          TEXT NOT NULL DEFAULT '',
    checked_at      TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_sh_company ON sovereignty_health(company_id);

  -- Stage 10: Live Video Investigation Recording System.
  -- Recording sessions track live camera/microphone recordings during investigations.

  CREATE TABLE IF NOT EXISTS recording_sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    workspace_id        INTEGER REFERENCES workspaces(id),
    investigation_id    INTEGER REFERENCES investigations(id),
    case_id             INTEGER REFERENCES cases(id),
    equipment_id        INTEGER NOT NULL REFERENCES equipment(id),
    title               TEXT NOT NULL DEFAULT '',
    description         TEXT NOT NULL DEFAULT '',
    media_type          TEXT NOT NULL DEFAULT 'video' CHECK (media_type IN ('video','audio','video+audio')),
    status              TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','RECORDING','PAUSED','PROCESSING','COMPLETED','FAILED','ARCHIVED')),
    started_at          TEXT,
    stopped_at          TEXT,
    paused_at           TEXT,
    paused_duration     INTEGER NOT NULL DEFAULT 0,
    duration_seconds    INTEGER NOT NULL DEFAULT 0,
    created_by          INTEGER NOT NULL REFERENCES users(id),
    storage_key         TEXT NOT NULL DEFAULT '',
    file_size           INTEGER NOT NULL DEFAULT 0,
    sha256_hash         TEXT NOT NULL DEFAULT '',
    integrity_hash      TEXT NOT NULL DEFAULT '',
    processing_status   TEXT NOT NULL DEFAULT 'PENDING' CHECK (processing_status IN ('PENDING','QUEUED','PROCESSING','COMPLETED','FAILED')),
    processing_started_at TEXT,
    processing_completed_at TEXT,
    processing_error    TEXT NOT NULL DEFAULT '',
    sovereignty_classification TEXT NOT NULL DEFAULT 'INTERNAL' CHECK (sovereignty_classification IN ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_rs_company ON recording_sessions(company_id);
  CREATE INDEX IF NOT EXISTS idx_rs_investigation ON recording_sessions(investigation_id);
  CREATE INDEX IF NOT EXISTS idx_rs_case ON recording_sessions(case_id);
  CREATE INDEX IF NOT EXISTS idx_rs_equipment ON recording_sessions(equipment_id);
  CREATE INDEX IF NOT EXISTS idx_rs_status ON recording_sessions(company_id, status);

  -- Recording chunks for large video files.
  CREATE TABLE IF NOT EXISTS recording_chunks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id        INTEGER NOT NULL REFERENCES recording_sessions(id),
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    chunk_index         INTEGER NOT NULL,
    chunk_size          INTEGER NOT NULL,
    chunk_sha256        TEXT NOT NULL,
    storage_key         TEXT NOT NULL,
    start_time          REAL NOT NULL,
    end_time            REAL NOT NULL,
    duration_seconds    REAL NOT NULL,
    uploaded_at         TEXT NOT NULL DEFAULT (datetime('now')),
    status              TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','UPLOADING','COMPLETED','FAILED','MERGED')),
    error_message       TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_rc_recording ON recording_chunks(recording_id);
  CREATE INDEX IF NOT EXISTS idx_rc_status ON recording_chunks(recording_id, status);
  CREATE UNIQUE INDEX IF NOT EXISTS idx_rc_unique ON recording_chunks(recording_id, chunk_index);

  -- Recording frames (keyframes extracted for analysis).
  CREATE TABLE IF NOT EXISTS recording_frames (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id        INTEGER NOT NULL REFERENCES recording_sessions(id),
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    investigation_id    INTEGER REFERENCES investigations(id),
    case_id             INTEGER REFERENCES cases(id),
    equipment_id        INTEGER NOT NULL REFERENCES equipment(id),
    frame_index         INTEGER NOT NULL,
    timestamp_seconds   REAL NOT NULL,
    recording_timestamp_seconds REAL NOT NULL,
    frame_timestamp     TEXT NOT NULL,
    storage_key         TEXT NOT NULL,
    file_size           INTEGER NOT NULL,
    sha256_hash         TEXT NOT NULL,
    width               INTEGER NOT NULL,
    height              INTEGER NOT NULL,
    capture_type        TEXT NOT NULL DEFAULT 'MANUAL' CHECK (capture_type IN ('MANUAL','PERIODIC','EVENT_TRIGGERED')),
    analysis_status     TEXT NOT NULL DEFAULT 'PENDING' CHECK (analysis_status IN ('PENDING','QUEUED','PROCESSING','COMPLETED','FAILED')),
    analysis_started_at TEXT,
    analysis_completed_at TEXT,
    analysis_error      TEXT NOT NULL DEFAULT '',
    vision_result       TEXT NOT NULL DEFAULT '{}',
    captured_by         INTEGER NOT NULL REFERENCES users(id),
    captured_at         TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at        TEXT
  );
  CREATE INDEX IF NOT EXISTS idx_rf_recording ON recording_frames(recording_id);
  CREATE INDEX IF NOT EXISTS idx_rf_investigation ON recording_frames(investigation_id);
  CREATE INDEX IF NOT EXISTS idx_rf_case ON recording_frames(case_id);
  CREATE INDEX IF NOT EXISTS idx_rf_analysis ON recording_frames(analysis_status);

  -- AI interactions during live recording.
  CREATE TABLE IF NOT EXISTS recording_ai_interactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id        INTEGER NOT NULL REFERENCES recording_sessions(id),
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    investigation_id    INTEGER REFERENCES investigations(id),
    case_id             INTEGER REFERENCES cases(id),
    user_id             INTEGER NOT NULL REFERENCES users(id),
    question            TEXT NOT NULL,
    answer              TEXT NOT NULL DEFAULT '',
    provider            TEXT NOT NULL DEFAULT '',
    model               TEXT NOT NULL DEFAULT '',
    recording_timestamp_seconds REAL NOT NULL,
    wall_clock_timestamp TEXT NOT NULL,
    context_snapshot    TEXT NOT NULL DEFAULT '{}',
    latency_ms          INTEGER,
    tokens_in           INTEGER,
    tokens_out          INTEGER,
    provenance          TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_rai_recording ON recording_ai_interactions(recording_id);
  CREATE INDEX IF NOT EXISTS idx_rai_investigation ON recording_ai_interactions(investigation_id);
  CREATE INDEX IF NOT EXISTS idx_rai_case ON recording_ai_interactions(case_id);

  -- Recording events (timeline integration).
  CREATE TABLE IF NOT EXISTS recording_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id        INTEGER NOT NULL REFERENCES recording_sessions(id),
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    investigation_id    INTEGER REFERENCES investigations(id),
    case_id             INTEGER REFERENCES cases(id),
    event_type          TEXT NOT NULL CHECK (event_type IN ('RECORDING_STARTED','RECORDING_PAUSED','RECORDING_RESUMED','RECORDING_STOPPED','FRAME_CAPTURED','EVIDENCE_CREATED','AI_QUESTION','AI_RESPONSE','OBSERVATION_ADDED','MEASUREMENT_ADDED','PROCESSING_STARTED','PROCESSING_COMPLETED','PROCESSING_FAILED','RECORDING_COMPLETED','RECORDING_ARCHIVED')),
    timestamp_seconds   REAL,
    recording_timestamp_seconds REAL,
    wall_clock_timestamp TEXT NOT NULL,
    user_id             INTEGER REFERENCES users(id),
    payload             TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_re_recording ON recording_events(recording_id);
  CREATE INDEX IF NOT EXISTS idx_re_type ON recording_events(event_type);
  CREATE INDEX IF NOT EXISTS idx_re_timestamp ON recording_events(wall_clock_timestamp);

  -- Recording evidence (linking frames to evidence system).
  CREATE TABLE IF NOT EXISTS recording_evidence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id        INTEGER NOT NULL REFERENCES recording_sessions(id),
    frame_id            INTEGER NOT NULL REFERENCES recording_frames(id),
    evidence_id         INTEGER NOT NULL REFERENCES evidence(id),
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    investigation_id    INTEGER NOT NULL REFERENCES investigations(id),
    case_id             INTEGER REFERENCES cases(id),
    created_by          INTEGER NOT NULL REFERENCES users(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_rev_recording ON recording_evidence(recording_id);
  CREATE INDEX IF NOT EXISTS idx_rev_frame ON recording_evidence(frame_id);
  CREATE INDEX IF NOT EXISTS idx_rev_evidence ON recording_evidence(evidence_id);

  -- Recording transcripts (for optional voice questions).
  CREATE TABLE IF NOT EXISTS recording_transcripts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id        INTEGER NOT NULL REFERENCES recording_sessions(id),
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    segment_index       INTEGER NOT NULL,
    start_time          REAL NOT NULL,
    end_time            REAL NOT NULL,
    transcript_text     TEXT NOT NULL,
    language            TEXT NOT NULL DEFAULT 'en',
    confidence          REAL,
    created_by          INTEGER NOT NULL REFERENCES users(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_rt_recording ON recording_transcripts(recording_id);
