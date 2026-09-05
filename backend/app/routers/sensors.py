"""Sensor intelligence API: CSV ingestion, quality, statistics, trend,
anomalies, FFT, correlation, event windows, export.

Tenant rule: every dataset owned via (id, company_id); foreign ids → 404.
RBAC: upload/analyze = ADMIN+ENGINEER; read/export = all roles.
All math is local numpy; error messages are sanitized.
"""
import csv
import hashlib
import io
import json
import os
import uuid
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from ..agents.analysis_agents import DataAnalysisAgent
from ..audit import log_event
from ..core.config import ROOT, get_settings
from ..core.deps import get_current_session, require_roles
from ..core.rate_limit import allow
from ..core.security import utcnow_iso
from ..db import connect
from ..multimodal import sensor_analysis as A
from ..multimodal import sensor_quality as Q
from ..multimodal.sensor_ingest import IngestError, parse_csv

router = APIRouter(prefix="/api/sensors", tags=["sensors"])
_ANALYZER = DataAnalysisAgent()
_CHUNK = 1024 * 1024
_ANOM_METHODS = ("zscore", "rolling_zscore", "iqr", "threshold")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _root() -> Path:
    p = Path(get_settings().STORAGE_SENSORS)
    return p if p.is_absolute() else ROOT / p


def _safe_join(root: Path, *parts: str) -> Path:
    target = (root.joinpath(*parts)).resolve()
    if target != root.resolve() and root.resolve() not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid storage path")
    return target


