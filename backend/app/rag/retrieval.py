"""Hybrid retrieval: semantic cosine + lexical BM25 + metadata filters, local
rerank (equipment/phrase signals), dedup, validated provenance citations,
context packing, and an honest INSUFFICIENT_EVIDENCE state.

Scores are retrieval relevance signals — NEVER probabilities or confidence.
initial_rank = pure semantic order; final_rank = after hybrid + boosts.
"""
import hashlib
import math
import re

from ..core.config import get_settings
from . import store
from .embeddings import get_embedding_provider

STOPWORDS = frozenset(
    "a an the and or of to in on for with what which who whom whose is are was"
    " were be been do does did how when where why show tell give me my our it"
    " its this that these those as at by from into about".split())

ABBREV = {
    "vib": "vibration", "vibs": "vibration", "temp": "temperature",
    "temps": "temperature", "press": "pressure", "maint": "maintenance",
    "insp": "inspection", "brg": "bearing", "rtd": "rtd", "nde": "nde",
    "od": "od", "id": "id",
}

_EQUIP_RE = re.compile(r"\b([a-z]{1,4})\s*-?\s*(\d{1,4})\b", re.I)


def normalize_query(query: str) -> str:
    """Deterministic normalization only: lowercase, equipment-code spacing
    canonicalized (p204 → p-204), known abbreviations expanded. No facts
    invented; original query is always preserved alongside."""
    q = (query or "").strip().lower()
    q = _EQUIP_RE.sub(lambda m: f"{m.group(1)}-{m.group(2)}", q)
    q = " ".join(ABBREV.get(t, t) for t in q.split())
    return re.sub(r"\s+", " ", q).strip()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return max(-1.0, min(1.0, dot / na / nb))


def _keywords(normalized: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9\-]+", normalized)
            if t not in STOPWORDS and len(t) > 1]


def hybrid_search(*, company_id: int, query: str,
                  equipment_id: int | None = None,
                  document_id: int | None = None,
                  source_types: list[str] | None = None,
                  top_k: int | None = None,
                  include_historical: bool = False) -> dict:
    """Full pipeline returning citations or INSUFFICIENT_EVIDENCE. Every
    citation is validated against live DB rows before return."""
    s = get_settings()
    top_k = top_k or s.RETRIEVAL_TOP_K
    top_k = max(1, min(top_k, 50))
    normalized = normalize_query(query)
    if not normalized:
        return _insufficient(query, normalized, 0, None, "empty query")
    provider = get_embedding_provider()
    qvec = provider.embed_query(normalized)
    model = provider.model_name
    cand_n = s.RETRIEVAL_CANDIDATES

    sem_rows = store.fetch_candidates(
        company_id, active_only=not include_historical,
        equipment_id=equipment_id, doc_id=document_id, source_types=source_types,
        embedding_model=model, limit=cand_n * 4)
    sem = [(r, _cosine(qvec, r["vector"])) for r in sem_rows]
    sem.sort(key=lambda t: -t[1])
    sem_rank = {r["id"]: i + 1 for i, (r, _) in enumerate(sem)}

    lex_rows = store.lexical_candidates(
        company_id, normalized, active_only=not include_historical,
        equipment_id=equipment_id, doc_id=document_id, source_types=source_types,
        limit=cand_n * 4)

    pooled: dict[str, dict] = {}
    for r, cos in sem:
        # Raw cosine clamped at 0 keeps the relevance scale honest: unrelated
        # content scores near 0 instead of ~0.5, so MIN_RELEVANCE_SCORE bites.
        pooled[r["id"]] = {"row": r, "sem": max(0.0, cos), "lex": 0.0}
    for r, rank in lex_rows:
        lex = 1.0 / (1.0 + abs(rank))
        if r["id"] in pooled:
            pooled[r["id"]]["lex"] = lex
        else:
            # Lexical-only hits still need a vector for dedup; fetch lazily.
            pooled[r["id"]] = {"row": r, "sem": 0.0, "lex": lex}

    alpha = s.RETRIEVAL_ALPHA
    scored = []
    for cid, p in pooled.items():
        combined = alpha * p["sem"] + (1.0 - alpha) * p["lex"]
        scored.append({"row": p["row"], "semantic_score": round(p["sem"], 4),
                       "lexical_score": round(p["lex"], 4),
                       "combined": combined,
                       "initial_rank": sem_rank.get(cid)})
    scored.sort(key=lambda d: -d["combined"])

    # Rerank (local signals): equipment match + exact-phrase bonus.
    keys = _keywords(normalized)
    phrase = " ".join(keys)
    for d in scored:
        boost = 0.0
        signals = []
        if equipment_id is not None and d["row"].get("equipment_id") == equipment_id:
            boost += s.RERANK_EQUIPMENT_BOOST
            signals.append("equipment_match")
        if d["lexical_score"] > 0:
            signals.append("keyword_match")
        if d["semantic_score"] > 0.35:
            signals.append("semantic_similarity")
        text_l = (d["row"]["text"] or "").lower()
        if phrase and len(phrase) >= 4 and phrase in text_l:
            boost += s.RERANK_PHRASE_BOOST
            signals.append("exact_phrase")
        d["combined"] = min(1.0, d["combined"] + boost)
        d["combined_score"] = round(d["combined"], 4)
        d["why"] = signals
    scored.sort(key=lambda d: -d["combined"])

    # Dedup: exact checksum collapse, then near-dup cosine > 0.95.
    seen_sum: dict[str, dict] = {}
    for d in scored:
        key = d["row"]["checksum"]
        if key not in seen_sum or d["combined"] > seen_sum[key]["combined"]:
            seen_sum[key] = d
    deduped = sorted(seen_sum.values(), key=lambda d: -d["combined"])
    final: list[dict] = []
    for d in deduped:
        dup = False
        for kept in final:
            if _cosine(_vec_of(d), _vec_of(kept)) > 0.95:
                dup = True
                break
        if not dup:
            final.append(d)
        if len(final) >= top_k * 3:
            break

    # Provenance validation against live rows; failures are dropped, never cited.
    citations = []
    for d in final[:top_k]:
        cit = _validate_citation(d, include_historical)
        if cit is not None:
            citations.append(cit)
    for i, c in enumerate(citations, start=1):
        c["final_rank"] = i

    best = citations[0]["combined_score"] if citations else (
        round(final[0]["combined"], 4) if final else None)
    if not citations or (best is not None and best < s.MIN_RELEVANCE_SCORE):
        return _insufficient(query, normalized, len(final), best,
                             "below minimum_relevance_score")
    return {"status": "OK", "original_query": query, "normalized_query": normalized,
            "citations": citations, "count": len(citations)}


