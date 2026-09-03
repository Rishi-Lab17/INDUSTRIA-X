# Setup (Stage 1, Windows, no Docker needed)

Prereqs (verified on this machine): Node 24 + npm 11, Python 3.13 + pip,
Git 2.55, Ollama 0.33.2. Docker: NOT installed — not required until Stage 10.

```powershell
cd "C:\Users\Rishi K Yadav\Documents\INDUSTRIA-X"
copy .env.example .env   # set a long random JWT_SECRET
pip install -r backend\requirements.txt
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
# second terminal:
cd frontend; npm install; npm run dev   # http://127.0.0.1:5173
```

Vite proxies `/api` → backend, so no frontend env file is needed in dev.
`npm run build` produces `frontend/dist/` (verified). Tests:
`python -m pytest tests/ -v` (isolated temp DB, BCRYPT_ROUNDS=4).

## Email OTP via Resend (production) / local outbox (dev)

Set `RESEND_API_KEY` + `RESEND_FROM_EMAIL` in `.env` (key from
https://resend.com/api-keys, verified sender domain). The FastAPI backend
POSTs to `https://api.resend.com/emails` — the key never touches the
frontend. With `APP_ENV=local` and no key, verification mail is written to
`storage/temporary/dev-outbox/<email>.eml` (gitignored) and the API returns
`dev_mode: true` with an explicit message — the code never appears in any
response, log, or UI. Any other `APP_ENV` without a key → HTTP 502 (loud).
