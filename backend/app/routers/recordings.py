"""Stage 10: Live Video Investigation Recording System.
Recording lifecycle, chunked uploads, frame extraction, AI interaction, evidence integration.
"""
import hashlib
import io
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from ..audit import log_event
from ..core.config import ROOT, get_settings
from ..core.deps import get_current_session, require_roles
from ..core.rate_limit import allow
from ..core.security import utcnow_iso
from ..db import connect
from ..processing.video_frames import extract_keyframes, extract_frame_at_timestamp

router = APIRouter(prefix="/api/recordings", tags=["recordings"])
_CHUNK_SIZE = 1024 * 1024


class RecordingCreate(BaseModel):
    investigation_id: Optional[int] = None
    case_id: Optional[int] = None
    equipment_id: int
    title: str = ""
    description: str = ""
    media_type: str = "video"

    @field_validator("media_type")
    @classmethod
    def _mt(cls, v: str) -> str:
        if v not in ("video", "audio", "video+audio"):
            raise ValueError("media_type must be video, audio, or video+audio")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return v.strip()[:200]


class RecordingPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class RecordingPause(BaseModel):
    pass


class RecordingResume(BaseModel):
    pass


class RecordingStop(BaseModel):
    pass


class ChunkUploadInfo(BaseModel):
    recording_id: int
    chunk_index: int
    total_chunks: int
    chunk_sha256: str


class FrameCapture(BaseModel):
    recording_id: int
    timestamp_seconds: float
    capture_type: str = "MANUAL"

    @field_validator("capture_type")
    @classmethod
    def _ct(cls, v: str) -> str:
        if v not in ("MANUAL", "PERIODIC", "EVENT_TRIGGERED"):
            raise ValueError("capture_type must be MANUAL, PERIODIC, or EVENT_TRIGGERED")
        return v


class AIQuestion(BaseModel):
    recording_id: int
    question: str
    recording_timestamp_seconds: float

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Question must not be empty")
        return v[:4000]


class TranscriptSegment(BaseModel):
    recording_id: int
    start_time: float
    end_time: float
    transcript_text: str
    language: str = "en"
    confidence: Optional[float] = None


def _limited(sess: dict, action: str = "recording") -> None:
    ok, retry = allow(f"{action}:{sess['user_id']}", 60, 60)
    if not ok:
        raise HTTPException(status_code=429, detail="Rate limit reached.",
                            headers={"Retry-After": str(retry)})


