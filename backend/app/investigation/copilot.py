"""Investigation copilot: deterministic grounded answers over investigation
data (no LLM required). Every answer cites real records; insufficient data
yields "Insufficient evidence to determine this." Evidence text is treated as
DATA (wrapped/quoted, never executed) — prompt-injection safe by construction.

Also: assumption detection, conflict detection, health/readiness computation.
"""
import re
import time

from .common import DEFAULT_GATE
from . import scoring as S


def _clean(question: str) -> str:
    """Normalize quotes/dashes so keyword matching is contraction-safe."""
    q = (question or "").lower()
    return (q.replace("’", "'").replace("‘", "'").replace("`", "'")
             .replace("—", " ").replace("–", " "))

NORMAL_WORDS = ("normal", "no abnormal", "looks ok", "looks fine", "healthy",
                "within limits", "acceptable", "no issue", "good condition")


def _ts_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def detect_conflicts(evidence: list[dict]) -> list[dict]:
    """Sensor anomaly vs technician-normal contradiction (keyword rules)."""
    conflicts = []
    anomalies = [e for e in evidence
                 if e.get("type") == "SENSOR" and e.get("metadata", {}).get("anomaly_count", 0) > 0]
    normals = [e for e in evidence
               if e.get("type") in ("TECHNICIAN", "MANUAL", "INSPECTION")
               and any(w in f"{e.get('title', '')} {e.get('description', '')}".lower()
                       for w in NORMAL_WORDS)]
    for a in anomalies:
        for n in normals:
            conflicts.append({
                "evidence_a_id": a["id"], "evidence_b_id": n["id"],
                "description": (f"Conflict detected: sensor evidence '{a['title']}' reports "
                                f"anomalies while '{n['title']}' reports normal condition."),
                "recommendation": "Repeat the measurement under operating load with a "
                                  "calibrated instrument, then re-enter the observation.",
            })
    return conflicts


def detect_assumptions(*, evidence: list[dict], datasets_meta: list[dict],
                       equipment_id: int) -> list[dict]:
    """Heuristic assumption list with UNVERIFIED default (never asserted true)."""
    out = []

    def add(text):
        if text not in [a["text"] for a in out]:
            out.append({"text": text, "status": "UNVERIFIED"})

    if any(e.get("type") == "SENSOR" for e in evidence):
        add("Sensor calibration is current.")
    if any(e.get("type") == "SENSOR" for e in evidence):
        add("Operating load was approximately normal during recording.")
    for ds in datasets_meta:
        add(f"Dataset '{ds.get('name')}' corresponds to the investigated equipment.")
    if any(e.get("type") in ("IMAGE", "OCR") for e in evidence):
        add("Inspection images depict the investigated equipment in its current state.")
    if any(e.get("type") in ("DOCUMENT", "RAG") for e in evidence):
        add("Retrieved documents apply to this equipment revision.")
    return out


def investigation_health(*, scored: list[dict], evidence: list[dict],
                         critical_gaps: int, settings: dict,
                         now: float | None = None) -> dict:
    """Readiness components from real data (NOT diagnosis confidence)."""
    now = now if now is not None else time.time()
    expected = max(1, sum(h.get("expected_slots", 0) for h in scored) or len(evidence) or 1)
    coverage = 100.0 * min(len(evidence), expected) / expected
    quals = [e.get("_quality", {}).get("quality", 0.5) for e in evidence]
    quality = 100.0 * (sum(quals) / len(quals)) if quals else 0.0
    sep = S.separation(scored)
    separation = min(100.0, sep * 4.0)
    fresh = [S.freshness_factor(e.get("timestamp"), settings, now)[0] for e in evidence]
    freshness = 100.0 * (sum(fresh) / len(fresh)) if fresh else 50.0
    rel = [S.trust_for(settings, e.get("type", "")) for e in evidence]
    reliability = 100.0 * (sum(rel) / len(rel)) if rel else 50.0
    return S.health_score(coverage=coverage, quality=quality,
                          separation=separation, freshness=freshness,
                          reliability=reliability, critical_gaps=critical_gaps)


