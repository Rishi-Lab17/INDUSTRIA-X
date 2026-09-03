# Database (Stage 1)

SQLite WAL at `./database/industria-x.db` (zero-install, sovereign, file-local).
Schema source of truth: `database/schema.sql`, applied by `backend/app/db.py::init_db()`
on server startup (FastAPI lifespan).

Tables: `companies`, `users` (bcrypt hash, role, is_active), `otp_codes`
(sha256 hash, expiry, attempt counter, consumed flag), `sessions`
(JWT jti, expiry, revoked flag), `audit_events`, `equipment`.

Multi-tenancy: every company-owned row carries `company_id`; the backend
derives it from the verified session, never from client input. Tenant
isolation is asserted by `tests/test_stage1_auth.py`.

Stage 2 additions: `equipment` (company-scoped, `UNIQUE(company_id, code)`,
criticality/status CHECKs, soft delete via `is_active`), `companies.settings`
JSON, `audit_events.entity_type/entity_id` (+ index) linking events to assets.
`init_db()` forward-migrates pre-existing databases with ALTER TABLE.

Upgrade path (Stage 10): swap `DATABASE_URL` to Postgres + add migrations;
no query code changes needed beyond the `db.py` connector.
