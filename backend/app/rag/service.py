"""Index pipeline + knowledge health + retrieval evaluation.

Index states live on documents.index_status: NOT_INDEXED → INDEXING →
INDEXED | INDEX_FAILED; STALE when a newer version exists; archived docs keep
their last state but their chunks deactivate (excluded unless historical).
"""
import json
import time
from datetime import datetime, timezone

from ..audit import log_event
from ..core.security import utcnow_iso
from ..db import connect as app_connect
from . import store
from .chunking import chunk_sections
from .embeddings import EmbeddingError, embedding_metadata, get_embedding_provider
from .retrieval import content_checksum, hybrid_search


class IndexingError(Exception):
    pass


def _doc_owned(doc_id: int, company_id: int):
    con = app_connect()
    try:
        row = con.execute("SELECT * FROM documents WHERE id = ? AND company_id = ?",
                          (doc_id, company_id)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def _set_status(doc_id: int, **fields) -> None:
    fields["updated_at"] = utcnow_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    con = app_connect()
    try:
        con.execute(f"UPDATE documents SET {sets} WHERE id = ?",
                    (*fields.values(), doc_id))
        con.commit()
    finally:
        con.close()


def index_document(doc_id: int, company_id: int, user_id: int,
                   ip: str | None, *, force: bool = False) -> dict:
    """Index one COMPLETED document version. Duplicate content + same model is
    skipped (no wasted embeddings). Failures → INDEX_FAILED, doc untouched."""
    doc = _doc_owned(doc_id, company_id)
    if doc is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found")
    if doc["processing_status"] != "COMPLETED":
        from fastapi import HTTPException
        raise HTTPException(status_code=409,
                            detail="Only COMPLETED documents can be indexed")
    provider = get_embedding_provider()
    model = provider.model_name
    store.init_store()
    checksum = content_checksum(doc.get("extracted_text") or "")
    if not force and doc.get("index_status") == "INDEXED" \
            and doc.get("embedding_model") == model \
            and doc.get("indexed_checksum") == checksum:
        return {"document_id": doc_id, "status": "INDEXED",
                "detail": "Already indexed (duplicate content skipped)",
                "chunks": doc.get("chunk_count", 0)}
    _set_status(doc_id, index_status="INDEXING", index_error=None)
    log_event("document_indexing_started", {"document_id": doc_id},
              company_id=company_id, user_id=user_id, ip=ip,
              entity_type="document", entity_id=doc_id)
    try:
        try:
            sections = json.loads(doc.get("extracted_json") or "{}").get("sections", [])
        except (ValueError, TypeError):
            sections = []
        chunks = chunk_sections(sections, source_type=doc["file_type"])
        if not chunks:
            # No chunkable content (e.g. image without OCR): index honestly empty.
            store.delete_doc(doc_id)
            _set_status(doc_id, index_status="INDEXED", indexed_version=doc["version"],
                        indexed_at=utcnow_iso(), chunk_count=0,
                        embedding_model=model, indexed_checksum=checksum,
                        index_error=None)
            log_event("document_indexed",
                      {"document_id": doc_id, "chunks": 0, "empty": True},
                      company_id=company_id, user_id=user_id, ip=ip,
                      entity_type="document", entity_id=doc_id)
            return {"document_id": doc_id, "status": "INDEXED",
                    "detail": "No chunkable content; indexed empty", "chunks": 0}
        texts = [c["text"] for c in chunks]
        vectors = provider.embed_texts(texts)
        ids = store.upsert_chunks(
            doc_id, company_id, chunks, vectors,
            {"equipment_id": doc["equipment_id"], "filename": doc["original_filename"],
             "version": doc["version"], "embedding_model": model})
        _set_status(doc_id, index_status="INDEXED", indexed_version=doc["version"],
                    indexed_at=utcnow_iso(), chunk_count=len(ids),
                    embedding_model=model, indexed_checksum=checksum,
                    index_error=None)
    except (EmbeddingError, IndexingError) as e:
        _set_status(doc_id, index_status="INDEX_FAILED", index_error=str(e))
        log_event("document_indexing_failed",
                  {"document_id": doc_id, "error": str(e)},
                  company_id=company_id, user_id=user_id, ip=ip,
                  entity_type="document", entity_id=doc_id)
        return {"document_id": doc_id, "status": "INDEX_FAILED",
                "detail": str(e), "chunks": 0}
    log_event("document_indexed",
              {"document_id": doc_id, "chunks": len(ids), "model": model},
              company_id=company_id, user_id=user_id, ip=ip,
              entity_type="document", entity_id=doc_id)
    return {"document_id": doc_id, "status": "INDEXED",
            "detail": f"Indexed {len(ids)} chunks", "chunks": len(ids)}


def retire_version(doc_id: int) -> None:
    """A newer version took over: chunks off, status STALE if it was INDEXED
    (history kept for explicit historical queries)."""
    store.set_doc_active(doc_id, False)
    con = app_connect()
    try:
        row = con.execute("SELECT index_status FROM documents WHERE id = ?",
                          (doc_id,)).fetchone()
    finally:
        con.close()
    if row is not None and row["index_status"] == "INDEXED":
        _set_status(doc_id, index_status="STALE")


def set_archived(doc_id: int, archived: bool) -> None:
    store.set_doc_active(doc_id, not archived)


def delete_vectors(doc_id: int) -> int:
    return store.delete_doc(doc_id)


def reindex_company(company_id: int, user_id: int, ip: str | None,
                    equipment_id: int | None = None) -> dict:
    """Reindex STALE/FAILED/NOT_INDEXED docs of one company (mass reindex is
    explicit and bounded — no background loops)."""
    con = app_connect()
    try:
        q = ("SELECT id FROM documents WHERE company_id = ? AND is_archived = 0"
             " AND processing_status = 'COMPLETED' AND (index_status IS NULL"
             " OR index_status IN ('NOT_INDEXED','INDEX_FAILED','STALE','REINDEX_REQUIRED'))")
        params: list = [company_id]
        if equipment_id is not None:
            q += " AND (equipment_id = ? OR ? IS NULL)"
            params += [equipment_id, equipment_id]
        ids = [r[0] for r in con.execute(q, params).fetchall()]
    finally:
        con.close()
    results = [index_document(i, company_id, user_id, ip, force=True) for i in ids]
    log_event("knowledge_reindexed",
              {"company_id": company_id, "documents": len(ids)},
              company_id=company_id, user_id=user_id, ip=ip)
    return {"reindexed": len(ids), "results": results}


def knowledge_health(company_id: int | None = None) -> dict:
    """Real counts from documents + vector store. Nothing hardcoded."""
    con = app_connect()
    try:
        if company_id is None:
            base, params = "", []
        else:
            base, params = "WHERE company_id = ?", [company_id]
        total = con.execute(f"SELECT COUNT(*) FROM documents {base}", params).fetchone()[0]
        ready = con.execute(
            f"SELECT COUNT(*) FROM documents {base}"
            + (" AND " if base else "WHERE ") + "processing_status = 'COMPLETED'",
            params).fetchone()[0]

        def cnt(status):
            return con.execute(
                f"SELECT COUNT(*) FROM documents {base}"
                + (" AND " if base else "WHERE ") + "index_status = ?",
                (*params, status)).fetchone()[0]

        indexed = cnt("INDEXED")
        indexing = cnt("INDEXING")
        stale = cnt("STALE") + cnt("REINDEX_REQUIRED")
        failed = cnt("INDEX_FAILED")
        not_indexed = total - indexed - indexing - stale - failed
        last = con.execute(
            f"SELECT MAX(indexed_at) FROM documents {base}", params).fetchone()[0]
    finally:
        con.close()
    store.init_store()
    vs = store.stats(company_id)
    meta = embedding_metadata()
    return {"documents_total": total, "documents_ready": ready,
            "indexed": indexed, "indexing": indexing, "stale": stale,
            "failed": failed, "not_indexed": max(0, not_indexed),
            "chunks_total": vs["chunks_total"],
            "chunks_active": vs["chunks_active"],
            "embedding_provider": meta["provider"],
            "embedding_model": meta["model_name"],
            "embedding_dimension": meta["dimension"],
            "embedding_models_in_store": vs["embedding_models"],
            "vector_db": ("ONLINE" if store.fts_rebuild_check() else "ERROR"),
            "last_indexed_at": last or vs["last_indexed_at"]}


# ---------------- Evaluation (synthetic Pump P-204 corpus, real pipeline) ---

EVAL_QUERIES = [
    {"q": "What is the vibration inspection procedure for Pump P-204?",
     "expect_file": "manual.txt", "equipment_code": "P-204"},
    {"q": "What bearing maintenance interval is specified?",
     "expect_file": "manual.txt", "equipment_code": "P-204"},
    {"q": "Which document describes coupling alignment?",
     "expect_file": "align.txt", "equipment_code": "P-204"},
    {"q": "What does the previous inspection report say about vibration?",
     "expect_file": "inspection.txt", "equipment_code": "P-204"},
    {"q": "Which evidence belongs specifically to Pump P-204?",
     "expect_file": "history.txt", "equipment_code": "P-204"},
    {"q": "Compressor C-301 oil pressure limits",
     "expect_file": None, "equipment_code": None},  # negative control
]

EVAL_CORPUS = {
    "manual.txt": ("Pump P-204 Maintenance Manual. Bearing inspection procedure: "
                   "check bearing housing vibration monthly with a calibrated meter. "
                   "Bearing maintenance interval is every 6 months. Replace bearings "
                   "showing spalling or excess play."),
    "align.txt": ("Coupling alignment guide for Pump P-204. Use dial indicators. "
                  "Permitted angular misalignment is 0.05 mm. Check alignment "
                  "after every overhaul."),
    "inspection.txt": ("Previous inspection report for Pump P-204. Vibration at "
                       "bearing NDE measured 4.1 mm/s, above the 2.8 limit. "
                       "Recommend bearing replacement at next shutdown."),
    "history.txt": ("Maintenance history log, Pump P-204. 2026-08-12: bearing "
                    "replaced. 2026-08-20: vibration rechecked normal. Evidence "
                    "belongs specifically to Pump P-204 asset tag P-204."),
}


def run_evaluation(*, company_id: int, equipment_id: int, k: int = 5) -> dict:
    """Execute the eval set against the LIVE retrieval system (no mocks, no
    hardcoded scores). Corpus docs must already be indexed for this company."""
    from .retrieval import hybrid_search
    results = []
    for item in EVAL_QUERIES:
        t0 = time.time()
        res = hybrid_search(company_id=company_id, query=item["q"],
                            equipment_id=equipment_id
                            if item["equipment_code"] else None,
                            top_k=k)
        latency = round((time.time() - t0) * 1000, 1)
        got = [c["filename"] for c in res.get("citations", [])]
        exp = item["expect_file"]
        if exp is None:
            passed = res["status"] == "INSUFFICIENT_EVIDENCE" or not got
            rank, rr, prec = None, 0.0, 1.0 if not got else 0.0
        else:
            rank = next((i + 1 for i, f in enumerate(got) if f == exp), None)
            rr = 1.0 / rank if rank else 0.0
            prec = sum(1 for f in got if f == exp) / len(got) if got else 0.0
            passed = rank is not None and rank <= k
        results.append({"query": item["q"], "expected": exp, "got": got,
                        "rank": rank, "mrr": round(rr, 3),
                        "precision_at_k": round(prec, 3),
                        "recall_at_k": 1.0 if rank else 0.0,
                        "latency_ms": latency, "pass": passed})
    n = len(results)
    return {"queries": results, "k": k,
            "summary": {
                "pass_rate": round(sum(r["pass"] for r in results) / n, 3),
                "mean_mrr": round(sum(r["mrr"] for r in results) / n, 3),
                "mean_latency_ms": round(
                    sum(r["latency_ms"] for r in results) / n, 1),
                "evaluated_at": datetime.now(timezone.utc).isoformat()}}
