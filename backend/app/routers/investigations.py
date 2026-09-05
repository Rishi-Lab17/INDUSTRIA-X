"""Multimodal investigations: equipment + documents/RAG + sensor + vision
fused into one evidence-grounded context with snapshots.

RBAC: create/run/snapshot = ADMIN+ENGINEER; view = all roles.
AI interpretation only when a model is actually available (Stage 5
orchestrator); otherwise interpretation is null with a clear limitation.
Safety language is mandatory: observations, never diagnoses.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from ..agents.analysis_agents import DataAnalysisAgent, load_dataset_rows
from ..audit import log_event
from ..core.deps import get_current_session, require_roles
from ..core.rate_limit import allow
from ..core.security import utcnow_iso
from ..db import connect
from ..multimodal import fusion
from ..multimodal import sensor_analysis as A
from ..rag.retrieval import hybrid_search

router = APIRouter(prefix="/api/investigations", tags=["investigations"])
_SENSOR_AGENT = DataAnalysisAgent()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _equipment_owned(con, equipment_id: int, company_id: int):
    row = con.execute("SELECT * FROM equipment WHERE id = ? AND company_id = ?"
                      " AND is_active = 1", (equipment_id, company_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return dict(row)


def _limited(sess: dict) -> None:
    ok, retry = allow(f"mm:{sess['user_id']}", 30, 60)
    if not ok:
        raise HTTPException(status_code=429, detail="Analysis rate limit reached.",
                            headers={"Retry-After": str(retry)})


class MultimodalIn(BaseModel):
    equipment_id: int
    question: str
    document_ids: list[int] = []
    dataset_ids: list[int] = []
    asset_ids: list[int] = []
    window_start: float | None = None
    window_end: float | None = None
    ai_session_id: int | None = None

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Question must not be empty")
        return v.strip()[:2000]

    @field_validator("document_ids", "dataset_ids", "asset_ids")
    @classmethod
    def _ids(cls, v: list[int]) -> list[int]:
        if len(v) > 20:
            raise ValueError("Too many references (max 20 each)")
        if any(not isinstance(i, int) or i <= 0 for i in v):
            raise ValueError("Invalid reference id")
        return v


def _owned_ids(con, table: str, ids: list[int], company_id: int,
               id_col: str = "id") -> list[dict]:
    out = []
    for i in ids:
        row = con.execute(f"SELECT * FROM {table} WHERE {id_col} = ? AND company_id = ?",
                          (i, company_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Resource not found: {table}/{i}")
        out.append(dict(row))
    return out


@router.post("/multimodal",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def run_multimodal(body: MultimodalIn, request: Request,
                   sess: dict = Depends(get_current_session)):
    _limited(sess)
    company_id = sess["company_id"]
    con = connect()
    try:
        equipment = _equipment_owned(con, body.equipment_id, company_id)
        docs = _owned_ids(con, "documents", body.document_ids, company_id)
        for d in docs:
            if d["equipment_id"] not in (None, body.equipment_id):
                raise HTTPException(status_code=422, detail=(
                    f"Document {d['id']} is linked to different equipment"))
        datasets = _owned_ids(con, "sensor_datasets", body.dataset_ids, company_id)
        for ds in datasets:
            if ds["equipment_id"] != body.equipment_id:
                raise HTTPException(status_code=422, detail=(
                    f"Dataset {ds['id']} belongs to different equipment"))
        assets = _owned_ids(con, "vision_assets", body.asset_ids, company_id)
        for a in assets:
            if a["equipment_id"] != body.equipment_id:
                raise HTTPException(status_code=422, detail=(
                    f"Image {a['id']} belongs to different equipment"))
    finally:
        con.close()

    evidence: list[dict] = []
    warnings: list[str] = []
    timeline: list[dict] = []
    sensor_summaries: list[dict] = []
    image_findings: list[dict] = []

    # Documents → Stage 4 RAG citations (company + equipment scoped).
    rag_cites: list[dict] = []
    if docs or True:
        rag = hybrid_search(company_id=company_id, query=body.question,
                            equipment_id=body.equipment_id, top_k=6)
        for c in rag.get("citations", []):
            rag_cites.append(c)
            evidence.append(fusion.make_evidence(
                type="DOCUMENT", source=c["filename"], equipment_id=body.equipment_id,
                description=f"{c['filename']} v{c['document_version']}"
                            + (f" p.{c['page']}" if c.get("page") else ""),
                data_ref={"document_id": c["document_id"],
                          "chunk_id": c["chunk_id"],
                          "score": c["combined_score"]}))
            timeline.append({"ts": None, "kind": "rag",
                             "label": f"RAG evidence: {c['filename']}"})
        if rag.get("status") != "OK":
            warnings.append("RAG returned insufficient evidence for this question.")

    # Sensors → deterministic analysis per dataset (first channel + anomalies).
    for ds in datasets:
        _, rows = load_dataset_rows(ds["id"])
        channels = json.loads(ds["channels"])
        if not channels:
            warnings.append(f"Dataset {ds['id']} has no channels; skipped.")
            continue
        ch = channels[0]["name"]
        res = _SENSOR_AGENT.analyze(rows=rows, channel=ch)
        summary = {"dataset_id": ds["id"], "channel": ch,
                   "statistics": res.get("statistics", {}),
                   "trend": res.get("trend", {}).get("direction"),
                   "anomaly_count": res.get("anomalies", {}).get("count", 0)}
        sensor_summaries.append(summary)
        evidence.append(fusion.make_evidence(
            type="SENSOR", source=f"dataset:{ds['id']}:{ch}",
            equipment_id=body.equipment_id,
            description=f"{ch}: n={summary['statistics'].get('n', 0)}, "
                        f"trend={summary['trend']}, "
                        f"anomalies={summary['anomaly_count']}",
            data_ref={"dataset_id": ds["id"], "channel": ch}))
        for e in res.get("anomalies", {}).get("events", [])[:50]:
            timeline.append({"ts": e["ts"], "kind": "sensor_anomaly",
                             "label": f"Sensor anomaly {ch}={e['value']}"})
        timeline.append({"ts": None, "kind": "analysis",
                         "label": f"Sensor analysis completed ({ch})"})

    # Images → metadata + OCR + annotations as visual evidence.
    for a in assets:
        try:
            qd = json.loads(a.get("quality_detail") or "{}")
        except (ValueError, TypeError):
            qd = {}
        finding = {"asset_id": a["id"], "filename": a["filename"],
                   "quality": a["quality_status"],
                   "ocr_text": a.get("ocr_text") or "",
                   "annotations": _asset_annotations(a["id"], company_id)}
        image_findings.append(finding)
        evidence.append(fusion.make_evidence(
            type="IMAGE", source=a["filename"], equipment_id=body.equipment_id,
            description=f"{a['filename']} ({a['width']}x{a['height']}, "
                        f"quality {a['quality_status']})",
            data_ref={"asset_id": a["id"]}))
        if finding["ocr_text"]:
            evidence.append(fusion.make_evidence(
                type="OCR", source=a["filename"], equipment_id=body.equipment_id,
                description=f"OCR text from {a['filename']}",
                data_ref={"asset_id": a["id"]}))
        for ann in finding["annotations"]:
            evidence.append(fusion.make_evidence(
                type="USER_INPUT", source=a["filename"],
                equipment_id=body.equipment_id,
                description=f"Marked region '{ann['label']}': {ann.get('note', '')}",
                data_ref={"asset_id": a["id"], "annotation_id": ann["id"]}))
        timeline.append({"ts": None, "kind": "image",
                         "label": f"Image evidence: {a['filename']}"})
        if a["quality_status"] == "POOR":
            warnings.append(f"Image {a['filename']} quality is POOR; visual "
                            f"reasoning refused for it.")

    observations = fusion.correlate(sensor_summaries, rag_cites, image_findings)
    window = None
    if body.window_start is not None or body.window_end is not None:
        if body.window_start is None or body.window_end is None:
            raise HTTPException(status_code=422, detail="Time window needs start and end")
        window = {"start": body.window_start, "end": body.window_end}
    context = fusion.build_context(
        company_id=company_id, equipment={k: equipment[k] for k in
                                          ("id", "code", "name", "type", "criticality",
                                           "status") if k in equipment},
        question=body.question, documents=[{"id": d["id"], "filename": d["original_filename"],
                                            "version": d["version"]} for d in docs],
        citations=rag_cites, sensor=sensor_summaries, images=image_findings,
        observations=observations, warnings=warnings, window=window)

    # Optional AI interpretation: only via Stage 5 orchestrator, only when a
    # model is actually available. Never faked.
    interpretation = None
    ai_run_id = None
    if body.ai_session_id is not None:
        interpretation, ai_run_id = _maybe_interpret(
            sess, body.ai_session_id, body.question, context, request)

    result = {"equipment": {"id": equipment["id"], "code": equipment["code"],
                            "name": equipment["name"]},
              "question": body.question,
              "evidence": evidence,
              "observations": observations,
              "timeline": fusion.build_timeline(timeline),
              "warnings": warnings,
              "context_chars": len(json.dumps(context, default=str)),
              "interpretation": interpretation,
              "ai_run_id": ai_run_id}
    _record(sess, body.equipment_id, "multimodal:investigation",
            {"equipment_id": body.equipment_id,
             "documents": body.document_ids, "datasets": body.dataset_ids,
             "assets": body.asset_ids},
            {"evidence_count": len(evidence), "ai_run_id": ai_run_id}, request)
    return result


def _asset_annotations(asset_id: int, company_id: int) -> list[dict]:
    con = connect()
    try:
        rows = con.execute("SELECT * FROM vision_annotations WHERE asset_id = ?"
                           " AND company_id = ? ORDER BY id",
                           (asset_id, company_id)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _maybe_interpret(sess: dict, ai_session_id: int, question: str,
                     context: dict, request: Request):
    from ..agents import orchestrator
    from ..ai.registry import cached_health
    con = connect()
    try:
        own = con.execute("SELECT * FROM ai_sessions WHERE id = ? AND company_id = ?",
                          (ai_session_id, sess["company_id"])).fetchone()
    finally:
        con.close()
    if own is None:
        raise HTTPException(status_code=404, detail="AI session not found")
    if cached_health().get("status") != "ONLINE":
        return ({"status": "UNAVAILABLE",
                 "limitation": "MODEL UNAVAILABLE: no local AI runtime connected; "
                               "deterministic evidence above stands on its own."}, None)
    res = orchestrator.execute(
        sess={**sess, "equipment_id": context["equipment"]["id"]},
        session_id=ai_session_id,
        user_message=("Multimodal investigation evidence follows. Summarize what is "
                      "OBSERVED vs INFERRED and list limitations.\n\nQuestion: "
                      + question + "\n\nEvidence context:\n"
                      + json.dumps(context, default=str)[:8000]),
        task_type="document_qa", prompt_template="rag_answer")
    return ({"status": res["status"], "answer": res.get("answer", ""),
             "citations": res.get("citations", []),
             "limitation": "AI interpretation is advisory only; verify before acting."},
            res.get("run_id"))


@router.get("/{investigation_id}")
def get_investigation(investigation_id: int,
                      sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        row = con.execute("SELECT * FROM multimodal_investigations WHERE id = ?"
                          " AND company_id = ?", (investigation_id, sess["company_id"])).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return {"id": row["id"], "equipment_id": row["equipment_id"],
            "question": row["question"], "config": json.loads(row["config"]),
            "results": json.loads(row["results"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


@router.get("")
def list_investigations(sess: dict = Depends(get_current_session),
                        equipment_id: int | None = None):
    con = connect()
    try:
        q = ("SELECT id, equipment_id, question, created_at, updated_at"
             " FROM multimodal_investigations WHERE company_id = ?")
        params: list = [sess["company_id"]]
        if equipment_id is not None:
            q += " AND equipment_id = ?"
            params.append(equipment_id)
        q += " ORDER BY id DESC"
        rows = con.execute(q, params).fetchall()
    finally:
        con.close()
    return {"investigations": [dict(r) for r in rows]}


class SnapshotIn(BaseModel):
    investigation_id: int | None = None
    equipment_id: int | None = None
    question: str = ""
    config: dict = {}
    results: dict = {}

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        return v.strip()[:2000]


@router.post("/snapshot", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def save_snapshot(body: SnapshotIn, request: Request,
                  sess: dict = Depends(get_current_session)):
    equipment_id = body.equipment_id
    if body.investigation_id is not None:
        con = connect()
        try:
            row = con.execute("SELECT * FROM multimodal_investigations WHERE id = ?"
                              " AND company_id = ?",
                              (body.investigation_id, sess["company_id"])).fetchone()
        finally:
            con.close()
        if row is None:
            raise HTTPException(status_code=404, detail="Investigation not found")
        equipment_id = row["equipment_id"]
    if equipment_id is None:
        raise HTTPException(status_code=422, detail="equipment_id is required")
    con = connect()
    try:
        eq = con.execute("SELECT id FROM equipment WHERE id = ? AND company_id = ?",
                         (equipment_id, sess["company_id"])).fetchone()
        if eq is None:
            raise HTTPException(status_code=404, detail="Equipment not found")
        payload = fusion.snapshot_payload(equipment_id=equipment_id,
                                          question=body.question,
                                          config=body.config, results=body.results)
        cur = con.execute(
            "INSERT INTO multimodal_investigations (company_id, equipment_id, question,"
            " config, results, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (sess["company_id"], equipment_id, body.question,
             fusion.to_jsonable(body.config), fusion.to_jsonable(payload),
             sess["user_id"], utcnow_iso(), utcnow_iso()))
        inv_id = cur.lastrowid
        con.commit()
    finally:
        con.close()
    log_event("investigation_snapshot",
              {"investigation_id": inv_id, "equipment_id": equipment_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request), entity_type="investigation", entity_id=inv_id)
    return {"investigation_id": inv_id, "message": "Snapshot saved"}


def _record(sess: dict, equipment_id, method: str, params: dict,
            result: dict, request: Request) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO analysis_runs (company_id, equipment_id, kind, input_ref,"
            " method, params, result_summary, warnings, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sess["company_id"], equipment_id, "multimodal",
             json.dumps(params), method, json.dumps(params),
             json.dumps(result)[:4000],
             json.dumps(["Observations only; no failure diagnosis."]),
             sess["user_id"], utcnow_iso()))
        conn.commit()
    finally:
        conn.close()
    log_event("sensor_analysis" if method.startswith("sensor") else "multimodal_analysis",
              {"method": method, "equipment_id": equipment_id},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_client_ip(request))
