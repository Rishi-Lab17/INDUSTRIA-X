# Testing (Stage 1 + email-OTP hardening + Stage 2)

Run from the root: `python -m pytest tests/ -v` (25 tests, all passing).

`tests/test_stage1_auth.py` (5 tests): full register→verify→login→me→logout→
revoked flow (OTP read from the fake provider's server-side record, never the
API), 401/403/409/422 cases, RBAC matrix, A↔B tenant isolation, live health/
sovereignty probes.

`tests/test_email_otp.py` (13 tests: A–I + provider/failure coverage, fake
Resend HTTP server): provider selection (key+flag → Resend, else development);
real provider call asserted (POST /emails, Bearer auth, exact from/to/subject,
single code in body, server-side only); response contains no OTP and no API
key; DB stores sha256 hash only; correct code verifies and cannot be replayed;
wrong/expired messages exact; resend issues a new code and kills the old; 60s
cooldown (429 + Retry-After); hourly cap and 10-min verify rate limit
enforced; Resend 500/429/unreachable → safe 502 with account unverified;
unconfigured provider → 502 outside local, dev-outbox file inside local (with
recipient/subject/OTP/timestamps/purpose, zero external calls); caplog leak
audit (no OTP/key/headers/JWTs in logs); health `email_provider` and
sovereignty `email_delivery` reporting in both modes.

Leak audits (manual, must stay clean): grep frontend `src/` for
`dev_otp|devOtp|console.log` → none; grep backend for `print(|dev_otp` → none.

Failure matrix now also covers: expired OTP, reused OTP, resend cooldown,
verify brute-force, SMTP outage, unknown-email resend (generic success).

`tests/test_stage2_equipment.py` (7 tests): company profile read/patch RBAC,
equipment CRUD + soft delete, full role matrix (tech read-only incl. QR,
engineer no-delete, admin full), cross-company 404s on every endpoint,
per-company code reuse, validation/422s, QR PNG magic + payload + auth,
unauthenticated blocking, per-asset history ordering with audit persistence
after deactivation.

Failure matrix covers: invalid login, unverified login, wrong/expired/reused
OTP, resend cooldown + hourly cap, verify brute-force, Resend outage/reject,
unknown-email resend, unauthorized role, cross-company access, revoked
session, Kimi unreachable, backend unreachable (frontend shows error state,
no fake data).

Rule: no stage is marked COMPLETE with failing tests; no next stage starts
with critical failures open.
