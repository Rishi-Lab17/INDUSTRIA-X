"""Knowledge (RAG) API: explicit indexing controls, hybrid search with
provenance, health, and evaluation. Search is open to all authenticated
roles; indexing controls are ADMIN+ENGINEER; eval is ADMIN+ENGINEER.
Raw vectors are never returned. Company scope always enforced."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from ..audit import log_event
from ..core.deps import get_current_session, require_roles
from ..db import connect as app_connect
from ..rag import service as rag_service
from ..rag.retrieval import hybrid_search, pack_context

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _equipment_owned(equipment_id: int | None, company_id: int) -> None:
    if equipment_id is None:
        return
    con = app_connect()
    try:
        ok = con.execute("SELECT 1 FROM equipment WHERE id = ? AND company_id = ?",
                         (equipment_id, company_id)).fetchone()
    finally:
        con.close()
    if ok is None:
        raise HTTPException(status_code=404, detail="Equipment not found")


class SearchIn(BaseModel):
    query: str
    equipment_id: int | None = None
    document_id: int | None = None
    source_types: list[str] | None = None
    top_k: int | None = None
    include_historical: bool = False

    @field_validator("query")
    @classmethod
    def _q(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must not be empty")
        return v.strip()[:2000]


class ReindexIn(BaseModel):
    equipment_id: int | None = None


@router.post("/documents/{document_id}/index",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def index_document(document_id: int, request: Request,
                   sess: dict = Depends(get_current_session)):
    return rag_service.index_document(document_id, sess["company_id"],
                                      sess["user_id"], _client_ip(request))


@router.get("/documents/{document_id}/index-status")
def index_status(document_id: int, sess: dict = Depends(get_current_session)):
    con = app_connect()
    try:
        row = con.execute(
            "SELECT id, index_status, indexed_version, indexed_at, index_error,"
            " chunk_count, embedding_model, version, processing_status"
            " FROM documents WHERE id = ? AND company_id = ?",
            (document_id, sess["company_id"])).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(row)


@router.post("/documents/{document_id}/reindex",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def reindex_document(document_id: int, request: Request,
                     sess: dict = Depends(get_current_session)):
    return rag_service.index_document(document_id, sess["company_id"],
                                      sess["user_id"], _client_ip(request),
                                      force=True)


@router.post("/reindex",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def reindex_company(body: ReindexIn, request: Request,
                    sess: dict = Depends(get_current_session)):
    _equipment_owned(body.equipment_id, sess["company_id"])
    return rag_service.reindex_company(sess["company_id"], sess["user_id"],
                                       _client_ip(request), body.equipment_id)


@router.get("/health")
def knowledge_health(sess: dict = Depends(get_current_session)):
    return rag_service.knowledge_health(sess["company_id"])


@router.post("/search")
def search(body: SearchIn, request: Request,
           sess: dict = Depends(get_current_session)):
    if body.document_id is not None:
        con = app_connect()
        try:
            ok = con.execute("SELECT 1 FROM documents WHERE id = ? AND company_id = ?",
                             (body.document_id, sess["company_id"])).fetchone()
        finally:
            con.close()
        if ok is None:
            raise HTTPException(status_code=404, detail="Document not found")
    _equipment_owned(body.equipment_id, sess["company_id"])
    res = hybrid_search(company_id=sess["company_id"], query=body.query,
                        equipment_id=body.equipment_id, document_id=body.document_id,
                        source_types=body.source_types, top_k=body.top_k,
                        include_historical=body.include_historical)
    if res["status"] == "OK":
        packed = pack_context(res["citations"])
        res["context"] = packed["context"]
        res["context_chars"] = packed["chars"]
        res["context_truncated"] = packed["truncated"]
        res["chunks_used"] = packed["chunks_used"]
    mode = ("equipment" if body.equipment_id is not None
            else ("document" if body.document_id is not None else "general"))
    if body.include_historical:
        mode += "+historical"
    log_event("knowledge_searched",
              {"query": body.query[:200], "mode": mode,
               "equipment_id": body.equipment_id,
               "document_id": body.document_id,
               "results": res.get("count", 0), "status": res["status"]},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request))
    res["mode"] = mode
    return res


@router.get("/eval",
            dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def run_eval(sess: dict = Depends(get_current_session)):
    """Run the synthetic evaluation set against live retrieval. The corpus
    docs must exist+be indexed (see tests/seed helper); otherwise queries
    honestly report INSUFFICIENT_EVIDENCE and fail."""
    equipment_id = _eval_equipment(sess["company_id"])
    if equipment_id is None:
        raise HTTPException(status_code=409, detail=(
            "Evaluation corpus not indexed for this company. Index the Pump P-204"
            " eval documents first (see docs/stage4.md)."))
    return rag_service.run_evaluation(company_id=sess["company_id"],
                                      equipment_id=equipment_id)


def _eval_equipment(company_id: int) -> int | None:
    from ..rag.service import EVAL_CORPUS  # noqa: F401 (kept for clarity)
    con = app_connect()
    try:
        # Any equipment of this company carrying eval docs; the eval test
        # creates equipment code EVAL-P204.
        row = con.execute(
            "SELECT id FROM equipment WHERE company_id = ? AND code = 'EVAL-P204'",
            (company_id,)).fetchone()
        return int(row[0]) if row else None
    finally:
        con.close()
