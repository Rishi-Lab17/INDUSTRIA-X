"""RAGAgent: retrieve private sources, select evidence, pack bounded context.

Uses Stage 4 RAG only — no second vector database. Preserves citations and
returns retrieval metadata the orchestrator records on the run.
"""
from ..rag.retrieval import hybrid_search, pack_context


def retrieve(*, company_id: int, query: str, equipment_id: int | None,
             top_k: int = 6) -> dict:
    """Returns {status, citations, context, context_chars, context_truncated,
    chunks_used, normalized_query, candidates, best_score, ...}."""
    res = hybrid_search(company_id=company_id, query=query,
                        equipment_id=equipment_id, top_k=top_k)
    if res["status"] != "OK":
        return res
    packed = pack_context(res["citations"])
    res["context"] = packed["context"]
    res["context_chars"] = packed["chars"]
    res["context_truncated"] = packed["truncated"]
    res["chunks_used"] = packed["chunks_used"]
    return res
