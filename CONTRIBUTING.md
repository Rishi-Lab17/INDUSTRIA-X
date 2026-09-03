# Contributing to INDUSTRIA-X

Six members, one repository. Protect `main` — it always holds verified work.

## Branch workflow

```
main          ← verified releases only (PR from develop after full verification)
  ↑
develop       ← integration branch (PRs from feature branches)
  ↑
feature/*     ← all real work happens here
```

Suggested member branches: `feature/member-1-integration`,
`feature/member-2-platform`, `feature/member-3-knowledge`,
`feature/member-4-multimodal`, `feature/member-5-investigation`,
`feature/member-6-product`. Stage branches (`feature/stage-N`) are also fine.

## Rules

1. **Never work directly on `main`.** Never push unfinished work to `main`.
2. Clone, then branch off `develop`:
   `git checkout develop; git pull; git checkout -b feature/<yours>`
3. **Before every PR:** `python -m pytest tests/ -q` (from repo root) AND
   `npm run build` (in `frontend/`). Both must pass.
4. Never force-push shared branches. Never rewrite history on `main`/`develop`.
5. PR → review (reviewer re-runs tests) → merge into `develop`.
   `develop` → `main` only after full verification (tests + build + smoke).

## Never commit

- `.env` (copy `.env.example` → `.env`, fill locally; JWT + Resend keys stay local)
- `*.db` / `*.sqlite*` databases
- `storage/documents|images|sensor_data|reports|temporary/*` runtime uploads
  (only `storage/*/.gitkeep` and `data/demo/*` seed files are tracked)
- `node_modules/`, `frontend/dist/`, `.venv/`, `__pycache__/`, `*.log`
- API keys, passwords, JWT secrets, OTP values, private documents

## Local run (no credentials required)

```powershell
copy .env.example .env   # set a long random JWT_SECRET
pip install -r backend\requirements.txt
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
# second terminal:
cd frontend; npm install; npm run dev   # http://127.0.0.1:5173
```

Email OTP works without any key: `APP_ENV=local` writes mail to
`storage/temporary/dev-outbox/`. With `RESEND_API_KEY` + `RESEND_FROM_EMAIL`
set, delivery goes through Resend (backend only).

## Manual branch protection (GitHub → Settings → Branches → Add rule for `main`)

- Require a pull request before merging
- Require status checks to pass (CI)
- Do not allow bypassing the above settings
- Do not allow force pushes
