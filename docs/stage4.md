# Stage 4 — Embeddings + Vector DB + Private RAG + Provenance

Stage 4 turns the Stage 3 Knowledge Base into a local-first retrieval engine.
No Kimi/agents (Stage 5). No external calls anywhere: onnx embeddings, SQLite
vectors + FTS5 lexical, deterministic local rerank — all on this machine.

## Architecture

```
COMPLETED document
  → chunk_sections() (structure-aware: headings/pages/tables/row-groups,
     target 800 / min 200 / max 2000 chars, ~120ch sentence-boundary overlap)
  → FastEmbedProvider (sentence-transformers/all-MiniLM-L6-v2, 384d, onnx CPU)
  → vectors.db (chunks + float32 blobs + FTS5 porter index, content-synced
     via explicit triggers + self-healing backfill on init)
  → hybrid_search(): semantic cosine + BM25 + metadata filters
  → local rerank (equipment +0.15, exact-phrase +0.10) with initial/final rank
  → checksum + near-dup (>0.95) dedup
  → provenance validation against live rows
  → OK citations | INSUFFICIENT_EVIDENCE
  → pack_context() (Stage-5-ready, truncation recorded)
```

Modules (`backend/app/rag/`): `embeddings.py` (provider ABC, fastembed +
labelled deterministic test provider, singleton + override hook, metadata
registry), `chunking.py`, `store.py`, `retrieval.py` (hybrid/rerank/dedup/
provenance/normalization/packing), `service.py` (index pipeline, health,
eval). API: `routers/knowledge.py`. UI: Search, KB index controls, Eval.

## Embeddings

Real onnx weights, cached from HF on first run (~80MB), offline afterwards.
Deterministic per input. Identity + dimension come from the live model and
are stored per chunk; index/search enforce model match (never silently mix).
`EMBEDDING_PROVIDER=test-deterministic` exists for fast unit contexts; those
vectors are labelled `is_test` and the default production path never uses them.

## Chunk metadata

chunk_id, document_id (= version row), company_id, equipment_id, filename,
version, page/pages, section heading, source_type, chunk_index, char_count,
sha256 checksum, embedding_model, active flag, created_at, full text.

## Index states (documents.index_status)

NOT_INDEXED → INDEXING → INDEXED | INDEX_FAILED; STALE when superseded by a
newer version (chunks deactivate, history kept); archived docs keep status
but chunks deactivate; delete removes chunks+vectors+FTS rows. Duplicate
content+model re-index is skipped via stored `indexed_checksum` (no wasted
embeddings). Failures keep the source document COMPLETED and retry cleanly.

## Retrieval

`POST /api/knowledge/search` {query, equipment_id?, document_id?, source_types?,
top_k?, include_historical?}. Company filter always applies server-side;
equipment/document ids are ownership-checked (else 404). Scores are relevance
signals (`semantic_score`, `lexical_score`, `combined_score`) — never
probabilities. `MIN_RELEVANCE_SCORE=0.25` (documented meaning: minimum combined
relevance; below it → INSUFFICIENT_EVIDENCE with candidates/best/threshold).

Query normalization is deterministic (lowercase, equipment-code spacing,
fixed abbreviation map); original + normalized both returned and audited.

Historical mode (`include_historical`) searches inactive chunks; default
searches current only. Equipment scope filters AND boosts (+0.15).

## Provenance

Every citation validates live: doc exists, company matches, chunk exists +
belongs to doc/version, active unless historical. Citation: document_id,
version, chunk_id, filename, page, section, equipment, 300-char excerpt from
stored text, scores, ranks, method (hybrid/semantic/lexical), why_retrieved
signals (equipment/keyword/semantic/phrase/version — deterministic, no
chain-of-thought).

## Health

`GET /api/knowledge/health`: real counts (total/ready/indexed/indexing/stale/
failed/not_indexed, chunks total/active, model + dimension + models in store,
vector_db ONLINE/ERROR, last indexed). `/api/health` probes embeddings +
vector store live.

## Evaluation

`GET /api/knowledge/eval` (ADMIN/ENGINEER): 6 synthetic Pump P-204 questions
(+1 negative control) executed against live retrieval; reports rank, MRR,
precision@K, recall@K, latency, pass/fail + summary. Requires the EVAL-P204
corpus indexed (the test suite builds it; see test_stage4_rag). Eval UI at
`/eval`. Nothing hardcoded — scores come from the real pipeline.

## Configuration (.env)

EMBEDDING_PROVIDER/EMBEDDING_MODEL/VECTOR_DB_PATH, CHUNK_TARGET/MIN/MAX/
OVERLAP_CHARS, RETRIEVAL_TOP_K/CANDIDATES/ALPHA, MIN_RELEVANCE_SCORE,
RERANK_EQUIPMENT/PHRASE_BOOST, MAX_CONTEXT_CHUNKS/CHARS. Safe defaults;
no environment-specific paths (all relative to repo root).

## Offline behavior

After the one-time model download, indexing + search run with loopback-only
network (asserted by test: sockets blocked → search + fresh index succeed).
fastembed/onnxruntime/SQLite/FTS5 need no network at runtime.

## Security

Company filter is applied in SQL before scoring AND re-validated per citation;
cross-company doc/equipment/chunk access → 404; RBAC: search all roles,
index/reindex ADMIN+ENGINEER, eval ADMIN+ENGINEER. Raw vectors never leave
the backend (asserted: no `vector` key in any response). vectors.db is
gitignored (`*.db`) with the app DB. Search audit logs query metadata +
counts, never document content or secrets.

## Troubleshooting

- `INDEX_FAILED` with model error → first run needs network once for the
  ~80MB download; check `/api/knowledge/health` embedding fields.
- Legacy vectors.db from early builds → `init_store()` migrates contentless
  FTS, creates sync triggers, backfills missing index rows automatically.
- Threshold too strict/lenient → tune `MIN_RELEVANCE_SCORE` (documented).

## Stage 5 boundary

Stage 5 consumes `POST /api/knowledge/search` citations + `pack_context`
output. No agent/Kimi code lives here.
