# INDUSTRIA-X — Architecture (modular monolith, local-first)

> Single repo root: `C:\Users\Rishi K Yadav\Documents\INDUSTRIA-X`.
> Nothing belonging to the project lives outside it.

## 1. Product flow

```
PROBLEM -> EQUIPMENT -> PRIVATE DATA -> RAG / SENSOR / VISION
  -> KIMI K3 -> AGENTS -> HYPOTHESES (n>=2) + EVIDENCE (for/against/missing)
  -> NEXT-BEST-EVIDENCE -> VERIFICATION -> SAFETY GATE
  -> HUMAN APPROVAL -> PDF REPORT -> AUDIT TRACE
```

The differentiator is **evidence-first investigation**, not a chatbot.

## 2. Runtime topology (today, no Docker on this machine)

```
[Vite React SPA :5173] --JWT--> [FastAPI :8000] --> [SQLite ./database]
        |                              |--> [local storage/ docs,images,sensors,reports]
        |                              |--LightRAG--> [AI provider abstraction]
        |-- health/sovereignty reads ---+--> [Ollama :11434] (dev model only, labelled)
                                       +--> [Kimi K3 endpoint] (primary, errors clearly if absent)
```

Why this stack:

- **Modular monolith** (spec §44): one backend, one frontend, no K8s/service mesh.
- **SQLite (WAL)** instead of Postgres: zero-install, file-local, sovereign;
  upgrade path to Postgres is a single `DATABASE_URL` change (Stage 10).
- **Local vector store** (Stage 4): SQLite file at `./database/vectors.db`
  with cosine similarity over fastembed onnx vectors + FTS5/BM25 lexical arm.
  No server, no cloud.
- **Frontend**: React + Vite + TypeScript + Tailwind, dark-navy command-center
  theme (`#071521` bg, `#00A6C7` accent). Served separately in dev, static in prod.

## 3. AI provider abstraction (spec §7 — no silent fallback)

```
agents/orchestrator -> ai/providers/base.py (interface)
                       |-- ai/providers/kimi_k3.py   (PRIMARY, OpenAI-compatible)
                       |-- ai/providers/ollama_dev.py (DEV ONLY, labelled)
```

Rules enforced in code:

1. Default and only production path is `kimi-k3`.
2. If Kimi K3 is unreachable → HTTP 502 with `model_active: "none"` and a
   clear message. **Never fabricate an answer, never silently swap models.**
3. Every AI response carries `model_active` + `sovereignty` flags; the UI
   renders exactly that string. No hard claim of "air-gapped".
4. No OpenAI/Claude/Gemini keys are wired. The `OPENAI_API_KEY` found in the
   environment is ignored by the backend.

## 4. Honest Kimi K3 hardware position (verified 2026-09-03)

- Kimi K3 ≈ 2.8T params (MoE, 104B active), ~594 GB 1-bit GGUF / ~1.4 TB MXFP4.
- Producers recommend multi-GPU clusters (8×H100 minimum class / 64-accelerator
  guidance). **This laptop (RTX 3050 4 GB, 15.3 GB RAM) cannot load it.**
- Installed today: Ollama 0.33.2 + `Nemotron-3-Nano-4B Q4` only. No Kimi weights.
- Consequence: backend ships with a real Kimi K3 client + real health check
  that reports `OFFLINE` until an on-prem Kimi server is connected; pipelines
  are tested end-to-end against the labelled dev model without ever claiming
  "Kimi ran".

## 5. Backend modules (map to stages)

| Dir        | Contents (stage)                              |
| ---------- | --------------------------------------------- |
| `backend/` | FastAPI app, auth (S1), companies/equip (S2)  |
| `rag/`     | chunking/embed/retrieve/rank/provenance (S4)  |
| `backend/app/ai/` | providers (Kimi OpenAI-compat + TEST), model
  registry + router + cached health, versioned prompts, context builder (S5) |
| `backend/app/agents/` | allowlisted tools, PlannerAgent, RAGAgent,
  orchestrator state machine + run tracking (S5; vision/sensor/hypothesis
  agents land in later stages) |
| `database/`| schema + migrations + seeds (S1–S2)           |
| `storage/` | runtime uploads (git-ignored)                 |
| `data/demo`| fictional PUMP P-204 demo set (S6/hero demo)  |

Investigation state machine (S7):
`CREATED → PLANNING → COLLECTING_EVIDENCE → ANALYZING → WAITING_FOR_EVIDENCE
→ VERIFYING → AWAITING_APPROVAL → APPROVED|REJECTED → COMPLETED`.

## 6. Multi-tenancy (spec §12)

Every row in company-owned tables carries `company_id`. Tenant is derived
from the JWT session server-side; `company_id` from the client is ignored.
Stage 1+2 tests assert Company A ↔ B isolation explicitly.

## 7. Sovereignty & health (spec §8/§31/§32)

`/api/sovereignty` returns values read from env + live probes — never static
 marketing copy. `/api/health` probes backend, DB, vector DB, Kimi, RAG,
 storage, sensor/vision engines with `ONLINE|OFFLINE|DEGRADED|ERROR`.

## 8. What is deliberately NOT built

Kubernetes, microservices, cloud vector DBs, Supabase/Firebase/Clerk auth,
external AI fallback, Vercel dependency. Vercel later = static frontend mirror
only; the local system stays authoritative.
