"""Multimodal fusion: typed evidence, cross-modal observations, timeline,
snapshots. Every statement is tagged OBSERVATION / INTERPRETATION /
LIMITATION. Interpretations use safety language ("may indicate", "requires
engineering verification") and never diagnose failures or prescribe actions.
"""
import json
import uuid
from datetime import datetime, timezone

EVIDENCE_TYPES = ("DOCUMENT", "SENSOR", "IMAGE", "OCR", "CALCULATION",
                  "USER_INPUT", "SYSTEM_OBSERVATION")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_evidence(*, type: str, source: str, equipment_id=None,
                  description: str, data_ref=None, timestamp=None) -> dict:
    assert type in EVIDENCE_TYPES, f"unknown evidence type {type}"
    return {"id": f"ev_{uuid.uuid4().hex[:12]}", "type": type, "source": source,
            "timestamp": timestamp, "equipment_id": equipment_id,
            "description": description, "data_ref": data_ref or {}}


def observation(text: str) -> dict:
    return {"kind": "OBSERVATION", "text": text}


def interpretation(text: str) -> dict:
    return {"kind": "INTERPRETATION", "text": text}


def limitation(text: str) -> dict:
    return {"kind": "LIMITATION", "text": text}


def correlate(sensor_summaries: list, doc_citations: list,
              image_findings: list) -> list[dict]:
    """Deterministic cross-modal rules. Only relates actually-present
    evidence; each claim carries its kind tag."""
    out: list[dict] = []
    anomalies = [s for s in sensor_summaries
                 if s.get("anomaly_count", 0) > 0]
    if anomalies and doc_citations:
        names = sorted({c.get("filename", "?") for c in doc_citations})
        chans = sorted({s.get("channel", "?") for s in anomalies})
        out.append(observation(
            f"Sensor anomalies present in {', '.join(chans)} while "
            f"{len(doc_citations)} document excerpt(s) "
            f"({', '.join(names)}) were retrieved for the same equipment."))
        out.append(interpretation(
            "The co-occurrence of sensor anomalies and retrieved documentation "
            "may warrant engineering review; it does not by itself establish "
            "a failure mechanism."))
        out.append(limitation(
            "Document excerpts were selected by keyword/semantic similarity, "
            "not by causal analysis."))
    visuals = [v for v in image_findings
               if v.get("annotations") or v.get("ocr_text")]
    if anomalies and visuals:
        out.append(observation(
            f"{len(visuals)} inspection image(s) with visual evidence exist "
            f"alongside sensor anomalies in "
            f"{', '.join(sorted({s.get('channel', '?') for s in anomalies}))}."))
        out.append(interpretation(
            "Combined sensor and visual evidence may indicate a change in "
            "machine behavior. Requires engineering verification."))
        out.append(limitation(
            "Temporal alignment between sensor events and images is by upload "
            "proximity only, not by synchronized clocks."))
    if not out:
        out.append(limitation(
            "The available evidence is insufficient to determine relationships "
            "between modalities."))
    return out


def build_timeline(events: list[dict]) -> list[dict]:
    """events: [{ts (iso|epoch|None), kind, label}]. Sorted, nulls last."""
    def key(e):
        ts = e.get("ts")
        try:
            return (0, float(ts))
        except (TypeError, ValueError):
            return (1, 0.0)
    return sorted(events, key=key)


def build_context(*, company_id: int, equipment: dict | None,
                  question: str, documents: list, citations: list,
                  sensor: list, images: list, observations: list,
                  warnings: list, window: dict | None) -> dict:
    """Bounded multimodal context for reasoning (Stage 5 consumes this)."""
    return {
        "company_id": company_id,
        "equipment": equipment,
        "question": (question or "")[:2000],
        "documents": documents,
        "citations": citations,
        "sensor_summaries": sensor,
        "images": images,
        "observations": observations,
        "warnings": warnings,
        "time_window": window,
        "built_at": now_iso(),
    }


def snapshot_payload(*, equipment_id: int, question: str, config: dict,
                     results: dict) -> dict:
    return {"equipment_id": equipment_id, "question": question,
            "config": config, "results": results,
            "saved_at": now_iso(), "format_version": 1}


def to_jsonable(obj) -> str:
    return json.dumps(obj, default=str)
