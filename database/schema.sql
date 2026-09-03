-- Stage 1 schema (SQLite, WAL). Single source of truth; applied by backend/app/db.py.
-- Multi-tenancy: every company-owned row carries company_id. Never trust
-- company_id from the client — the backend derives it from the session.

CREATE TABLE IF NOT EXISTS companies (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,
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
  ip          TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_company ON audit_events(company_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action);
