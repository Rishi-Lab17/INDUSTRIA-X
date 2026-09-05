"""Vision intelligence API: image ingestion, quality, OCR, analysis,
annotations with evidence regions.

Tenant rule: assets/annotations scoped by (id, company_id); foreign → 404.
RBAC: upload + annotate = all roles (technician evidence); analyze/OCR =
ADMIN+ENGINEER; annotation edit/delete = owner or ADMIN; view = all roles.
All vision is local (PIL + optional tesseract); unavailable engines degrade
honestly, never faked.
"""
import hashlib
import io
import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel, field_validator

from ..agents.analysis_agents import VisionAgent
from ..audit import log_event
from ..core.config import ROOT, get_settings
from ..core.deps import get_current_session, require_roles
from ..core.rate_limit import allow
from ..core.security import utcnow_iso
from ..db import connect
from ..multimodal.vision_ingest import VisionError, open_image, validate_image
from ..processing.ocr import OCRError, get_ocr_provider, ocr_available

router = APIRouter(prefix="/api/vision", tags=["vision"])
_VISION = VisionAgent()
_CHUNK = 1024 * 1024
_LABELS = ("corrosion", "crack", "leakage", "damaged insulation",
           "discoloration", "unusual component condition", "other")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _root() -> Path:
    p = Path(get_settings().STORAGE_IMAGES)
    return p if p.is_absolute() else ROOT / p


def _safe_join(root: Path, *parts: str) -> Path:
    target = (root.joinpath(*parts)).resolve()
    if target != root.resolve() and root.resolve() not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid storage path")
    return target