def _owned_recording(con, rec_id: int, company_id: int):
    row = con.execute("SELECT * FROM recording_sessions WHERE id = ? AND company_id = ?",
                      (rec_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    return row


def _owned_investigation(con, inv_id: int, company_id: int):
    row = con.execute("SELECT * FROM investigations WHERE id = ? AND company_id = ?",
                      (inv_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return row


def _owned_case(con, case_id: int, company_id: int):
    row = con.execute("SELECT * FROM cases WHERE id = ? AND company_id = ?",
                      (case_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return row


def _owned_equipment(con, eq_id: int, company_id: int):
    row = con.execute("SELECT * FROM equipment WHERE id = ? AND company_id = ? AND is_active = 1",
                      (eq_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return row


def _storage_root() -> Path:
    p = Path(get_settings().STORAGE_RECORDINGS)
    return p if p.is_absolute() else ROOT / p


def _safe_join(root: Path, *parts: str) -> Path:
    target = (root.joinpath(*parts)).resolve()
    if target != root.resolve() and root.resolve() not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid storage path")
    return target


def _save_chunk(con, recording_id: int, company_id: int, chunk_index: int,
                chunk_bytes: bytes, chunk_sha256: str, start_time: float,
                end_time: float, duration: float) -> dict:
    """Save a chunk and return the chunk record."""
    root = _storage_root()
    company_dir = root / str(company_id)
    company_dir.mkdir(parents=True, exist_ok=True)
    
    storage_key = f"chunks/{company_id}/rec_{recording_id}_chunk_{chunk_index}.webm"
    file_path = _safe_join(root, storage_key)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, "wb") as f:
        f.write(chunk_bytes)
    
    cur = con.execute(
        "INSERT INTO recording_chunks (recording_id, company_id, chunk_index, chunk_size, "
        "chunk_sha256, storage_key, start_time, end_time, duration_seconds, status, uploaded_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (recording_id, company_id, chunk_index, len(chunk_bytes), chunk_sha256,
         storage_key, start_time, end_time, end_time - start_time, "COMPLETED", utcnow_iso()))
    con.commit()
    return dict(con.execute("SELECT * FROM recording_chunks WHERE id = ?", (cur.lastrowid,)).fetchone())


def _merge_chunks(recording_id: int, company_id: int) -> dict:
    """Merge chunks into final recording file."""
    con = connect()
    try:
        chunks = con.execute(
            "SELECT storage_key, chunk_index, chunk_sha256, start_time, end_time, duration_seconds "
            "FROM recording_chunks WHERE recording_id = ? AND company_id = ? AND status = 'COMPLETED' "
            "ORDER BY chunk_index", (recording_id, company_id)).fetchall()
        
        if not chunks:
            raise HTTPException(status_code=400, detail="No chunks to merge")
        
        root = _storage_root()
        merged_path = _safe_join(_storage_root(), f"recordings/{company_id}/rec_{recording_id}.webm")
        merged_path.parent.mkdir(parents=True, exist_ok=True)
        
        total_size = 0
        merged_sha256 = hashlib.sha256()
        
        with open(merged_path, "wb") as out:
            for ch in chunks:
                chunk_path = _safe_join(_storage_root(), ch["storage_key"])
                if not chunk_path.exists():
                    continue
                with open(chunk_path, "rb") as f:
                    data = f.read()
                    out.write(data)
                    merged_sha256.update(data)
                    total_size += len(data)
        
        # Update recording session
        cur = con.execute(
            "UPDATE recording_sessions SET storage_key = ?, file_size = ?, sha256_hash = ?, "
            "processing_status = 'COMPLETED', status = 'COMPLETED', stopped_at = ?, "
            "duration_seconds = ?, updated_at = ? WHERE id = ?",
            (f"recordings/{company_id}/rec_{recording_id}.webm",
             total_size, merged_sha256.hexdigest(), utcnow_iso(),
             sum(c["duration_seconds"] for c in chunks), utcnow_iso(), recording_id))
        con.commit()
        
        # Mark chunks as merged
        for ch in chunks:
            con.execute("UPDATE recording_chunks SET status = 'MERGED' WHERE storage_key = ?", (ch["storage_key"],))
        con.commit()
        
        return dict(con.execute("SELECT * FROM recording_sessions WHERE id = ?", (recording_id,)).fetchone())
    finally:
        con.close()


@router.post("", status_code=201)
async def create_recording(body: RecordingCreate, request: Request,
                           sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        # Validate equipment
        _owned_equipment(con, body.equipment_id, sess["company_id"])
        
        # Validate investigation if provided
        inv_id = body.investigation_id
        if inv_id:
            _owned_investigation(con, inv_id, sess["company_id"])
        
        # Validate case if provided
        case_id = body.case_id
        if case_id:
            _owned_case(con, case_id, sess["company_id"])
        
        # Create recording session
        cur = con.execute(
            "INSERT INTO recording_sessions (company_id, workspace_id, investigation_id, case_id, "
            "equipment_id, title, description, media_type, status, created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sess["company_id"], sess.get("workspace_id"), body.investigation_id, body.case_id,
             body.equipment_id, body.title, body.description, body.media_type, "DRAFT",
             sess["user_id"], utcnow_iso(), utcnow_iso()))
        rec_id = cur.lastrowid
        con.commit()
        
        # Log event
        log_event("recording_created", {"recording_id": rec_id, "equipment_id": body.equipment_id},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="recording", entity_id=rec_id)
        
        return dict(con.execute("SELECT * FROM recording_sessions WHERE id = ?", (rec_id,)).fetchone())
    finally:
        con.close()


@router.get("")
def list_recordings(sess: dict = Depends(get_current_session),
                    investigation_id: Optional[int] = None,
                    case_id: Optional[int] = None,
                    equipment_id: Optional[int] = None,
                    status: Optional[str] = None,
                    page: int = 1, page_size: int = 20):
    con = connect()
    try:
        q = "SELECT * FROM recording_sessions WHERE company_id = ?"
        params = [sess["company_id"]]
        if investigation_id:
            q += " AND investigation_id = ?"; params.append(investigation_id)
        if case_id:
            q += " AND case_id = ?"; params.append(case_id)
        if equipment_id:
            q += " AND equipment_id = ?"; params.append(equipment_id)
        if status:
            q += " AND status = ?"; params.append(status)
        
        total = con.execute(f"SELECT COUNT(*) FROM ({q})", params).fetchone()[0]
        rows = con.execute(q + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                           (*params, page_size, (page - 1) * page_size)).fetchall()
        return {"recordings": [dict(r) for r in rows], "total": total,
                "page": page, "page_size": page_size}
    finally:
        con.close()


@router.get("/{rec_id}")
def get_recording(rec_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        rec = _owned_recording(con, rec_id, sess["company_id"])
        return dict(rec)
    finally:
        con.close()


@router.patch("/{rec_id}")
def patch_recording(rec_id: int, body: RecordingPatch, request: Request,
                    sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        rec = _owned_recording(con, rec_id, sess["company_id"])
        if rec["status"] not in ("DRAFT", "RECORDING", "PAUSED"):
            raise HTTPException(status_code=422, detail="Cannot modify recording in current state")
        
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if updates:
            con.execute("UPDATE recording_sessions SET updated_at = ?, " +
                       ", ".join(f"{k} = ?" for k in updates) + " WHERE id = ?",
                       (utcnow_iso(), *updates.values(), rec_id))
            con.commit()
        
        log_event("recording_updated", {"recording_id": rec_id, "changed": list(updates)},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="recording", entity_id=rec_id)
        return dict(con.execute("SELECT * FROM recording_sessions WHERE id = ?", (rec_id,)).fetchone())
    finally:
        con.close()


@router.post("/{rec_id}/start")
async def start_recording(rec_id: int, request: Request,
                          sess: dict = Depends(get_current_session)):
    _limited(sess, "recording_start")
    con = connect()
    try:
        rec = _owned_recording(con, rec_id, sess["company_id"])
        if rec["status"] != "DRAFT":
            raise HTTPException(status_code=422, detail="Recording must be in DRAFT state")
        
        con.execute("UPDATE recording_sessions SET status = 'RECORDING', started_at = ?, "
                    "updated_at = ? WHERE id = ?",
                    (utcnow_iso(), utcnow_iso(), rec_id))
        con.commit()
        
        log_event("recording_started", {"recording_id": rec_id},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="recording", entity_id=rec_id)
        
        # Create recording event
        con.execute("INSERT INTO recording_events (recording_id, company_id, event_type, "
                    "wall_clock_timestamp, user_id, payload) VALUES (?,?,?,?,?,?)",
                    (rec_id, sess["company_id"], "RECORDING_STARTED",
                     utcnow_iso(), sess["user_id"], "{}"))
        con.commit()
        
        return dict(con.execute("SELECT * FROM recording_sessions WHERE id = ?", (rec_id,)).fetchone())
    finally:
        con.close()


@router.post("/{rec_id}/pause")
async def pause_recording(rec_id: int, request: Request,
                          sess: dict = Depends(get_current_session)):
    _limited(sess, "recording_pause")
    con = connect()
    try:
        rec = _owned_recording(con, rec_id, sess["company_id"])
        if rec["status"] != "RECORDING":
            raise HTTPException(status_code=422, detail="Recording is not currently recording")
        
        con.execute("UPDATE recording_sessions SET status = 'PAUSED', paused_at = ?, "
                    "updated_at = ? WHERE id = ?",
                    (utcnow_iso(), utcnow_iso(), rec_id))
        con.commit()
        
        log_event("recording_paused", {"recording_id": rec_id},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="recording", entity_id=rec_id)
        
        con.execute("INSERT INTO recording_events (recording_id, company_id, event_type, "
                    "wall_clock_timestamp, user_id, payload) VALUES (?,?,?,?,?,?)",
                    (rec_id, sess["company_id"], "RECORDING_PAUSED",
                     utcnow_iso(), sess["user_id"], "{}"))
        con.commit()
        
        return dict(con.execute("SELECT * FROM recording_sessions WHERE id = ?", (rec_id,)).fetchone())
    finally:
        con.close()


@router.post("/{rec_id}/resume")
async def resume_recording(rec_id: int, request: Request,
                           sess: dict = Depends(get_current_session)):
    _limited(sess, "recording_resume")
    con = connect()
    try:
        rec = _owned_recording(con, rec_id, sess["company_id"])
        if rec["status"] != "PAUSED":
            raise HTTPException(status_code=422, detail="Recording is not paused")
        
        paused_duration = 0
        if rec["paused_at"]:
            paused_at = datetime.fromisoformat(rec["paused_at"])
            now = datetime.fromisoformat(utcnow_iso())
            paused_duration = int((now - paused_at).total_seconds())
        
        con.execute("UPDATE recording_sessions SET status = 'RECORDING', paused_at = NULL, "
                    "paused_duration = paused_duration + ?, updated_at = ? WHERE id = ?",
                    (paused_duration, utcnow_iso(), rec_id))
        con.commit()
        
        log_event("recording_resumed", {"recording_id": rec_id, "paused_duration": paused_duration},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="recording", entity_id=rec_id)
        
        con.execute("INSERT INTO recording_events (recording_id, company_id, event_type, "
                    "wall_clock_timestamp, user_id, payload) VALUES (?,?,?,?,?,?)",
                    (rec_id, sess["company_id"], "RECORDING_RESUMED",
                     utcnow_iso(), sess["user_id"], json.dumps({"paused_duration": paused_duration})))
        con.commit()
        
        return dict(con.execute("SELECT * FROM recording_sessions WHERE id = ?", (rec_id,)).fetchone())
    finally:
        con.close()


@router.post("/{rec_id}/stop")
async def stop_recording(rec_id: int, request: Request,
                         sess: dict = Depends(get_current_session)):
    _limited(sess, "recording_stop")
    con = connect()
    try:
        rec = _owned_recording(con, rec_id, sess["company_id"])
        if rec["status"] not in ("RECORDING", "PAUSED"):
            raise HTTPException(status_code=422, detail="Recording is not in progress")
        
        # Calculate duration
        started = rec["started_at"]
        paused_dur = rec["paused_duration"] or 0
        if started:
            start_dt = datetime.fromisoformat(started)
            now = datetime.fromisoformat(utcnow_iso())
            duration = int((now - start_dt).total_seconds()) - paused_dur
        else:
            duration = 0
        
        con.execute("UPDATE recording_sessions SET status = 'PROCESSING', stopped_at = ?, "
                    "duration_seconds = ?, paused_at = NULL, updated_at = ? WHERE id = ?",
                    (utcnow_iso(), max(0, duration), utcnow_iso(), rec_id))
        con.commit()
        
        log_event("recording_stopped", {"recording_id": rec_id, "duration_seconds": duration},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="recording", entity_id=rec_id)
        
        con.execute("INSERT INTO recording_events (recording_id, company_id, event_type, "
                    "wall_clock_timestamp, user_id, payload) VALUES (?,?,?,?,?,?)",
                    (rec_id, sess["company_id"], "RECORDING_STOPPED",
                     utcnow_iso(), sess["user_id"], json.dumps({"duration_seconds": duration})))
        con.commit()
        
        # Mark for async processing
        con.execute("UPDATE recording_sessions SET processing_status = 'QUEUED' WHERE id = ?", (rec_id,))
        con.commit()
        
        return dict(con.execute("SELECT * FROM recording_sessions WHERE id = ?", (rec_id,)).fetchone())
    finally:
        con.close()


@router.post("/{rec_id}/chunks")
async def upload_chunk(rec_id: int, request: Request,
                       chunk_index: int = Form(...),
                       total_chunks: int = Form(...),
                       chunk_sha256: str = Form(...),
                       start_time: float = Form(...),
                       end_time: float = Form(...),
                       file: UploadFile = File(...),
                       sess: dict = Depends(get_current_session)):
    _limited(sess, "chunk_upload")
    con = connect()
    try:
        rec = _owned_recording(con, rec_id, sess["company_id"])
        if rec["status"] not in ("RECORDING", "PAUSED", "PROCESSING"):
            raise HTTPException(status_code=422, detail="Recording not accepting chunks")

        # Read chunk bytes exactly once and verify SHA256 over those bytes.
        chunk_bytes = await file.read()
        if len(chunk_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty chunk")

        computed = hashlib.sha256(chunk_bytes).hexdigest()
        if computed != chunk_sha256:
            raise HTTPException(status_code=422, detail="Chunk SHA256 mismatch")

        duration = max(0.0, (end_time or 0.0) - (start_time or 0.0))

        chunk = _save_chunk(con, rec_id, sess["company_id"], chunk_index,
                            chunk_bytes, chunk_sha256, start_time or 0.0,
                            end_time or 0.0, duration)

        log_event("recording_chunk_uploaded", {"recording_id": rec_id, "chunk_index": chunk_index},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="recording_chunk", entity_id=chunk["id"])

        return chunk
    finally:
        con.close()


@router.post("/{rec_id}/merge")
async def merge_chunks(rec_id: int, request: Request,
                       sess: dict = Depends(get_current_session)):
    _limited(sess, "recording_merge")
    result = _merge_chunks(rec_id, sess["company_id"])
    return result


@router.post("/{rec_id}/frames", status_code=201)
async def capture_frame(rec_id: int, body: FrameCapture, request: Request,
                        sess: dict = Depends(get_current_session)):
    _limited(sess, "frame_capture")
    con = connect()
    try:
        rec = _owned_recording(con, rec_id, sess["company_id"])
        if rec["status"] not in ("RECORDING", "PAUSED", "PROCESSING", "COMPLETED"):
            raise HTTPException(status_code=422, detail="Recording not in capturable state")
        
        # Extract frame at timestamp
        if rec["storage_key"]:
            root = _storage_root()
            video_path = _safe_join(_storage_root(), rec["storage_key"])
            if video_path.exists():
                frame_bytes, metadata = extract_frame_at_timestamp(
                    str(video_path), body.timestamp_seconds)
                
                # Save frame
                sha256_hash = hashlib.sha256(frame_bytes).hexdigest()
                frame_key = f"frames/{sess['company_id']}/rec_{rec_id}_frame_{uuid.uuid4().hex[:8]}.jpg"
                frame_path = _safe_join(_storage_root(), frame_key)
                frame_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(frame_path, "wb") as f:
                    f.write(frame_bytes)
                
                cur = con.execute(
                    "INSERT INTO recording_frames (recording_id, company_id, investigation_id, case_id, "
                    "equipment_id, frame_index, timestamp_seconds, recording_timestamp_seconds, "
                    "frame_timestamp, storage_key, file_size, sha256_hash, width, height, "
                    "capture_type, analysis_status, captured_by, captured_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rec_id, sess["company_id"], rec["investigation_id"], rec["case_id"],
                     rec["equipment_id"], 0, body.timestamp_seconds, body.timestamp_seconds,
                     utcnow_iso(), f"frames/{sess['company_id']}/rec_{rec_id}_{uuid.uuid4().hex[:8]}.jpg",
                     len(frame_bytes), hashlib.sha256(frame_bytes).hexdigest(),
                     metadata.get("width", 0), metadata.get("height", 0),
                     body.capture_type, "PENDING", sess["user_id"], utcnow_iso()))
                frame_id = cur.lastrowid
                con.commit()
                
                log_event("recording_frame_captured", {"recording_id": rec_id, "frame_id": frame_id},
                          company_id=sess["company_id"], user_id=sess["user_id"],
                          ip=_client_ip(request), entity_type="recording_frame", entity_id=frame_id)
                
                # Create recording event
                con.execute("INSERT INTO recording_events (recording_id, company_id, event_type, "
                            "timestamp_seconds, recording_timestamp_seconds, wall_clock_timestamp, "
                            "user_id, payload) VALUES (?,?,?,?,?,?,?,?)",
                            (rec_id, sess["company_id"], "FRAME_CAPTURED",
                             body.timestamp_seconds, body.timestamp_seconds, utcnow_iso(),
                             sess["user_id"], json.dumps({"frame_id": frame_id})))
                con.commit()
                
                return dict(con.execute("SELECT * FROM recording_frames WHERE id = ?", (frame_id,)).fetchone())
        
        raise HTTPException(status_code=404, detail="Recording video not found")
    finally:
        con.close()


@router.get("/{rec_id}/frames")
def list_frames(rec_id: int, sess: dict = Depends(get_current_session),
                page: int = 1, page_size: int = 20):
    con = connect()
    try:
        _owned_recording(con, rec_id, sess["company_id"])
        total = con.execute("SELECT COUNT(*) FROM recording_frames WHERE recording_id = ? AND company_id = ?",
                            (rec_id, sess["company_id"])).fetchone()[0]
        rows = con.execute("SELECT * FROM recording_frames WHERE recording_id = ? AND company_id = ? "
                           "ORDER BY frame_index LIMIT ? OFFSET ?",
                           (rec_id, sess["company_id"], page_size, (page - 1) * page_size)).fetchall()
        return {"frames": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}
    finally:
        con.close()


@router.post("/{rec_id}/questions", status_code=201)
async def ask_ai(rec_id: int, body: AIQuestion, request: Request,
                 sess: dict = Depends(get_current_session)):
    _limited(sess, "ai_question")
    con = connect()
    try:
        rec = _owned_recording(con, rec_id, sess["company_id"])

        # Grounded answer: reuse the existing deterministic investigation
        # copilot (no LLM, no fabrication). If the recording is linked to an
        # investigation, answer over its real evidence/hypotheses; otherwise
        # report the model honestly as unavailable.
        answer_text, provider, model = _grounded_copilot_answer(
            con, rec, body.question, sess["company_id"])

        # Build context for audit/provenance.
        context = {
            "case_id": rec["case_id"],
            "investigation_id": rec["investigation_id"],
            "equipment_id": rec["equipment_id"],
            "recording_id": rec_id,
            "recording_timestamp_seconds": body.recording_timestamp_seconds,
        }

        # Create interaction record
        cur = con.execute(
            "INSERT INTO recording_ai_interactions (recording_id, company_id, investigation_id, "
            "case_id, user_id, question, answer, recording_timestamp_seconds, wall_clock_timestamp, "
            "context_snapshot, provider, model, latency_ms, provenance) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rec_id, sess["company_id"], rec["investigation_id"], rec["case_id"],
             sess["user_id"], body.question, answer_text, body.recording_timestamp_seconds,
             utcnow_iso(), json.dumps(context), provider, model, 0, "{}"))
        interaction_id = cur.lastrowid
        con.commit()

        log_event("recording_ai_question", {"recording_id": rec_id, "interaction_id": interaction_id},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="recording_ai_interaction", entity_id=interaction_id)

        con.execute("INSERT INTO recording_events (recording_id, company_id, event_type, "
                    "timestamp_seconds, recording_timestamp_seconds, wall_clock_timestamp, "
                    "user_id, payload) VALUES (?,?,?,?,?,?,?,?)",
                    (rec_id, sess["company_id"], "AI_QUESTION",
                     body.recording_timestamp_seconds, body.recording_timestamp_seconds, utcnow_iso(),
                     sess["user_id"], json.dumps({"interaction_id": interaction_id, "question": body.question})))
        con.commit()

        # Log AI response event (only if an answer was produced).
        con.execute("INSERT INTO recording_events (recording_id, company_id, event_type, "
                    "timestamp_seconds, recording_timestamp_seconds, wall_clock_timestamp, "
                    "user_id, payload) VALUES (?,?,?,?,?,?,?,?)",
                    (rec_id, sess["company_id"], "AI_RESPONSE",
                     body.recording_timestamp_seconds, body.recording_timestamp_seconds, utcnow_iso(),
                     sess["user_id"], json.dumps({"interaction_id": interaction_id})))
        con.commit()

        return dict(con.execute("SELECT * FROM recording_ai_interactions WHERE id = ?", (interaction_id,)).fetchone())
    finally:
        con.close()


def _grounded_copilot_answer(con, rec, question: str, company_id: int):
    """Produce a grounded, deterministic answer reusing the Stage 7 copilot.

    Never fabricates an AI/LLM response. If the recording is linked to a real
    investigation, answers over its actual evidence/hypotheses; otherwise
    reports the model honestly as unavailable.
    """
    if rec["investigation_id"]:
        try:
            from ..investigation import copilot as copilot_mod
            from ..investigation.common import company_settings
            from . import hypotheses as hyp_mod

            inv_id = rec["investigation_id"]
            inv = con.execute(
                "SELECT * FROM investigations WHERE id = ? AND company_id = ?",
                (inv_id, company_id)).fetchone()
            if inv is not None:
                settings = company_settings(con, company_id)
                view = hyp_mod.full_view(con, dict(inv), settings)
                recs = hyp_mod.stored_recommendations(con, inv_id)
                assumptions = [dict(r) for r in con.execute(
                    "SELECT * FROM assumptions WHERE investigation_id = ?", (inv_id,)).fetchall()]
                conflicts = [dict(r) for r in con.execute(
                    "SELECT * FROM conflicts WHERE investigation_id = ? AND status = 'OPEN'",
                    (inv_id,)).fetchall()]
                health = hyp_mod.health_for(con, dict(inv), settings)
                out = copilot_mod.answer(
                    question=question, investigation=dict(inv), equipment=view["equipment"],
                    evidence=view["evidence"], scored=view["hypotheses"],
                    missing=view["missing"], recommendations=recs,
                    assumptions=assumptions, conflicts=conflicts, health=health)
                return out.get("answer", ""), "local", "deterministic-copilot"
        except Exception:
            # On any integration failure, fall through to the honest message
            # rather than fabricating an answer.
            pass

    return (
        "Local AI model is unavailable. No investigation is linked to this "
        "recording, so no grounded assistant response can be produced.",
        "local", "offline",
    )


@router.get("/{rec_id}/interactions")
def list_ai_interactions(rec_id: int, sess: dict = Depends(get_current_session),
                         page: int = 1, page_size: int = 20):
    con = connect()
    try:
        _owned_recording(con, rec_id, sess["company_id"])
        total = con.execute("SELECT COUNT(*) FROM recording_ai_interactions WHERE recording_id = ? AND company_id = ?",
                            (rec_id, sess["company_id"])).fetchone()[0]
        rows = con.execute("SELECT * FROM recording_ai_interactions WHERE recording_id = ? AND company_id = ? "
                           "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                           (rec_id, sess["company_id"], page_size, (page - 1) * page_size)).fetchall()
        return {"interactions": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}
    finally:
        con.close()


@router.get("/{rec_id}/events")
def list_events(rec_id: int, sess: dict = Depends(get_current_session),
                event_type: Optional[str] = None,
                page: int = 1, page_size: int = 50):
    con = connect()
    try:
        _owned_recording(con, rec_id, sess["company_id"])
        q = "SELECT * FROM recording_events WHERE recording_id = ? AND company_id = ?"
        params = [rec_id, sess["company_id"]]
        if event_type:
            q += " AND event_type = ?"; params.append(event_type)
        total = con.execute(f"SELECT COUNT(*) FROM ({q})", params).fetchone()[0]
        rows = con.execute(q + " ORDER BY wall_clock_timestamp DESC LIMIT ? OFFSET ?",
                           (*params, page_size, (page - 1) * page_size)).fetchall()
        return {"events": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}
    finally:
        con.close()


@router.post("/{rec_id}/evidence", status_code=201)
async def create_evidence_from_frame(rec_id: int, frame_id: int = Form(...),
                                     title: str = Form(...),
                                     description: str = Form(""),
                                     sess: dict = Depends(get_current_session)):
    _limited(sess, "evidence_create")
    con = connect()
    try:
        rec = _owned_recording(con, rec_id, sess["company_id"])
        frame = con.execute("SELECT * FROM recording_frames WHERE id = ? AND recording_id = ? AND company_id = ?",
                            (frame_id, rec_id, sess["company_id"])).fetchone()
        if not frame:
            raise HTTPException(status_code=404, detail="Frame not found")
        
        # Create evidence record
        cur = con.execute(
            "INSERT INTO evidence (investigation_id, company_id, equipment_id, type, source, title, "
            "description, content, confidence, reliability, timestamp, created_by, metadata, provenance) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rec["investigation_id"], sess["company_id"], rec["equipment_id"],
             "VIDEO_FRAME", "live_recording", title, description,
             f"Frame from recording {rec_id} at {frame['recording_timestamp_seconds']}s",
             0.9, 0.9, utcnow_iso(), sess["user_id"],
             json.dumps({"recording_id": rec_id, "frame_id": frame_id,
                         "recording_timestamp": frame["recording_timestamp_seconds"]}),
             json.dumps({"recording_id": rec_id, "frame_id": frame_id,
                         "storage_key": frame["storage_key"],
                         "sha256": frame["sha256_hash"]})))
        evidence_id = cur.lastrowid
        
        # Link recording evidence
        con.execute("INSERT INTO recording_evidence (recording_id, frame_id, evidence_id, "
                    "company_id, investigation_id, case_id, created_by) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (rec_id, frame_id, evidence_id, sess["company_id"],
                     rec["investigation_id"], rec["case_id"], sess["user_id"]))
        
        # Update frame analysis status
        con.execute("UPDATE recording_frames SET analysis_status = 'COMPLETED', "
                    "analysis_completed_at = ? WHERE id = ?",
                    (utcnow_iso(), frame_id))
        
        con.commit()
        
        log_event("recording_evidence_created", {"recording_id": rec_id, "frame_id": frame_id, "evidence_id": evidence_id},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_client_ip(request), entity_type="evidence", entity_id=evidence_id)
        
        con.execute("INSERT INTO recording_events (recording_id, company_id, event_type, "
                    "timestamp_seconds, recording_timestamp_seconds, wall_clock_timestamp, "
                    "user_id, payload) VALUES (?,?,?,?,?,?,?,?)",
                    (rec_id, sess["company_id"], "EVIDENCE_CREATED",
                     frame["recording_timestamp_seconds"], frame["recording_timestamp_seconds"], utcnow_iso(),
                     sess["user_id"], json.dumps({"frame_id": frame_id, "evidence_id": evidence_id})))
        con.commit()
        
        return dict(con.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone())
    finally:
        con.close()


@router.get("/{rec_id}/evidence")
def list_evidence(rec_id: int, sess: dict = Depends(get_current_session),
                  page: int = 1, page_size: int = 20):
    con = connect()
    try:
        _owned_recording(con, rec_id, sess["company_id"])
        total = con.execute("SELECT COUNT(*) FROM recording_evidence WHERE recording_id = ? AND company_id = ?",
                            (rec_id, sess["company_id"])).fetchone()[0]
        rows = con.execute("""
            SELECT re.*, e.title as evidence_title, e.type as evidence_type, e.created_at as evidence_created
            FROM recording_evidence re
            JOIN evidence e ON e.id = re.evidence_id
            WHERE re.recording_id = ? AND re.company_id = ?
            ORDER BY re.created_at DESC LIMIT ? OFFSET ?
        """, (rec_id, sess["company_id"], page_size, (page - 1) * page_size)).fetchall()
        return {"evidence": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}
    finally:
        con.close()


@router.get("/{rec_id}/transcripts")
def list_transcripts(rec_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        _owned_recording(con, rec_id, sess["company_id"])
        rows = con.execute("SELECT * FROM recording_transcripts WHERE recording_id = ? AND company_id = ? "
                           "ORDER BY segment_index", (rec_id, sess["company_id"])).fetchall()
        return {"transcripts": [dict(r) for r in rows]}
    finally:
        con.close()


@router.post("/{rec_id}/transcripts", status_code=201)
async def add_transcript(rec_id: int, body: TranscriptSegment, sess: dict = Depends(get_current_session)):
    _limited(sess, "transcript_add")
    con = connect()
    try:
        _owned_recording(con, rec_id, sess["company_id"])
        
        # Find segment index
        count = con.execute("SELECT COUNT(*) FROM recording_transcripts WHERE recording_id = ?",
                            (rec_id,)).fetchone()[0]
        
        cur = con.execute(
            "INSERT INTO recording_transcripts (recording_id, company_id, segment_index, "
            "start_time, end_time, transcript_text, language, confidence, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (rec_id, sess["company_id"], count, body.start_time, body.end_time,
             body.transcript_text, body.language, body.confidence, sess["user_id"]))
        con.commit()
        
        return dict(con.execute("SELECT * FROM recording_transcripts WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        con.close()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


from datetime import datetime