# Stage 5 — Kimi K3 + AI Workbench + Agent Orchestration

Stage 5 adds the AI foundation later stages consume. No multimodality,
hypotheses, approvals (Stages 6–8). No external AI, ever.

## Runtime reality (verified 2026-09-05)

- **Kimi K3 is NOT installed here.** 2.8T params cannot run on this machine;
  no vLLM/SGLang/llama.cpp/Ollama-Kimi endpoint exists. Probes confirm it.
- `KimiK3Provider` (OpenAI-compatible HTTP) is fully implemented and reports
  OFFLINE with latency/reason; AI runs return UNAVAILABLE, never fake text.
- To go live: serve Kimi weights on-prem (`vLLM`/`SGLang`/llama.cpp server),
  set `KIMI_K3_BASE_URL` in `.env`. No code changes needed.
- `TestProvider` (deterministic, labelled TEST ONLY) proves orchestration,
  tools, states, citations — never presented as Kimi.

## Architecture

```
Workbench UI → POST /api/ai/sessions/{id}/messages (SSE optional)
  → rate limit → session ownership → orchestrator.execute()
    → PLANNING (PlannerAgent: deterministic plan + owned-equipment resolve)
    → RETRIEVING (search_knowledge_base tool → Stage 4 hybrid + provenance)
    → GENERATING (provider.generate/stream, timeout-bounded, cancellable)
    → COMPLETED | FAILED | CANCELLED | TIMEOUT | UNAVAILABLE
  → run record + tool runs + audit + (SSE tokens) + citations + plan
```

Modules: `backend/app/ai/` (providers, registry, routing, prompts,
context) + `backend/app/agents/` (tools, planner, rag_agent, orchestrator).

## Providers (`ai/providers.py`)

`AIProvider.generate/stream/health/capabilities`. Kimi: httpx chat
completions + SSE, `trust_env=False` (local traffic never via proxy),
bounded retries on transient only (connect/429/5xx), 4xx never retried,
per-call timeouts, cooperative cancellation, usage passthrough or null.

## Registry / router (`ai/registry.py`)

Single configured model record: id/provider/display/local/is_test/
capabilities (`{supported, verified_live}` — never claimed without proof)/
context_limit null until a runtime reports it/endpoint/status. Health cached
30s. `route(task)`: reasoning/document_qa/tool_planning/coding → kimi-k3
(capability-gated); vision → explicit unavailable; embedding → Stage 4.

## Tools (`agents/tools.py`)

Allowlist of 7: search_knowledge_base, get_equipment, get_equipment_history,
get_document_metadata, get_document_excerpt (4000ch cap), get_system_health
(admin/engineer), get_current_ai_status. Every call: role check → input
validation (int ranges, length caps) → ownership check → bounded execution →
audit (invoked/denied) + tool-run row. Model proposes; server disposes.
No shell/SQL/network/Python execution exists anywhere in the path.

## Agents

- PlannerAgent: deterministic steps [search_knowledge_base (+owned equipment),
  generate] with reasons + summary. No hidden reasoning.
- RAGAgent: hybrid search → top citations → `pack_context` (budgets recorded).
- Orchestrator: explicit states, per-run cancel events, timeout-bounded
  provider calls, max 5 tool calls/run ("Tool execution limit reached."),
  phase timings, prompt template+version on every run.

## Prompts (`ai/prompts.py`)

Versioned (`stage5-v1`): industrial_assistant, document_qa, equipment_assistant,
planner, rag_answer, tool_planner. Evidence-first industrial system prompt
(no fabricated facts/inspections/measurements, no physical actions).

## Context (`ai/context.py`)

Equipment block (owned record only) + evidence block (bounded) + recent
history (20 msgs / half-budget, oldest dropped first, drops recorded).
Citations never dropped by truncation.

## Sessions / runs (DB)

`ai_sessions` (company/user/equipment/title/provider/model),
`ai_messages` (USER/ASSISTANT/SYSTEM/TOOL, no CoT column exists),
`ai_runs` (provider/model/task/template+version/status/error category/
timings/tokens nullable/sources/tools), `ai_tool_runs` (name/inputs-keys/
status/error/duration). All company-scoped; additive migration.

## API (`routers/ai.py`)

Sessions CRUD (owner + admin visibility), messages (sync + SSE stream),
runs detail + cancel, models, health (provider + run metrics), tools
(role-filtered). 401 unauthenticated, 404 foreign, 403 tool-denied inside
200 bodies, 413 oversize, 429 rate-limited, 503 unavailable, 504 timeout.

## Safety

Rate limits (30/user + 200/company per 5 min), message/context/tool-count
caps, audit metadata-only (no prompts with content, no JWTs/keys),
caplog-tested secret silence, sovereignty `external_ai=BLOCKED`,
`ai_workbench: offline-no-model` until a runtime connects.

## UI (`/workbench`)

Sessions sidebar, equipment scope, live model/RAG/external badges, SSE
streaming bubbles, run card (plan ✓ evidence ✓, sources, metrics),
run history table, Stop/Retry, honest OFFLINE banner. Same design system.

## Tests

`tests/test_stage5_ai.py` (~35): selection, config, offline honesty, live
contract (SKIPs without runtime), retry semantics, registry/routing, session
CRUD + isolation, grounded answers + run records, insufficient-evidence,
equipment scoping, cross-company (sessions/runs/tools), tech scope,
SSE format, orchestrator cancel, endpoint cancel, timeout, loop limit,
prompt/rate limits, tool injection/role/oversize, audit+metrics, secret/CoT
silence, sovereignty labels, Kimi-503-no-fallback, full e2e.

## Troubleshooting

- Workbench says OFFLINE → expected until `KIMI_K3_BASE_URL` serves `/models`.
- 503 on send → model unavailable; evidence still recorded on the run.
- 429 → rate limits (config `AI_RUNS_*`); 413 → message cap (`AI_MAX_*`).