def _owned(con, dataset_id: int, company_id: int):
    row = con.execute("SELECT * FROM sensor_datasets WHERE id = ? AND company_id = ?",
                      (dataset_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Sensor dataset not found")
    return row


def _check_equipment(con, equipment_id: int, company_id: int):
    eq = con.execute("SELECT id FROM equipment WHERE id = ? AND company_id = ?"
                     " AND is_active = 1", (equipment_id, company_id)).fetchone()
    if eq is None:
        raise HTTPException(status_code=404, detail="Equipment not found")


def _meta(row, equipment_code=None) -> dict:
    try:
        channels = json.loads(row["channels"])
    except (ValueError, TypeError):
        channels = []
    return {
        "id": row["id"], "equipment_id": row["equipment_id"],
        "equipment_code": equipment_code, "name": row["name"],
        "source_filename": row["source_filename"],
        "sha256_hash": row["sha256_hash"], "channels": channels,
        "row_count": row["row_count"], "time_start": row["time_start"],
        "time_end": row["time_end"],
        "sample_interval_s": row["sample_interval_s"],
        "quality_status": row["quality_status"],
        "quality_score": row["quality_score"], "created_at": row["created_at"],
    }


def _limited(sess: dict, action: str = "sensor:analyze") -> None:
    ok, retry = allow(f"{action}:{sess['user_id']}", 60, 60)
    if not ok:
        raise HTTPException(status_code=429, detail="Analysis rate limit reached.",
                            headers={"Retry-After": str(retry)})


@router.post("/upload", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
async def upload_dataset(request: Request, file: UploadFile = File(...),
                         equipment_id: int = Form(...),
                         name: str | None = Form(None),
                         sess: dict = Depends(get_current_session)):
    s = get_settings()
    max_bytes = s.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    fname = (file.filename or "").strip()
    if not fname.lower().endswith(".csv") or "/" in fname or "\\" in fname \
            or fname.startswith("."):
        raise HTTPException(status_code=422, detail="Only .csv sensor files are supported")
    tmp_path = (ROOT / Path(s.STORAGE_TEMP)) / f"sensor_{uuid.uuid4().hex}.tmp"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    hasher, size = hashlib.sha256(), 0
    try:
        with open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (limit {s.MAX_UPLOAD_SIZE_MB} MB)")
                hasher.update(chunk)
                out.write(chunk)
    except HTTPException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    if size == 0:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=422, detail="File is empty")
    digest = hasher.hexdigest()
    try:
        ingest = parse_csv(tmp_path.read_bytes(), max_rows=s.SENSOR_MAX_ROWS,
                           max_channels=s.SENSOR_MAX_CHANNELS)
    except IngestError as e:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=422, detail=str(e))
    con = connect()
    try:
        _check_equipment(con, equipment_id, sess["company_id"])
        cur = con.execute(
            "INSERT INTO sensor_datasets (company_id, equipment_id, uploaded_by, name,"
            " source_filename, storage_key, sha256_hash, channels, row_count,"
            " time_start, time_end, sample_interval_s, quality_status, quality_score,"
                " quality_detail, created_at) VALUES (?,?,?,?,?,'',?,?,?,?,?,?,'PENDING',NULL,'{}',?)",
            (sess["company_id"], equipment_id, sess["user_id"],
             (name or fname).strip()[:128], fname, digest,
             json.dumps(ingest["channels"]), ingest["row_count"],
             ingest["time_start"], ingest["time_end"], ingest["median_interval_s"],
             utcnow_iso()))
        ds_id = cur.lastrowid
        key = f"{sess['company_id']}/{ds_id}/original.csv"
        con.execute("UPDATE sensor_datasets SET storage_key = ? WHERE id = ?",
                    (key, ds_id))
        root = _root()
        dest_dir = _safe_join(root, str(sess["company_id"]), str(ds_id))
        dest_dir.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, _safe_join(root, key))
        # Normalized readings (long format, batched).
        batch = [(ds_id, ts, ch, v)
                 for ts, vals in ingest["rows"]
                 for ch, v in vals.items() if v is not None]
        con.executemany("INSERT INTO sensor_readings (dataset_id, ts, channel, value)"
                        " VALUES (?,?,?,?)", batch)
        # Quality from first channel (representative signal).
        first = ingest["channels"][0]["name"] if ingest["channels"] else ""
        quality = Q.assess(ingest, first) if first else {"status": "INVALID", "score": 0.0,
                                                        "issues": ["no channels"]}
        con.execute("UPDATE sensor_datasets SET quality_status = ?, quality_score = ?,"
                    " quality_detail = ? WHERE id = ?",
                    (quality["status"], quality["score"],
                     json.dumps({"issues": quality.get("issues", []),
                                 "problems": ingest["problems"],
                                 "dropped_rows": ingest["dropped_rows"],
                                 "invalid_rows": quality.get("invalid_rows", 0),
                                 "missing_values": quality.get("missing_values", 0)}),
                     ds_id))
        con.commit()
        row = con.execute("SELECT * FROM sensor_datasets WHERE id = ?",
                          (ds_id,)).fetchone()
        eq = con.execute("SELECT code FROM equipment WHERE id = ?",
                         (equipment_id,)).fetchone()
    finally:
        con.close()
    log_event("sensor_uploaded",
              {"dataset_id": ds_id, "channels": len(ingest["channels"]),
               "rows": ingest["row_count"], "quality": quality["status"]},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="sensor_dataset", entity_id=ds_id)
    out = _meta(row, eq["code"] if eq else None)
    out["quality"] = {**quality, "problems": ingest["problems"],
                      "dropped_rows": ingest["dropped_rows"]}
    return out


@router.get("")
def list_datasets(sess: dict = Depends(get_current_session),
                  equipment_id: int | None = None):
    con = connect()
    try:
        q = ("SELECT d.*, e.code AS equipment_code FROM sensor_datasets d"
             " LEFT JOIN equipment e ON e.id = d.equipment_id"
             " WHERE d.company_id = ?")
        params: list = [sess["company_id"]]
        if equipment_id is not None:
            q += " AND d.equipment_id = ?"
            params.append(equipment_id)
        q += " ORDER BY d.id DESC"
        rows = con.execute(q, params).fetchall()
    finally:
        con.close()
    return {"datasets": [{**_meta(r, r["equipment_code"])} for r in rows]}


