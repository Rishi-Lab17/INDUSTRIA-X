# INDUSTRIA-X — Sovereign On-Premise Agentic AI Workbench

> Confidential industrial investigation: private docs + sensor + vision →
> Kimi K3 agentic reasoning → multiple hypotheses → evidence →
> next-best-evidence → verification → safety gate → human approval →
> professional PDF report → audit trace.

**Root (only root):** `C:\Users\Rishi K Yadav\Documents\INDUSTRIA-X`
**Demo hero:** PUMP P-204, abnormal vibration.

## Current status

- Stage 1 — COMPLETE (auth, OTP, sessions, RBAC, health, sovereignty)
- Stage 2 — COMPLETE (company workspace, equipment digital passport + QR)
- Stage 3 — NEXT (knowledge base + secure document upload)

## Team Git workflow

`main` (verified releases) ← `develop` (integration) ← `feature/*` (all work).
Never push unfinished work to `main`. Full rules: `CONTRIBUTING.md`.
CI (`.github/workflows/ci.yml`) runs pytest + frontend build, credential-free.

## Features (10 stages)

1. Foundation + auth (JWT, OTP, bcrypt, sessions, RBAC) + premium UI shell
2. Company workspace + RBAC + Equipment Digital Passport (QR)
3. Knowledge base: secure upload (PDF/DOCX/TXT/CSV/XLSX/images), OCR, processing
4. Local embeddings + vector DB + private RAG with provenance (no fake citations)
5. Kimi K3 provider abstraction + AI workbench + agent orchestration
6. Sensor intelligence (real CSV stats/anomalies) + vision (real image analysis)
7. Multiple hypotheses + evidence graph + next-best-evidence
8. Verification + safety gate + technician workflow + human approval
9. PDF reports + case memory + replay + audit + sovereignty center
10. Integration + testing + performance + local deployment + final polish

Every AI/sensor/RAG/verification result comes from a real backend computation.
Hardcoded answers, fake citations, fake progress, and silent external-AI
fallback are forbidden by the build spec and by the code.

## Architecture

Modular monolith: `frontend/` (React+Vite+TS) + `backend/` (FastAPI) +
`ai/` + `agents/` + `rag/` + SQLite + local file storage. See
`docs/architecture.md`. Full doc index lives in `docs/`.

## Setup (Windows, no Docker required)

```powershell
cd "C:\Users\Rishi K Yadav\Documents\INDUSTRIA-X"
copy .env.example .env   # then edit JWT_SECRET
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
python -m uvicorn app.main:app --app-dir backend --port 8000
# second terminal:
cd frontend; npm install; npm run dev
```

Open http://127.0.0.1:5173. Later machines with Docker: `docker compose up`.

## Database

SQLite WAL at `./database/industria-x.db` (zero-install, sovereign).
Schema in `database/`. Switch to Postgres later via `DATABASE_URL`.

## Kimi K3 (honest status)

Primary engine, OpenAI-compatible client at `KIMI_K3_BASE_URL`.
Full Kimi K3 (~2.8T params, ~594 GB–1.4 TB) needs datacenter GPUs and does
**not** run on the current RTX 3050 4 GB laptop — the backend reports Kimi
`OFFLINE` with a clear error instead of faking output. A labelled local dev
model (Ollama) exists only so pipelines can be tested honestly. The UI always
shows the model that actually answered.

## RAG

Upload → validate → store → extract (+OCR) → chunk → local embed → local
vector DB → retrieve → rank → Kimi → answer with document/page/chunk
provenance. Unknown info → "Information not found in the available knowledge
base."

## Demo scenario

Login → open PUMP P-204 → start investigation → load evidence → RAG →
sensor/vision → hypotheses + for/against/missing evidence →
next-best-evidence → technician submission → re-analysis → verification →
safety gate → approval → PDF → case memory → replay → audit → sovereignty.
Seed data: `data/demo/` (clearly fictional).

## Testing

`pytest` per stage (auth, tenant isolation, upload validation, RAG, agents,
sensor/vision, hypotheses, verification, approval, reports, audit) plus
failure cases (bad login, cross-company access, corrupt PDF/CSV, Kimi/vector
DB/DB down, refresh, network loss). No next stage starts with critical
failures.

## Team workflow (6 members, one repo)

Branches `feature/stage-N` → build → test → commit → push → PR → review →
merge to `main`. Never force-push shared branches. Owners: M1 lead/stages
1·5·10; M2 platform/stage 2; M3 knowledge/stages 3·4; M4 multimodal/stage 6;
M5 investigation/stages 7·8; M6 frontend/stage 9 + polish. Details:
`docs/team-workflow.md`.
