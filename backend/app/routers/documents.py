"""Knowledge Base: secure local document upload, processing, retrieval.

Tenant rule: every query scoped to session company_id; foreign ids → 404.
RBAC: upload/list/detail/preview/download = all roles; retry = ADMIN+ENGINEER;
archive/delete = ADMIN only. Files: generated storage keys only, hashed,
never executed. No external calls anywhere in this module.
"""
import hashlib
import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ..audit import log_event
from ..core.config import ROOT, get_settings
from ..core.deps import get_current_session, require_roles
from ..core.security import utcnow_iso
from ..db import connect
from ..processing.base import ProcessingFailed
from ..processing.registry import SUPPORTED_TYPES, get_processor
from ..processing.validate import TYPE_TO_MIME, ValidationError, validate_upload
from ..rag import service as rag_service

router = APIRouter(prefix="/api/documents", tags=["documents"])

CHUNK = 1024 * 1024
STATUSES = ("UPLOADED", "QUEUED", "PROCESSING", "COMPLETED",
            "FAILED", "RETRYING", "ARCHIVED")
IMAGE_TYPES = ("JPG", "JPEG", "PNG")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _storage_root(file_type: str) -> Path:
    s = get_settings()
    base = s.STORAGE_IMAGES if file_type in IMAGE_TYPES else s.STORAGE_DOCUMENTS
    p = Path(base)
    return p if p.is_absolute() else ROOT / p


def _safe_join(root: Path, *parts: str) -> Path:
    """Resolve strictly inside root; raises on any escape attempt."""
    target = (root.joinpath(*parts)).resolve()
    if target != root.resolve() and root.resolve() not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid storage path")
    return target


def _meta_row(row, equipment_code=None, uploader_name=None) -> dict:
    return {
        "id": row["id"], "company_id": row["company_id"],
        "equipment_id": row["equipment_id"], "equipment_code": equipment_code,
        "uploaded_by": row["uploaded_by"], "uploader_name": uploader_name,
        "original_filename": row["original_filename"],
        "file_type": row["file_type"], "mime_type": row["mime_type"],
        "file_size": row["file_size"], "sha256_hash": row["sha256_hash"],
        "version": row["version"], "parent_document_id": row["parent_document_id"],
        "processing_status": row["processing_status"],
        "processing_started_at": row["processing_started_at"],
        "processing_completed_at": row["processing_completed_at"],
        "processing_error": row["processing_error"],
        "processing_note": row["processing_note"],
        "page_count": row["page_count"], "ocr_used": bool(row["ocr_used"]),
        "is_archived": bool(row["is_archived"]),
        "index_status": row["index_status"] if "index_status" in row.keys() else "NOT_INDEXED",
        "indexed_version": row["indexed_version"] if "indexed_version" in row.keys() else None,
        "indexed_at": row["indexed_at"] if "indexed_at" in row.keys() else None,
        "index_error": row["index_error"] if "index_error" in row.keys() else None,
        "chunk_count": row["chunk_count"] if "chunk_count" in row.keys() else 0,
        "embedding_model": row["embedding_model"] if "embedding_model" in row.keys() else None,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "text_preview": (row["extracted_text"] or "")[:300],
    }


def _enrich(con, row) -> dict:
    eq_code, up_name = None, None
    if row["equipment_id"]:
        eq = con.execute("SELECT code FROM equipment WHERE id = ?",
                         (row["equipment_id"],)).fetchone()
        eq_code = eq["code"] if eq else None
    if row["uploaded_by"]:
        u = con.execute("SELECT name FROM users WHERE id = ?",
                        (row["uploaded_by"],)).fetchone()
        up_name = u["name"] if u else None
    return _meta_row(row, eq_code, up_name)


