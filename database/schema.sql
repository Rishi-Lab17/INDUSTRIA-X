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
  phone         TEXT,
  phone_verified INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS otp_codes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id),
  code_hash   TEXT NOT NULL,
  expires_at  TEXT NOT NULL,
  consumed    INTEGER NOT NULL DEFAULT 0,
  attempts    INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_otp_user ON otp_codes(user_id);

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
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_company ON documents(company_id);
CREATE INDEX IF NOT EXISTS idx_documents_equipment ON documents(equipment_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(processing_status);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(company_id, sha256_hash);
