# Stage 7 — Multi-Hypothesis Investigation Intelligence

Stage 7 turns INDUSTRIA-X into an evidence-first investigation platform:
competing hypotheses, a live evidence graph, missing-evidence detection,
ranked Next-Best-Evidence, what-if simulation, confidence evolution, and a
Stage 8 readiness gate. Deterministic engines do the reasoning; Kimi (offline
in this environment) may optionally review via the Stage 5 orchestrator.

## Architecture

```
backend/app/investigation/   scoring.py · missing.py · graph.py
                             similarity.py · hypotheses.py · copilot.py
                             service.py · common.py
backend/app/routers/cases.py        cases + evidence + timeline + assumptions
                                    + conflicts + health + readiness + copilot
backend/app/routers/hypotheses.py   hypotheses + scoring + graph + missing +
                                    NBE + simulate + confidence + similar
```

New API prefix is `/api/cases` (Stage 6 multimodal owns `/api/investigations/*`).

## Data model

`workspaces` (lazy per-company "Default"; company isolation is primary),
`investigations` (status workflow with legal-transition enforcement),
`evidence` (12 types, quality fields, JSON metadata/provenance, soft delete),
`hypotheses`, `evidence_links` (SUPPORTS/CONTRADICTS/NEUTRAL + weight),
`evidence_relations` (manual RELATED_TO/REQUIRES/VERIFIES/SIMILAR_TO),
`hypothesis_scores` (every scoring run → confidence history),
`evidence_recommendations` (ranked NBE, PENDING/DONE/DISMISSED),
`assumptions`, `conflicts`. Timeline is derived from `audit_events`
(entity_type=`investigation`), not a separate table.

## Scoring methodology (transparent, no fake probabilities)

Evidence Quality Q = reliability × confidence × freshness × source_quality,
each in [0,1]; defaults 0.7/0.7 when unset; trust weights from
`DEFAULT_TRUST`, overridable per company via `companies.settings.source_trust`.

Per hypothesis: S/C = quality-weighted SUPPORTS/CONTRADICTS mass;
support = 100·S/(S+C) (0 when empty); contradiction likewise;
completeness = 100·linked_slots/expected_slots; confidence band from
support − 0.5·contradiction gated by completeness (Low/Medium/Medium-High/High).
Rank: support desc, contradiction asc, id asc. Displayed as
"Evidence Support Score" — never "probability".

Independence discount (shared-origin mass) is reported per hypothesis as
`independence` (1.0 = fully independent sources); scores use quality-weighted
mass directly and the factor is shown for transparency.

## Missing evidence + NBE

Expected slots come from a deterministic catalog keyed by equipment-type and
hypothesis keywords (`missing.SLOTS`, `HYPOTHESIS_SLOTS`). Slots fill via
explicit metadata or title/description keyword match. NBE value =
coverage gain (filling a genuinely missing slot) + best simulated separation
change across positive/negative outcomes; ties break by effort, safety, title.
`what_if()` recomputes all scores with one hypothetical link — the same math
powers NBE previews and the `/simulate` endpoint. Terminology used:
"Discriminative Value", "Expected Uncertainty Reduction" (never "Bayesian
information gain").

## Similarity

Resolved/closed same-company cases: equipment-type 30 + category 25 +
problem-statement Jaccard 25 + evidence-title overlap 20 = 0..100
"similarity" (not a probability). Threshold 40 to display, else
"No sufficiently similar historical cases found."

## Copilot, assumptions, conflicts, health

Copilot answers from recorded data only (know/gaps/support/contradict/next/
assumptions/conflicts/summary branches); anything else →
"Insufficient evidence to determine this." Evidence text is data, never
instructions. Assumptions auto-detected (UNVERIFIED default) + patchable.
Conflicts: sensor-anomaly vs technician-normal keyword rules + repeat-
measurement recommendation; refresh is idempotent. Health = coverage,
quality, separation×4, freshness, reliability, critical gaps → LOW/MEDIUM/
HIGH readiness (NOT diagnosis confidence). Gate READY_FOR_VERIFICATION
requires: no critical gaps, no open conflicts, separation ≥ 15, technician
verification; the status transition enforces it (422 otherwise).

## RBAC

Create/edit/status/generate/score/NBE/simulate/refresh: ADMIN + ENGINEER.
Evidence create: all roles (technicians restricted to TECHNICIAN/MANUAL
types). Evidence edit/archive: ADMIN + ENGINEER (+creator for technicians on
own items). View/copilot/graph: all roles. Assumption/conflict updates:
ADMIN + ENGINEER. All server-side via `require_roles` + ownership checks.

## Security

Company_id from session only; foreign ids → 404; pydantic validation on all
inputs (ranges, enums, lengths); LIKE-parameterized search; rate limits on
mutating + copilot/simulate endpoints; sanitized errors; audit on all
mutations; no secrets in logs; prompt-injection tests included.

## Frontend (`/investigations`, `/investigations/:id`)

List + create dialog; dashboard with readiness/evidence/leading-hypothesis
cards; hypothesis cards (support/contradict/neutral, completeness, link
manager, status override, per-hypothesis what-if); evidence manager; NBE
panel with rationale + done; interactive SVG graph (zoom/pan/filter/search/
select, band rings, edge colors); confidence SVG chart; copilot panel;
assumptions/conflicts/similar/timeline panels. Same design system.

## Demo workflow

Login → workspace → equipment P-204 → create case → upload/select sensor CSV,
document, image → annotate → technician note → generate hypotheses → link
evidence → graph → missing → NBE → what-if → confidence → health → readiness
gate → READY_FOR_VERIFICATION (Stage 8 handoff).

## Limitations

- Kimi offline here: AI review hook returns honest UNAVAILABLE; deterministic
  engines carry the stage (verified by tests).
- No WebSocket/SSE live updates (polling; documented, no extra infra).
- No un-archive for evidence; no case delete (ARCHIVED terminal state).
- Freshness policy + trust hierarchy use documented defaults unless a
  company overrides `companies.settings`.
- Graph layout is deterministic radial (no force simulation) for reliability.