def _get_owned(con, doc_id: int, company_id: int):
    row = con.execute("SELECT * FROM documents WHERE id = ? AND company_id = ?",
                      (doc_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


def _check_equipment(con, equipment_id: int | None, company_id: int):
    if equipment_id is None:
        return
    eq = con.execute("SELECT id FROM equipment WHERE id = ? AND company_id = ?"
                     " AND is_active = 1", (equipment_id, company_id)).fetchone()
    if eq is None:
        raise HTTPException(status_code=404, detail="Equipment not found")


def _run_processing(con, doc_id: int, company_id: int, sess_user: int,
                    ip: str | None, *, is_retry: bool) -> dict:
    """Synchronous local pipeline with persisted state transitions."""
    row = _get_owned(con, doc_id, company_id)
    start_status = "RETRYING" if is_retry else "QUEUED"
    con.execute("UPDATE documents SET processing_status = ?, processing_error = NULL,"
                " processing_started_at = ?, updated_at = ? WHERE id = ?",
                (start_status, utcnow_iso(), utcnow_iso(), doc_id))
    con.commit()
    log_event("document_processing_started" if not is_retry
              else "document_processing_retried",
              {"document_id": doc_id}, company_id=company_id, user_id=sess_user,
              ip=ip, entity_type="document", entity_id=doc_id)
    con.execute("UPDATE documents SET processing_status = 'PROCESSING',"
                " updated_at = ? WHERE id = ?", (utcnow_iso(), doc_id))
    con.commit()
    row = con.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    root = _storage_root(row["file_type"])
    fpath = _safe_join(root, row["storage_key"])
    if not fpath.is_file():
        con.execute("UPDATE documents SET processing_status = 'FAILED',"
                    " processing_error = 'Stored file missing',"
                    " processing_completed_at = ?, updated_at = ? WHERE id = ?",
                    (utcnow_iso(), utcnow_iso(), doc_id))
        con.commit()
        log_event("document_processing_failed", {"document_id": doc_id},
                  company_id=company_id, user_id=sess_user, ip=ip,
                  entity_type="document", entity_id=doc_id)
        return _enrich(con, con.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone())
    processor = get_processor(row["file_type"])
    try:
        assert processor is not None
        res = processor.process(fpath, original_filename=row["original_filename"])
        try:
            sections_json = json.dumps({"source_document_id": doc_id,
                                        "sections": res["sections"]})
        except (ValueError, TypeError):
            sections_json = "{}"
        con.execute(
            "UPDATE documents SET processing_status = 'COMPLETED',"
            " extracted_text = ?, extracted_json = ?, page_count = ?,"
            " ocr_used = ?, processing_note = ?, processing_completed_at = ?,"
            " updated_at = ? WHERE id = ?",
            (res["extracted_text"], sections_json, res["page_count"],
             1 if res["ocr_used"] else 0, res["note"], utcnow_iso(),
             utcnow_iso(), doc_id))
        con.commit()
        log_event("document_processing_completed",
                  {"document_id": doc_id, "ocr_used": bool(res["ocr_used"])},
                  company_id=company_id, user_id=sess_user, ip=ip,
                  entity_type="document", entity_id=doc_id)
    except ProcessingFailed as e:
        con.execute("UPDATE documents SET processing_status = 'FAILED',"
                    " processing_error = ?, processing_completed_at = ?,"
                    " updated_at = ? WHERE id = ?",
                    (str(e), utcnow_iso(), utcnow_iso(), doc_id))
        con.commit()
        log_event("document_processing_failed", {"document_id": doc_id},
                  company_id=company_id, user_id=sess_user, ip=ip,
                  entity_type="document", entity_id=doc_id)
    except Exception:
        # Never leak internals: generic message, details stay server-side.
        con.execute("UPDATE documents SET processing_status = 'FAILED',"
                    " processing_error = 'Unexpected error during processing',"
                    " processing_completed_at = ?, updated_at = ? WHERE id = ?",
                    (utcnow_iso(), utcnow_iso(), doc_id))
        con.commit()
        log_event("document_processing_failed", {"document_id": doc_id},
                  company_id=company_id, user_id=sess_user, ip=ip,
                  entity_type="document", entity_id=doc_id)
    return _enrich(con, con.execute(
        "SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone())


@router.post("", status_code=201)
async def upload_document(request: Request,
                          file: UploadFile = File(...),
                          equipment_id: int | None = Form(None),
                          sess: dict = Depends(get_current_session)):
    s = get_settings()
    max_bytes = s.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    # Stream to temp while hashing: bounded memory, exact size enforcement.
    tmp_name = f"upload_{uuid.uuid4().hex}.tmp"
    tmp_dir = ROOT / Path(s.STORAGE_TEMP)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / tmp_name
    hasher, size, head = hashlib.sha256(), 0, b""
    try:
        with open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (limit {s.MAX_UPLOAD_SIZE_MB} MB)")
                if len(head) < 65536:
                    head += chunk[:65536 - len(head)]
                hasher.update(chunk)
                out.write(chunk)
    except HTTPException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="Unable to read upload")
    digest = hasher.hexdigest()
    if size == 0:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=422, detail="File is empty")
    try:
        file_type, mime = validate_upload(file.filename or "", file.content_type, head)
    except ValidationError as e:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=422, detail=str(e))
    con = connect()
    try:
        _check_equipment(con, equipment_id, sess["company_id"])
        # Deterministic versioning: same company + filename (case-insensitive)
        # + same equipment link. Identical bytes → return existing version.
        lname = (file.filename or "").strip().lower()
        if equipment_id is None:
            latest = con.execute(
                "SELECT * FROM documents WHERE company_id = ? AND lower(original_filename) = ?"
                " AND equipment_id IS NULL ORDER BY version DESC LIMIT 1",
                (sess["company_id"], lname)).fetchone()
        else:
            latest = con.execute(
                "SELECT * FROM documents WHERE company_id = ? AND lower(original_filename) = ?"
                " AND equipment_id = ? ORDER BY version DESC LIMIT 1",
                (sess["company_id"], lname, equipment_id)).fetchone()
        if latest is not None and latest["sha256_hash"] == digest:
            return JSONResponse(status_code=200,
                                content={**_enrich(con, latest), "duplicate": True})
        version = (latest["version"] + 1) if latest else 1
        parent_id = latest["id"] if latest else None
        ext = {".pdf": "PDF", ".docx": "DOCX", ".txt": "TXT", ".csv": "CSV",
               ".xlsx": "XLSX", ".jpg": "JPG", ".jpeg": "JPEG",
               ".png": "PNG"}
        ext = next(k for k, v in ext.items() if v == file_type)
        cur = con.execute(
            "INSERT INTO documents (company_id, equipment_id, uploaded_by, original_filename,"
            " storage_key, file_type, mime_type, file_size, sha256_hash, version,"
            " parent_document_id, processing_status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, 'UPLOADED', ?, ?)",
            (sess["company_id"], equipment_id, sess["user_id"],
             (file.filename or "").strip(), file_type, mime, size, digest,
             version, parent_id, utcnow_iso(), utcnow_iso()))
        doc_id = cur.lastrowid
        key = f"{sess['company_id']}/{doc_id}/original{ext}"
        con.execute("UPDATE documents SET storage_key = ? WHERE id = ?",
                    (key, doc_id))
        con.commit()
        root = _storage_root(file_type)
        dest_dir = _safe_join(root, str(sess["company_id"]), str(doc_id))
        dest_dir.mkdir(parents=True, exist_ok=True)
        (_safe_join(root, "processed")).mkdir(parents=True, exist_ok=True)
        dest = _safe_join(root, key)
        os.replace(tmp_path, dest)
    except HTTPException:
        raise
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Upload failed")
    log_event("document_uploaded",
              {"document_id": doc_id, "version": version,
               "file_type": file_type, "equipment_id": equipment_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="document", entity_id=doc_id)
    if parent_id is not None:
        log_event("document_version_created",
                  {"document_id": doc_id, "version": version,
                   "parent": parent_id},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="document", entity_id=doc_id)
        # Previous version retires: its chunks go inactive (STALE), history kept.
        rag_service.retire_version(parent_id)
    if equipment_id is not None:
        log_event("document_equipment_associated",
                  {"document_id": doc_id, "equipment_id": equipment_id},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="document", entity_id=doc_id)
    try:
        out = _run_processing(con, doc_id, sess["company_id"], sess["user_id"],
                              _client_ip(request), is_retry=False)
    finally:
        con.close()
    out["duplicate"] = False
    return out


@router.get("")
def list_documents(sess: dict = Depends(get_current_session),
                   equipment_id: int | None = None,
                   file_type: str | None = None,
                   processing_status: str | None = None,
                   is_archived: bool = False,
                   search: str | None = None,
                   page: int = 1, page_size: int = 20):
    if file_type is not None and file_type not in SUPPORTED_TYPES:
        raise HTTPException(status_code=422,
                            detail=f"file_type must be one of {SUPPORTED_TYPES}")
    if processing_status is not None and processing_status not in STATUSES:
        raise HTTPException(status_code=422,
                            detail=f"processing_status must be one of {STATUSES}")
    page, page_size = max(1, page), max(1, min(page_size, 100))
    query = "SELECT * FROM documents WHERE company_id = ? AND is_archived = ?"
    params: list = [sess["company_id"], 1 if is_archived else 0]
    if equipment_id is not None:
        query += " AND equipment_id = ?"
        params.append(equipment_id)
    if file_type:
        query += " AND file_type = ?"
        params.append(file_type)
    if processing_status:
        query += " AND processing_status = ?"
        params.append(processing_status)
    if search and search.strip():
        # Parameterized LIKE: no SQL injection via filter text.
        query += " AND original_filename LIKE ?"
        params.append(f"%{search.strip()}%")
    con = connect()
    try:
        total = con.execute(
            f"SELECT COUNT(*) FROM ({query})", params).fetchone()[0]
        rows = con.execute(query + " ORDER BY id DESC LIMIT ? OFFSET ?",
                           (*params, page_size, (page - 1) * page_size)).fetchall()
        items = [_enrich(con, r) for r in rows]
    finally:
        con.close()
    return {"documents": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{document_id}")
def get_document(document_id: int, request: Request,
                 sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _get_owned(con, document_id, sess["company_id"])
        out = _enrich(con, row)
    finally:
        con.close()
    log_event("document_viewed", {"document_id": document_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="document", entity_id=document_id)
    return out


@router.get("/{document_id}/preview")
def preview_document(document_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _get_owned(con, document_id, sess["company_id"])
        try:
            sections = json.loads(row["extracted_json"]).get("sections", [])
        except (ValueError, TypeError):
            sections = []
    finally:
        con.close()
    return {"id": row["id"], "processing_status": row["processing_status"],
            "ocr_used": bool(row["ocr_used"]), "page_count": row["page_count"],
            "extracted_text": row["extracted_text"] or "",
            "sections": sections if isinstance(sections, list) else []}


@router.get("/{document_id}/download")
def download_document(document_id: int, request: Request,
                      sess: dict = Depends(get_current_session)):
    # All authenticated roles may download own-company files (spec RBAC).
    con = connect()
    try:
        row = _get_owned(con, document_id, sess["company_id"])
        root = _storage_root(row["file_type"])
        fpath = _safe_join(root, row["storage_key"])
        if not fpath.is_file():
            raise HTTPException(status_code=404, detail="Stored file missing")
        size = fpath.stat().st_size
        safe_name = f"document-{document_id}{Path(row['storage_key']).suffix}"
        mime = row["mime_type"]
    finally:
        con.close()
    log_event("document_downloaded", {"document_id": document_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="document", entity_id=document_id)

    def _stream():
        with open(fpath, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(_stream(), media_type=mime,
                             headers={"Content-Disposition":
                                      f'attachment; filename="{safe_name}"',
                                      "Content-Length": str(size)})


@router.post("/{document_id}/retry",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def retry_processing(document_id: int, request: Request,
                     sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _get_owned(con, document_id, sess["company_id"])
        if row["processing_status"] != "FAILED":
            raise HTTPException(status_code=409,
                                detail="Only FAILED documents can be retried")
        out = _run_processing(con, document_id, sess["company_id"],
                              sess["user_id"], _client_ip(request), is_retry=True)
    finally:
        con.close()
    return out


@router.post("/{document_id}/archive",
             dependencies=[Depends(require_roles("COMPANY_ADMIN"))])
def archive_document(document_id: int, request: Request,
                     sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _get_owned(con, document_id, sess["company_id"])
        con.execute("UPDATE documents SET is_archived = 1,"
                    " processing_status = 'ARCHIVED', updated_at = ? WHERE id = ?",
                    (utcnow_iso(), document_id))
        con.commit()
        rag_service.set_archived(document_id, True)
    finally:
        con.close()
    log_event("document_archived", {"document_id": document_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="document", entity_id=document_id)
    return {"message": "Document archived."}


@router.delete("/{document_id}",
               dependencies=[Depends(require_roles("COMPANY_ADMIN"))])
def delete_document(document_id: int, request: Request,
                    sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _get_owned(con, document_id, sess["company_id"])
        root = _storage_root(row["file_type"])
        fpath = _safe_join(root, row["storage_key"])
        try:
            if fpath.is_file():
                fpath.unlink()
        except OSError:
            pass
        con.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        con.commit()
        rag_service.delete_vectors(document_id)
    finally:
        con.close()
    # The audit event itself is retained: deletion is never silent.
    log_event("document_deleted", {"document_id": document_id,
                                   "filename": row["original_filename"]},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="document", entity_id=document_id)
    return {"message": "Document permanently deleted."}