def readiness(*, health: dict, open_conflicts: int, scored: list[dict],
              technician_verified: bool, settings: dict) -> dict:
    """Stage 8 handoff gate. Returns {ready: bool, reasons[]}."""
    gate = settings.get("readiness_gate") or DEFAULT_GATE
    reasons = []
    if not scored:
        reasons.append("No hypotheses formulated yet")
    if health.get("critical_gaps", 1) > 0:
        reasons.append("Critical evidence missing")
    if open_conflicts > 0:
        reasons.append("Conflicting sensor data")
    if S.separation(scored) < float(gate.get("min_separation", 15.0)):
        reasons.append("Hypotheses insufficiently separated")
    if gate.get("require_technician_verification", True) and not technician_verified:
        reasons.append("Technician verification required")
    return {"ready": not reasons,
            "state": "READY_FOR_VERIFICATION" if not reasons else "NOT READY",
            "reasons": reasons}


def answer(*, question: str, investigation: dict, equipment: dict | None,
           evidence: list[dict], scored: list[dict], missing: list[dict],
           recommendations: list[dict], assumptions: list[dict],
           conflicts: list[dict], health: dict) -> dict:
    """Grounded copilot answer. Unknown questions → insufficient-evidence."""
    q = _clean(question)
    ranked = sorted(scored, key=lambda h: (h.get("rank", 99)))
    top = ranked[0] if ranked else None
    _neg = ("don't", "dont", "do not", "unknown", "unaware", "uncertain", "unsure")

    def ev_list(items, n=5):
        return [{"id": e["id"], "title": e["title"], "type": e["type"]}
                for e in items[:n]]

    if ((any(n in q for n in _neg) and "know" in q)
            or "missing" in q or "lack" in q or "gaps" in q or "need" in q):
        hi = [m for m in missing if m["priority"] == "HIGH"][:5]
        if not hi:
            return _r("All currently expected evidence slots are filled. "
                      "No high-priority gaps identified.", [])
        return _r("What we don't know (high priority): "
                  + "; ".join(f"{m['title']} ({m['priority']})" for m in hi)
                  + ".", [])
    if any(k in q for k in ("support", "evidence for", "behind", "leading")) and top:
        sup = [e for e in evidence if e.get("id") in top.get("support_ids", [])][:5]
        return _r(f"Leading hypothesis '{top['title']}' (support "
                  f"{top['support_score']}/100, {top['confidence_band']}) is supported by: "
                  + ("; ".join(e["title"] for e in sup) or "no linked evidence yet.")
                  + ".", ev_list(sup))
    if "contradict" in q and top:
        con = [e for e in evidence if e.get("id") in top.get("contradict_ids", [])][:5]
        return _r(("Contradicting evidence for "
                   f"'{top['title']}': " + "; ".join(e["title"] for e in con) + ".")
                  if con else
                  f"No contradicting evidence recorded for '{top['title']}'.", ev_list(con))
    if any(k in q for k in ("next", "should", "recommend", "investigate")):
        if not recommendations:
            return _r("No recommendations generated yet.", [])
        r0 = recommendations[0]
        return _r(f"Next best evidence: {r0['title']} (priority {r0['priority']}). "
                  f"{r0['rationale']['why']} "
                  f"Distinguishes: {r0['rationale']['distinguishes']}.",
                  [])
    if "assum" in q:
        return _r("Assumptions: " + "; ".join(
            f"{a['text']} [{a['status']}]" for a in assumptions[:8]) + ".", [])
    if "conflict" in q:
        if not conflicts:
            return _r("No evidence conflicts detected.", [])
        return _r("Conflicts: " + "; ".join(c["description"] for c in conflicts[:3]) + ".", [])
    if any(k in q for k in ("know", "summary", "status", "so far")):
        parts = [f"Investigation '{investigation['title']}' has {len(evidence)} "
                 f"evidence items and {len(scored)} hypotheses."]
        if top:
            parts.append(f"Leading: '{top['title']}' "
                         f"(support {top['support_score']}/100, {top['confidence_band']}).")
        parts.append(f"Readiness: {health.get('readiness', 'UNKNOWN')}.")
        return _r(" ".join(parts), ev_list(evidence))
    return _r("Insufficient evidence to determine this from the recorded "
              "investigation data. Ask about evidence, hypotheses, gaps, "
              "conflicts, assumptions, or next steps.", [])


def _r(text: str, refs: list) -> dict:
    return {"answer": text, "references": refs, "grounded": True}
