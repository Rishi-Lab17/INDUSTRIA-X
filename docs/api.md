# API (Stage 1)

Base: `http://127.0.0.1:8000`. Interactive docs: `/docs`.

Auth (`backend/app/routers/auth.py`):

- `POST /api/auth/register` {company_name, name, email, password, mobile_number?}
  → 201 {message, email_masked, dev_mode}. The 6-digit OTP is delivered via
  the Resend API (`dev_mode: false`, message "Verification code sent to your
  email address.") or, when unconfigured in local dev, saved to the
  server-side outbox file (`dev_mode: true`, message "Development mode: no
  external email was sent. ...") — NEVER in the response. No provider outside
  local → HTTP 502 (fails loudly, never faked). Resend rejects/outages →
  HTTP 502, account stays unverified.
- `POST /api/auth/verify-otp` {email, code} → "Email verified successfully."
  Wrong → 400 "Invalid verification code. Please try again."; expired/consumed
  → 400 "Verification code expired. Please request a new code."; >10 tries/10min
  → 429. Single-use: consumed immediately on success (no replay).
- `POST /api/auth/resend-otp` {email} → invalidates all pending codes, emails a
  fresh one. 60s cooldown per email (429 + Retry-After), 5/hour cap. Unknown or
  already-verified emails get a generic success (no enumeration).
- `POST /api/auth/phone/link` (auth) {id_token} → verifies Firebase ID token,
  links phone_number. Firebase unconfigured → 501; bad token → 401. Firebase
  only proves number ownership; company/RBAC/sessions/audit stay INDUSTRIA-X.
- `POST /api/auth/login` {email, password} → {access_token, user}.
- `POST /api/auth/logout` (auth) → revokes session jti.
- `GET /api/auth/me` (auth) → {user, company}.
- `POST /api/auth/users` (COMPANY_ADMIN) → create ENGINEER/TECHNICIAN in own company.
- `GET /api/auth/users` (COMPANY_ADMIN, ENGINEER) → own-company users only.
- `GET /api/auth/audit` (COMPANY_ADMIN, ENGINEER) → own-company events.

System (`backend/app/routers/system.py`):

- `GET /api/health` → {status, services{backend, database, storage, kimi,
  dev_model, rag, vector_db, sensor_engine, vision_engine}, latency_ms}.
  Kimi/RAG/vector/sensor/vision honestly OFFLINE until their stages.
- `GET /api/sovereignty` → env-driven guarantees + live `ai_active_model`
  (`"none"` until a Kimi K3 server is reachable) + `kimi_reachable`.

Conventions: JWT Bearer, tenant from session, 401 unauthenticated,
403 wrong role / unverified, 409 duplicate, 422 validation.

Company + equipment — Stage 2 (`routers/company.py`, `routers/equipment.py`):

- `GET /api/company` (all roles) → {company, members, stats}.
- `PATCH /api/company` (COMPANY_ADMIN) → rename / merge settings.
- `GET /api/equipment[?status=&criticality=&q=]` (all roles) → own-company assets.
- `POST /api/equipment` (ADMIN, ENGINEER) → 201 passport; 409 duplicate code.
- `GET /api/equipment/{id}` (all roles) → passport; foreign id → 404.
- `PATCH /api/equipment/{id}` (ADMIN, ENGINEER) → partial update + audit.
- `DELETE /api/equipment/{id}` (ADMIN) → soft deactivate (history kept).
- `GET /api/equipment/{id}/qr` (all roles) → PNG QR of the passport payload.
- `GET /api/equipment/{id}/history` (ADMIN, ENGINEER) → per-asset audit trail.

Knowledge Base — Stage 3 (`routers/documents.py`, `processing/`):

- `POST /api/documents` (multipart file + optional equipment_id; all roles)
  → 201 metadata; identical bytes → 200 `{duplicate: true}`; 413 oversize;
  422 validation. Synchronous local processing to COMPLETED/FAILED.
- `GET /api/documents` (filters: equipment_id, file_type, processing_status,
  is_archived, search, page/page_size) → metadata + 300-char preview only.
- `GET /api/documents/{id}` · `GET /{id}/preview` (full text + sections) ·
  `GET /{id}/download` (streamed, safe filename).
- `POST /{id}/retry` (ADMIN, ENGINEER; FAILED only) — never versions.
- `POST /{id}/archive` + `DELETE /{id}` (ADMIN; soft-hide / permanent + audit).
- Cross-company ids → 404 everywhere; errors sanitized.
