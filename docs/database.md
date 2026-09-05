# Database (Stage 1)

SQLite WAL at `./database/industria-x.db` (zero-install, sovereign, file-local).
Schema source of truth: `database/schema.sql`, applied by `backend/app/db.py::init_db()`
on server startup (FastAPI lifespan).

Tables: `companies`, `users` (bcrypt hash, role, is_active), `otp_codes`
(sha256 hash, expiry, attempt counter, consumed flag), `sessions`
(JWT jti, expiry, revoked flag), `audit_events`, `equipment`, `documents`.

Multi-tenancy: every company-owned row carries `company_id`; the backend
derives it from the verified session, never from client input. Tenant
isolation is asserted by `tests/test_stage1_auth.py`.

Stage 2 additions: `equipment` (company-scoped, `UNIQUE(company_id, code)`,
criticality/status CHECKs, soft delete via `is_active`), `companies.settings`
JSON, `audit_events.entity_type/entity_id` (+ index) linking events to assets.
`init_db()` forward-migrates pre-existing databases with ALTER TABLE.

Stage 3 additions: `documents` (company/equipment/uploader FKs, storage_key,
type/mime/size/sha256, version + parent chain, 7 states + timestamps +
sanitized error + note, extracted_text + extracted_json sections contract,
page_count, ocr_used, is_archived; indexes on company/equipment/status/hash).
No migration needed for existing DBs (new table via schema).

Stage 4 additions: `documents.index_status/indexed_version/indexed_at/`
`index_error/chunk_count/embedding_model/indexed_checksum` (ALTER-migrated);
`database/vectors.db` (gitignored): `chunks` (full provenance metadata +
active flag), `embeddings` (float32 blobs, never exposed), `chunks_fts`
(FTS5 porter, content-synced via explicit triggers + self-healing backfill —
SQLite does not create these automatically).

Upgrade path (Stage 10): swap `DATABASE_URL` to Postgres + add migrations;
no query code changes needed beyond the `db.py` connector.