def _vec_of(d: dict) -> list[float]:
    v = d["row"].get("vector")
    if v is None:
        cid = d["row"]["id"]
        row = store.get_chunk(cid) or {}
        v = []
        if row:
            import struct
            from .store import connect as _connect  # local import: no cycle
            con = _connect()
            try:
                r = con.execute("SELECT vector FROM embeddings WHERE chunk_id = ?",
                                (cid,)).fetchone()
                if r:
                    blob = r["vector"]
                    v = list(struct.unpack(f"<{len(blob)//4}f", blob))
            finally:
                con.close()
    return v or [0.0]


def _validate_citation(d: dict, include_historical: bool) -> dict | None:
    """Verify doc + version + chunk + company + active state live. Returns the
    citation or None (never cite invalid data)."""
    from ..db import connect as app_connect
    row, doc = d["row"], None
    con = app_connect()
    try:
        doc = con.execute("SELECT * FROM documents WHERE id = ?",
                          (row["doc_id"],)).fetchone()
    finally:
        con.close()
    if doc is None:
        return None
    if int(doc["company_id"]) != int(row["company_id"]):
        return None
    live = store.get_chunk(row["id"])
    if live is None or int(live["company_id"]) != int(row["company_id"]):
        return None
    if not include_historical:
        if not live["active"]:
            return None
        if doc["processing_status"] == "FAILED":
            return None
    text = live["text"] or ""
    excerpt = text[:300]
    return {
        "document_id": int(doc["id"]),
        "document_version": int(doc["version"]),
        "chunk_id": row["id"],
        "filename": row["filename"],
        "page": row["page"],
        "section": row["section"],
        "equipment_id": row["equipment_id"],
        "excerpt": excerpt,
        "semantic_score": d["semantic_score"],
        "lexical_score": d["lexical_score"],
        "combined_score": d["combined_score"],
        "initial_rank": d["initial_rank"],
        "retrieval_method": ("hybrid" if d["lexical_score"] > 0
                             and d["semantic_score"] > 0
                             else ("lexical" if d["lexical_score"] > 0
                                   else "semantic")),
        "why_retrieved": d["why"] + (["historical_version"] if include_historical
                                     and not live["active"]
                                     else ["current_version"]),
    }


def _insufficient(query, normalized, candidates, best, reason) -> dict:
    s = get_settings()
    return {"status": "INSUFFICIENT_EVIDENCE", "original_query": query,
            "normalized_query": normalized, "citations": [], "count": 0,
            "candidates": candidates, "best_score": best,
            "minimum_relevance_score": s.MIN_RELEVANCE_SCORE, "reason": reason}


def pack_context(citations: list[dict], *, max_chunks: int | None = None,
                 max_chars: int | None = None) -> dict:
    """Stage-5-ready evidence context. Truncation is recorded, provenance kept."""
    s = get_settings()
    max_chunks = max_chunks or s.MAX_CONTEXT_CHUNKS
    max_chars = max_chars or s.MAX_CONTEXT_CHARS
    blocks, used, truncated = [], 0, False
    for c in citations[:max_chunks]:
        head = (f"[Source: {c['filename']} v{c['document_version']}"
                + (f" p.{c['page']}" if c.get("page") else "")
                + (f" | {c['section']}" if c.get("section") else "") + "]")
        # Excerpt source: re-read full chunk text for faithful context.
        live = store.get_chunk(c["chunk_id"]) or {}
        body = (live.get("text") or c["excerpt"])[:max_chars]
        block = f"{head}\n{body}"
        if used + len(block) > max_chars:
            room = max_chars - used
            if room > 200:
                blocks.append(block[:room] + "\n[TRUNCATED]")
                used = max_chars
            truncated = True
            break
        blocks.append(block)
        used += len(block)
    return {"sources": citations[:max_chunks], "context": "\n\n".join(blocks),
            "chars": used, "truncated": truncated,
            "chunks_used": len(blocks)}


def content_checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
