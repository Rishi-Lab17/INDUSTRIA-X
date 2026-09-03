# Testing (Stage 1 + email-OTP hardening)

Run from the root: `python -m pytest tests/ -v` (12 tests, all passing).

`tests/test_stage1_auth.py` (5 tests): full register→verify→login→me→logout→
revoked flow (OTP read from the server-side SMTP sink, never the API),
401/403/409/422 cases, RBAC matrix, A↔B tenant isolation, live health/
sovereignty probes.

`tests/test_email_otp.py` (7 tests, sink = real SMTP over TCP):
real delivery asserted (envelope RCPT = exact email, subject, one 6-digit
code); response contains no OTP; DB stores sha256 hash only; correct code
verifies and cannot be replayed; wrong/expired messages exact; resend issues a
new code and kills the old; 60s cooldown (429 + Retry-After); hourly cap and
10-min verify rate limit enforced; unconfigured SMTP → 502 without OTP leak;
unconfigured Firebase → 501; audit rows scanned for code leakage (none).

Leak audits (manual, must stay clean): grep frontend `src/` for
`dev_otp|devOtp|console.log` → none; grep backend for `print(|dev_otp` → none.

Failure matrix now also covers: expired OTP, reused OTP, resend cooldown,
verify brute-force, SMTP outage, unknown-email resend (generic success).

Failure matrix covers: invalid login, unverified login, wrong/expired/reused
OTP, resend cooldown + hourly cap, verify brute-force, SMTP outage,
unknown-email resend, unauthorized role, cross-company access, revoked
session, Kimi unreachable, backend unreachable (frontend shows error state,
no fake data).

Rule: no stage is marked COMPLETE with failing tests; no next stage starts
with critical failures open.
