# Testing (Stage 1)

Run from the root: `python -m pytest tests/ -v`.

`tests/test_stage1_auth.py` (5 tests, all passing):

- Full flow: register → login-before-verify 403 → wrong OTP 400 →
  verify → login → me → logout → session revoked (401).
- Invalid logins (401), duplicate email/company (409).
- Pydantic validation (422): bad email, short password.
- RBAC: engineer can list but not create users; technician neither.
- Tenant isolation: Company B sees none of Company A's users/audit.
- System: `/api/health` probes DB live; Kimi honestly OFFLINE;
  `/api/sovereignty` reports `ai_active_model: none`, externals BLOCKED.

Failure matrix so far covers: invalid login, unverified login, bad/expired
OTP (expiry logic in code; time-travel test lands Stage 10), unauthorized
role, cross-company access, revoked session, Kimi unreachable, backend
unreachable (frontend shows error state, no fake data).

Rule: no stage is marked COMPLETE with failing tests; no next stage starts
with critical failures open.
