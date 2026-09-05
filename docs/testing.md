# Testing (Stages 1–4)

Run from the root: `python -m pytest tests/ -v` (55 tests, all passing).

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

`tests/test_stage3_documents.py` (14 tests): auth-required, RBAC matrix
(tech upload/view/download only; engineer retry; admin archive/delete),
all-format uploads with real content assertions, rejections (extension/MIME/
traversal/empty/oversize/vendor-MIME acceptance), malformed-PDF safety + error
leak scan, retry success/fail paths (never versions), SHA-256 + duplicate +
version chains, storage layout safety, full cross-company 404s, download
bytes/type, preview shape, filters + injection probe, archive/delete semantics,
complete audit trail, OCR-abstraction honesty (unavailable engine).

`tests/test_stage4_rag.py` (16 tests): real fastembed provider (384d,
deterministic, labelled test provider), structure-aware chunking + metadata,
index lifecycle + duplicate skip, hybrid search with validated provenance
(no vectors/scores-mislabelled), equipment scoping, INSUFFICIENT_EVIDENCE,
version consistency + historical retrieval, archive/delete vector semantics,
cross-company 404s, RBAC matrix, honest INDEX_FAILED + retry, query
normalization, dedup + rank tracking, KB health + search audit, live
evaluation (MRR/precision/recall/latency + negative control), offline
sockets-blocked search + index, perf bounds with printed timings.

Failure matrix covers: invalid login, unverified login, wrong/expired/reused
OTP, resend cooldown + hourly cap, verify brute-force, Resend outage/reject,
unknown-email resend, unauthorized role, cross-company access, revoked
session, Kimi unreachable, backend unreachable (frontend shows error state,
no fake data).

Rule: no stage is marked COMPLETE with failing tests; no next stage starts
with critical failures open.
