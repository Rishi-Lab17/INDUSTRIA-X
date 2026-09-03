# API (Stage 1)

Base: `http://127.0.0.1:8000`. Interactive docs: `/docs`.

Auth (`backend/app/routers/auth.py`):

- `POST /api/auth/register` {company_name, name, email, password} → 201
  {company_id, user_id, dev_otp?} (`dev_otp` only when `APP_ENV=local`).
- `POST /api/auth/verify-otp` {email, code} → activates account.
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