def _owned(con, asset_id: int, company_id: int):
    row = con.execute("SELECT * FROM vision_assets WHERE id = ? AND company_id = ?",
                      (asset_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return row


def _check_equipment(con, equipment_id: int, company_id: int):
    eq = con.execute("SELECT id FROM equipment WHERE id = ? AND company_id = ?"
                     " AND is_active = 1", (equipment_id, company_id)).fetchone()
    if eq is None:
        raise HTTPException(status_code=404, detail="Equipment not found")


def _meta(row, equipment_code=None) -> dict:
    try:
        qd = json.loads(row["quality_detail"])
    except (ValueError, TypeError):
        qd = {}
    return {
        "id": row["id"], "equipment_id": row["equipment_id"],
        "equipment_code": equipment_code, "filename": row["filename"],
        "mime_type": row["mime_type"], "file_size": row["file_size"],
        "width": row["width"], "height": row["height"],
        "sha256_hash": row["sha256_hash"],
        "quality_status": row["quality_status"], "quality_detail": qd,
        "ocr_status": row["ocr_status"],
        "ocr_text": row["ocr_text"] or "",
        "created_at": row["created_at"],
    }


def _limited(sess: dict) -> None:
    ok, retry = allow(f"vision:{sess['user_id']}", 60, 60)
    if not ok:
        raise HTTPException(status_code=429, detail="Analysis rate limit reached.",
                            headers={"Retry-After": str(retry)})


@router.post("/images", status_code=201)
async def upload_image(request: Request, file: UploadFile = File(...),
                       equipment_id: int = Form(...),
                       sess: dict = Depends(get_current_session)):
    s = get_settings()
    fname = (file.filename or "").strip()
    max_bytes = s.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    data = bytearray()
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        data += chunk
        if len(data) > max_bytes:
            raise HTTPException(status_code=413,
                                detail=f"File too large (limit {s.MAX_UPLOAD_SIZE_MB} MB)")
    raw = bytes(data)
    try:
        fmt, mime = validate_image(fname, file.content_type, raw)
    except VisionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    digest = hashlib.sha256(raw).hexdigest()
    img = open_image(raw)
    s2 = get_settings()
    scale = min(1.0, s2.IMAGE_MAX_DIMENSION / max(img.size))
    stored = img
    if scale < 1.0:
        stored = img.resize((int(img.width * scale), int(img.height * scale)))
    buf = io.BytesIO()
    stored.save(buf, format="PNG")
    stored_bytes, w, h = buf.getvalue(), stored.width, stored.height
    con = connect()
    try:
        _check_equipment(con, equipment_id, sess["company_id"])
        cur = con.execute(
            "INSERT INTO vision_assets (company_id, equipment_id, uploaded_by, filename,"
            " storage_key, mime_type, file_size, width, height, sha256_hash,"
            " quality_status, quality_detail, ocr_status, ocr_text, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sess["company_id"], equipment_id, sess["user_id"], fname, "",
             mime, len(stored_bytes), w, h, digest,
             "POOR", "{}", "NOT_ATTEMPTED", "", utcnow_iso()))
        asset_id = cur.lastrowid
        key = f"{sess['company_id']}/{asset_id}/original.png"
        con.execute("UPDATE vision_assets SET storage_key = ? WHERE id = ?",
                    (key, asset_id))
        con.commit()
        root = _root()
        dest_dir = _safe_join(root, str(sess["company_id"]), str(asset_id))
        dest_dir.mkdir(parents=True, exist_ok=True)
        (_safe_join(root, "processed")).mkdir(parents=True, exist_ok=True)
        _safe_join(root, key).write_bytes(stored_bytes)
        eq = con.execute("SELECT code FROM equipment WHERE id = ?",
                         (equipment_id,)).fetchone()
    finally:
        con.close()
    log_event("image_uploaded",
              {"asset_id": asset_id, "equipment_id": equipment_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="vision_asset", entity_id=asset_id)
    return _assess_and_update(asset_id, sess, request, eq_code=eq["code"] if eq else None)


def _assess_and_update(asset_id: int, sess: dict, request: Request,
                       eq_code=None) -> dict:
    from ..multimodal.vision_ingest import assess_quality
    con = connect()
    try:
        row = _owned(con, asset_id, sess["company_id"])
        root = _root()
        fpath = _safe_join(root, row["storage_key"])
        with Image.open(fpath) as img:
            img.load()
            quality = assess_quality(img)
        con.execute("UPDATE vision_assets SET quality_status = ?, quality_detail = ?"
                    " WHERE id = ?",
                    (quality["status"], json.dumps(quality), asset_id))
        con.commit()
        row = con.execute("SELECT * FROM vision_assets WHERE id = ?",
                          (asset_id,)).fetchone()
        if eq_code is None and row["equipment_id"]:
            eq = con.execute("SELECT code FROM equipment WHERE id = ?",
                             (row["equipment_id"],)).fetchone()
            eq_code = eq["code"] if eq else None
    finally:
        con.close()
    log_event("image_analyzed", {"asset_id": asset_id, "quality": quality["status"]},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="vision_asset", entity_id=asset_id)
    return _meta(row, eq_code)


@router.get("/images")
def list_images(sess: dict = Depends(get_current_session),
                equipment_id: int | None = None):
    con = connect()
    try:
        q = ("SELECT v.*, e.code AS equipment_code FROM vision_assets v"
             " LEFT JOIN equipment e ON e.id = v.equipment_id"
             " WHERE v.company_id = ?")
        params: list = [sess["company_id"]]
        if equipment_id is not None:
            q += " AND v.equipment_id = ?"
            params.append(equipment_id)
        q += " ORDER BY v.id DESC"
        rows = con.execute(q, params).fetchall()
    finally:
        con.close()
    return {"images": [_meta(r, r["equipment_code"]) for r in rows]}


@router.get("/images/{asset_id}")
def get_image_meta(asset_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _owned(con, asset_id, sess["company_id"])
        eq = con.execute("SELECT code FROM equipment WHERE id = ?",
                         (row["equipment_id"],)).fetchone()
    finally:
        con.close()
    return _meta(row, eq["code"] if eq else None)


@router.get("/images/{asset_id}/file")
def get_image_file(asset_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _owned(con, asset_id, sess["company_id"])
        fpath = _safe_join(_root(), row["storage_key"])
        if not fpath.is_file():
            raise HTTPException(status_code=404, detail="Stored file missing")
        size = fpath.stat().st_size
        mime = row["mime_type"]
    finally:
        con.close()

    def _stream():
        with open(fpath, "rb") as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(_stream(), media_type=mime,
                             headers={"Content-Length": str(size),
                                      "Content-Disposition":
                                      f'inline; filename="image-{asset_id}.png"'})


@router.post("/images/{asset_id}/quality",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def refresh_quality(asset_id: int, request: Request,
                    sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        _owned(con, asset_id, sess["company_id"])
    finally:
        con.close()
    return _assess_and_update(asset_id, sess, request)


@router.post("/images/{asset_id}/ocr",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def run_ocr(asset_id: int, request: Request,
            sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        row = _owned(con, asset_id, sess["company_id"])
        fpath = _safe_join(_root(), row["storage_key"])
        data = fpath.read_bytes()
    finally:
        con.close()
    if not ocr_available():
        status, text = "UNAVAILABLE", ""
        note = "OCR unavailable in current local environment."
    else:
        import tempfile
        prov = get_ocr_provider()
        tmp = None
        try:
            tmp = Path(tempfile.gettempdir()) / f"ix_ocr_{uuid.uuid4().hex}.png"
            tmp.write_bytes(data)
            text = prov.image_to_text(tmp)
            status, note = "COMPLETED", ""
        except OCRError as e:
            status, text, note = "FAILED", "", str(e)
        finally:
            try:
                if tmp is not None:
                    tmp.unlink()
            except OSError:
                pass
    con = connect()
    try:
        con.execute("UPDATE vision_assets SET ocr_status = ?, ocr_text = ? WHERE id = ?",
                    (status, text, asset_id))
        con.commit()
    finally:
        con.close()
    log_event("image_ocr",
              {"asset_id": asset_id, "status": status},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="vision_asset", entity_id=asset_id)
    return {"asset_id": asset_id, "ocr_status": status,
            "ocr_text": text, "note": note}


@router.post("/images/{asset_id}/analyze",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def analyze_image(asset_id: int, request: Request,
                  sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        row = _owned(con, asset_id, sess["company_id"])
        root = _root()
        fpath = _safe_join(root, row["storage_key"])
        anns = [dict(a) for a in con.execute(
            "SELECT x, y, w, h, label, note FROM vision_annotations"
            " WHERE asset_id = ? AND company_id = ? ORDER BY id",
            (asset_id, sess["company_id"])).fetchall()]
        try:
            qd = json.loads(row["quality_detail"])
        except (ValueError, TypeError):
            qd = {}
    finally:
        con.close()
    quality = {"status": row["quality_status"], **qd}
    if row["quality_status"] == "POOR":
        result = {"agent": _VISION.name, "status": "REFUSED",
                  "reason": "Image quality is POOR: "
                            + "; ".join(qd.get("reasons", ["insufficient visual information"])),
                  "regions": [], "findings": [],
                  "limitation": "Vision reasoning refused on unusable imagery."}
    else:
        result = _VISION.analyze(image_path=fpath, original_filename=row["filename"],
                                 ocr_text=row["ocr_text"] or None,
                                 ocr_status=row["ocr_status"], quality=quality,
                                 annotations=anns)
        result["status"] = "ANALYZED"
    _record_run(sess, row["equipment_id"], "vision:image",
                {"asset_id": asset_id}, result, request)
    return {"asset_id": asset_id, **result}


class AnnotationIn(BaseModel):
    x: float
    y: float
    w: float
    h: float
    label: str
    note: str = ""

    @field_validator("x", "y", "w", "h")
    @classmethod
    def _unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("Region coordinates must be in [0, 1]")
        return v

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        v = v.strip().lower()[:64]
        if v not in _LABELS:
            raise ValueError(f"label must be one of {sorted(_LABELS)}")
        return v

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        return v.strip()[:2000]


def _annotation_row(row) -> dict:
    return {"id": row["id"], "asset_id": row["asset_id"],
            "x": row["x"], "y": row["y"], "w": row["w"], "h": row["h"],
            "label": row["label"], "note": row["note"],
            "created_by": row["created_by"], "created_at": row["created_at"],
            "updated_at": row["updated_at"]}


@router.get("/images/{asset_id}/annotations")
def list_annotations(asset_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _owned(con, asset_id, sess["company_id"])
        rows = con.execute("SELECT * FROM vision_annotations WHERE asset_id = ?"
                           " AND company_id = ? ORDER BY id",
                           (asset_id, sess["company_id"])).fetchall()
    finally:
        con.close()
    return {"annotations": [_annotation_row(r) for r in rows]}


@router.post("/images/{asset_id}/annotations", status_code=201)
def create_annotation(asset_id: int, body: AnnotationIn, request: Request,
                      sess: dict = Depends(get_current_session)):
    if body.w <= 0 or body.h <= 0 or body.x + body.w > 1.0 or body.y + body.h > 1.0:
        raise HTTPException(status_code=422, detail="Region must fit inside the image")
    con = connect()
    try:
        _owned(con, asset_id, sess["company_id"])
        cur = con.execute(
            "INSERT INTO vision_annotations (asset_id, company_id, x, y, w, h,"
            " label, note, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (asset_id, sess["company_id"], body.x, body.y, body.w, body.h,
             body.label, body.note, sess["user_id"], utcnow_iso(), utcnow_iso()))
        aid = cur.lastrowid
        con.commit()
        row = con.execute("SELECT * FROM vision_annotations WHERE id = ?",
                          (aid,)).fetchone()
    finally:
        con.close()
    log_event("annotation_created",
              {"asset_id": asset_id, "annotation_id": aid, "label": body.label},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="vision_asset", entity_id=asset_id)
    return _annotation_row(row)


@router.patch("/images/{asset_id}/annotations/{annotation_id}")
def update_annotation(asset_id: int, annotation_id: int, body: AnnotationIn,
                      request: Request, sess: dict = Depends(get_current_session)):
    if body.w <= 0 or body.h <= 0 or body.x + body.w > 1.0 or body.y + body.h > 1.0:
        raise HTTPException(status_code=422, detail="Region must fit inside the image")
    con = connect()
    try:
        _owned(con, asset_id, sess["company_id"])
        row = con.execute("SELECT * FROM vision_annotations WHERE id = ?"
                          " AND asset_id = ? AND company_id = ?",
                          (annotation_id, asset_id, sess["company_id"])).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Annotation not found")
        if row["created_by"] != sess["user_id"] and sess["role"] != "COMPANY_ADMIN":
            raise HTTPException(status_code=403, detail="Only the author or admin may edit")
        con.execute("UPDATE vision_annotations SET x = ?, y = ?, w = ?, h = ?,"
                    " label = ?, note = ?, updated_at = ? WHERE id = ?",
                    (body.x, body.y, body.w, body.h, body.label, body.note,
                     utcnow_iso(), annotation_id))
        con.commit()
        row = con.execute("SELECT * FROM vision_annotations WHERE id = ?",
                          (annotation_id,)).fetchone()
    finally:
        con.close()
    log_event("annotation_modified",
              {"asset_id": asset_id, "annotation_id": annotation_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="vision_asset", entity_id=asset_id)
    return _annotation_row(row)


@router.delete("/images/{asset_id}/annotations/{annotation_id}")
def delete_annotation(asset_id: int, annotation_id: int, request: Request,
                      sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _owned(con, asset_id, sess["company_id"])
        row = con.execute("SELECT * FROM vision_annotations WHERE id = ?"
                          " AND asset_id = ? AND company_id = ?",
                          (annotation_id, asset_id, sess["company_id"])).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Annotation not found")
        if row["created_by"] != sess["user_id"] and sess["role"] != "COMPANY_ADMIN":
            raise HTTPException(status_code=403, detail="Only the author or admin may delete")
        con.execute("DELETE FROM vision_annotations WHERE id = ?", (annotation_id,))
        con.commit()
    finally:
        con.close()
    log_event("annotation_deleted",
              {"asset_id": asset_id, "annotation_id": annotation_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="vision_asset", entity_id=asset_id)
    return {"message": "Annotation deleted"}


def _record_run(sess: dict, equipment_id, method: str, params: dict,
                result: dict, request: Request) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO analysis_runs (company_id, equipment_id, kind, input_ref,"
            " method, params, result_summary, warnings, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sess["company_id"], equipment_id, "vision",
             json.dumps(params), method, json.dumps(params),
             json.dumps(result)[:4000], json.dumps([]),
             sess["user_id"], utcnow_iso()))
        conn.commit()
    finally:
        conn.close()