@router.get("/{dataset_id}")
def get_dataset(dataset_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _owned(con, dataset_id, sess["company_id"])
        eq = con.execute("SELECT code FROM equipment WHERE id = ?",
                         (row["equipment_id"],)).fetchone()
    finally:
        con.close()
    return _meta(row, eq["code"] if eq else None)


@router.get("/{dataset_id}/quality")
def dataset_quality(dataset_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _owned(con, dataset_id, sess["company_id"])
        stored = json.loads(row["quality_detail"] or "{}")
        live_rows = con.execute("SELECT COUNT(*) FROM sensor_readings"
                                " WHERE dataset_id = ?", (dataset_id,)).fetchone()[0]
    finally:
        con.close()
    # Stored assessment (from ingest, includes dropped/invalid rows) plus live
    # stored-row counts. Stored invalid rows are excluded from analysis.
    return {"dataset_id": dataset_id, "status": row["quality_status"],
            "score": row["quality_score"],
            "issues": stored.get("issues", []),
            "problems": stored.get("problems", []),
            "dropped_rows": stored.get("dropped_rows", 0),
            "invalid_rows": stored.get("invalid_rows", 0),
            "missing_values": stored.get("missing_values", 0),
            "rows": row["row_count"], "valid_rows": live_rows,
            "sampling_interval_s": row["sample_interval_s"],
            "time_start": row["time_start"], "time_end": row["time_end"],
            "time_span_s": (row["time_end"] - row["time_start"]
                            if row["time_end"] else 0)}


class AnalyzeIn(BaseModel):
    channel: str
    method: str = "rolling_zscore"
    window: int = 60
    threshold: float = 3.0
    gt: float | None = None
    lt: float | None = None
    compare_channel: str | None = None
    event_start: float | None = None
    event_end: float | None = None

    @field_validator("method")
    @classmethod
    def _method(cls, v: str) -> str:
        if v not in _ANOM_METHODS:
            raise ValueError(f"method must be one of {_ANOM_METHODS}")
        return v

    @field_validator("window")
    @classmethod
    def _window(cls, v: int) -> int:
        if not 2 <= v <= 100000:
            raise ValueError("window out of range")
        return v

    @field_validator("threshold")
    @classmethod
    def _threshold(cls, v: float) -> float:
        if not 0.1 <= v <= 20:
            raise ValueError("threshold out of range")
        return v


def _load_rows(dataset_id: int) -> tuple[dict, list]:
    from ..agents.analysis_agents import load_dataset_rows
    return load_dataset_rows(dataset_id)


@router.post("/{dataset_id}/analyze",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def analyze_dataset(dataset_id: int, body: AnalyzeIn, request: Request,
                    sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        row = _owned(con, dataset_id, sess["company_id"])
    finally:
        con.close()
    _, rows = _load_rows(dataset_id)
    names = [c["name"] for c in json.loads(row["channels"])]
    if body.channel not in names:
        raise HTTPException(status_code=422, detail="Unknown channel")
    if body.compare_channel and body.compare_channel not in names:
        raise HTTPException(status_code=422, detail="Unknown compare channel")
    window = None
    if body.event_start is not None or body.event_end is not None:
        if body.event_start is None or body.event_end is None:
            raise HTTPException(status_code=422,
                                detail="Event window needs start and end")
        window = {"start": body.event_start, "end": body.event_end}
    try:
        result = _ANALYZER.analyze(
            rows=rows, channel=body.channel, method=body.method,
            window=body.window, threshold=body.threshold, gt=body.gt, lt=body.lt,
            compare_channel=body.compare_channel, event_window=window)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _record_run(con=None, sess=sess, equipment_id=row["equipment_id"],
                method=f"sensor:{body.method}",
                params={"dataset_id": dataset_id, "channel": body.channel,
                        "window": body.window, "threshold": body.threshold},
                result=result, request=request)
    return {"dataset_id": dataset_id, **result,
            "warnings": _quality_warnings(row)}


def _quality_warnings(row) -> list[str]:
    w = []
    if row["quality_status"] in ("POOR", "INVALID"):
        w.append(f"Dataset quality is {row['quality_status']}; treat results cautiously.")
    elif row["quality_status"] == "WARNING":
        w.append("Dataset has quality warnings; check the quality report.")
    return w


@router.post("/{dataset_id}/trend",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def trend_dataset(dataset_id: int, body: AnalyzeIn, request: Request,
                  sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        row = _owned(con, dataset_id, sess["company_id"])
    finally:
        con.close()
    _, rows = _load_rows(dataset_id)
    if body.channel not in [c["name"] for c in json.loads(row["channels"])]:
        raise HTTPException(status_code=422, detail="Unknown channel")
    tss, vals = A.series_for(rows, body.channel)
    s = get_settings()
    roll = A.rolling(tss, vals, body.window)
    cap = s.CHART_MAX_POINTS * 2
    out = {"dataset_id": dataset_id, "channel": body.channel,
           "trend": A.trend(tss, vals),
           "rolling": {"window": roll["window"],
                       "times": roll["times"][:cap],
                       "rolling_mean": roll["rolling_mean"][:cap],
                       "rolling_std": roll["rolling_std"][:cap]},
           "warnings": _quality_warnings(row)}
    _record_run(con=None, sess=sess, equipment_id=row["equipment_id"],
                method="sensor:trend",
                params={"dataset_id": dataset_id, "channel": body.channel},
                result={"direction": out["trend"]["direction"]}, request=request)
    return out


@router.post("/{dataset_id}/anomalies",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def anomalies_dataset(dataset_id: int, body: AnalyzeIn, request: Request,
                      sess: dict = Depends(get_current_session)):
    _limited(sess)
    return analyze_dataset(dataset_id, body, request, sess)


@router.post("/{dataset_id}/frequency",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def frequency_dataset(dataset_id: int, body: AnalyzeIn, request: Request,
                      sess: dict = Depends(get_current_session)):
    _limited(sess)
    s = get_settings()
    con = connect()
    try:
        row = _owned(con, dataset_id, sess["company_id"])
    finally:
        con.close()
    _, rows = _load_rows(dataset_id)
    if body.channel not in [c["name"] for c in json.loads(row["channels"])]:
        raise HTTPException(status_code=422, detail="Unknown channel")
    tss, vals = A.series_for(rows, body.channel)
    freq = A.fft_analysis(tss, vals, min_samples=s.FFT_MIN_SAMPLES)
    warnings = _quality_warnings(row)
    if freq.get("available") and freq.get("interpolated_points"):
        warnings = warnings + [
            f"{freq['interpolated_points']} missing sample(s) linearly interpolated"
            " for FFT; large gaps would refuse analysis."]
    out = {"dataset_id": dataset_id, "channel": body.channel,
           "frequency": freq, "warnings": warnings}
    _record_run(con=None, sess=sess, equipment_id=row["equipment_id"],
                method="sensor:fft",
                params={"dataset_id": dataset_id, "channel": body.channel},
                result={"available": out["frequency"]["available"]}, request=request)
    return out


class CorrelateIn(BaseModel):
    dataset_id: int
    channel_a: str
    channel_b: str
    window_start: float | None = None
    window_end: float | None = None


@router.post("/correlation",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def correlate_channels(body: CorrelateIn, request: Request,
                       sess: dict = Depends(get_current_session)):
    _limited(sess)
    dataset_id = body.dataset_id
    con = connect()
    try:
        row = _owned(con, dataset_id, sess["company_id"])
    finally:
        con.close()
    _, rows = _load_rows(dataset_id)
    names = [c["name"] for c in json.loads(row["channels"])]
    for ch in (body.channel_a, body.channel_b):
        if ch not in names:
            raise HTTPException(status_code=422, detail="Unknown channel")
    if body.channel_a == body.channel_b:
        raise HTTPException(status_code=422, detail="Channels must differ")
    tss, va = A.series_for(rows, body.channel_a)
    _, vb = A.series_for(rows, body.channel_b)
    if body.window_start is not None and body.window_end is not None:
        mask_a = (tss >= body.window_start) & (tss <= body.window_end)
        # align via shared timestamps
        m1 = {t: v for t, v in zip(tss.tolist(), va.tolist())}
        import numpy as np
        t2, vb_full = A.series_for(rows, body.channel_b)
        m2 = {t: v for t, v in zip(t2.tolist(), vb_full.tolist())}
        common = sorted(t for t in set(m1) & set(m2)
                        if body.window_start <= t <= body.window_end)
        va = np.array([m1[t] for t in common])
        vb = np.array([m2[t] for t in common])
        win = {"start": body.window_start, "end": body.window_end, "n": len(common)}
    else:
        import numpy as np
        m1 = {t: v for t, v in zip(tss.tolist(), va.tolist())}
        t2, vb_full = A.series_for(rows, body.channel_b)
        m2 = {t: v for t, v in zip(t2.tolist(), vb_full.tolist())}
        common = sorted(set(m1) & set(m2))
        va = np.array([m1[t] for t in common])
        vb = np.array([m2[t] for t in common])
        win = {"n": len(common)}
    res = A.pearson(va, vb)
    out = {"dataset_id": dataset_id, "channel_a": body.channel_a,
           "channel_b": body.channel_b, "window": win, **res,
           "warnings": _quality_warnings(row)}
    _record_run(con=None, sess=sess, equipment_id=row["equipment_id"],
                method="sensor:correlation",
                params={"dataset_id": dataset_id, "a": body.channel_a,
                        "b": body.channel_b}, result={"r": res.get("r")},
                request=request)
    return out


@router.get("/{dataset_id}/series")
def dataset_series(dataset_id: int, channel: str,
                   sess: dict = Depends(get_current_session),
                   start: float | None = None, end: float | None = None):
    con = connect()
    try:
        row = _owned(con, dataset_id, sess["company_id"])
    finally:
        con.close()
    if channel not in [c["name"] for c in json.loads(row["channels"])]:
        raise HTTPException(status_code=422, detail="Unknown channel")
    _, rows = _load_rows(dataset_id)
    tss, vals = A.series_for(rows, channel)
    if start is not None:
        mask = tss >= start
        tss, vals = tss[mask], vals[mask]
    if end is not None:
        mask = tss <= end
        tss, vals = tss[mask], vals[mask]
    s = get_settings()
    return {"dataset_id": dataset_id, "channel": channel,
            **A.downsample(tss, vals, s.CHART_MAX_POINTS)}


@router.get("/{dataset_id}/export")
def export_dataset(dataset_id: int, request: Request,
                   sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = _owned(con, dataset_id, sess["company_id"])
    finally:
        con.close()
    _, rows = _load_rows(dataset_id)
    channels = [c["name"] for c in json.loads(row["channels"])]

    def _stream():
        yield "timestamp," + ",".join(channels) + "\n"
        for ts, vals in rows:
            yield f"{ts}," + ",".join(
                "" if vals.get(c) is None else repr(vals.get(c))
                for c in channels) + "\n"

    log_event("sensor_exported", {"dataset_id": dataset_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request),
              entity_type="sensor_dataset", entity_id=dataset_id)
    return StreamingResponse(_stream(), media_type="text/csv",
                             headers={"Content-Disposition":
                                      f'attachment; filename="dataset-{dataset_id}.csv"'})


def _record_run(con, *, sess: dict, equipment_id, method: str,
                params: dict, result: dict, request: Request) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO analysis_runs (company_id, equipment_id, kind, input_ref,"
            " method, params, result_summary, warnings, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sess["company_id"], equipment_id, "sensor",
             json.dumps(params), method, json.dumps(params),
             json.dumps(result)[:4000], json.dumps(["Statistical observation only; "
                                                    "not a failure diagnosis."]),
             sess["user_id"], utcnow_iso()))
        conn.commit()
    finally:
        conn.close()
    log_event(f"sensor_analysis",
              {"method": method, "equipment_id": equipment_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="sensor_dataset",
              entity_id=params.get("dataset_id"))
