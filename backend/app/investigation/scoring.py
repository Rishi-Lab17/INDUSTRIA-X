"""Transparent evidence + hypothesis scoring.

Evidence Quality Q = reliability × confidence × freshness × source_quality,
each factor in [0,1]. This is a deterministic heuristic, NOT a calibrated
probability — the UI must label it "Evidence Quality", never "probability".

Hypothesis scores:
  support_score       = 100 × S / (S + C)          (0 when no linked evidence)
  contradiction_score = 100 × C / (S + C)
  completeness        = 100 × linked_slots / expected_slots
  confidence_band     = Low | Medium | Medium-High | High, from support minus
                        half the contradiction, gated by completeness.

where S/C are quality-weighted sums over SUPPORTS/CONTRADICTS links.
"Evidence Support Score" terminology is used throughout; hypothesis
probability is never claimed.
"""
import math
import time

from .common import DEFAULT_FRESHNESS, trust_for


def freshness_factor(timestamp: str | float | None, settings: dict,
                     now: float | None = None) -> tuple[float, str]:
    """Returns (factor 0..1, band). Missing timestamp → (0.5, Unknown)."""
    if timestamp is None:
        return 0.5, "Unknown"
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return 0.5, "Unknown"
    now = now if now is not None else time.time()
    age = max(0.0, now - ts)
    policy = settings.get("freshness_policy") or DEFAULT_FRESHNESS
    for max_age, band in policy:
        try:
            if age <= float(max_age):
                factor = {"Fresh": 1.0, "Recent": 0.85, "Aging": 0.65,
                          "Stale": 0.4, "Unknown": 0.5}.get(band, 0.5)
                return factor, band
        except (TypeError, ValueError):
            continue
    return 0.4, "Stale"


def clamp01(x: float) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.5


def evidence_quality(evidence: dict, settings: dict,
                     now: float | None = None) -> dict:
    """evidence: row dict with reliability/confidence/timestamp/type keys."""
    reliability = evidence.get("reliability")
    reliability = clamp01(reliability) if reliability is not None else 0.7
    confidence = evidence.get("confidence")
    confidence = clamp01(confidence) if confidence is not None else 0.7
    fresh, band = freshness_factor(evidence.get("timestamp"), settings, now)
    source_quality = clamp01(trust_for(settings, evidence.get("type", "")))
    quality = round(reliability * confidence * fresh * source_quality, 4)
    return {"reliability": reliability, "confidence": confidence,
            "freshness": fresh, "freshness_band": band,
            "source_quality": source_quality, "quality": quality}


def score_hypothesis(links: list[dict], expected_slots: int,
                     settings: dict | None = None) -> dict:
    """links: [{relation, quality}]. expected_slots from missing-evidence
    engine (completed slots + missing slots). Pure function — also used by
    what-if simulation with hypothetical links."""
    settings = settings or {}
    s = sum(l["quality"] for l in links if l["relation"] == "SUPPORTS")
    c = sum(l["quality"] for l in links if l["relation"] == "CONTRADICTS")
    total = s + c
    support = round(100.0 * s / total, 1) if total > 0 else 0.0
    contra = round(100.0 * c / total, 1) if total > 0 else 0.0
    linked_slots = len({l.get("slot", l.get("evidence_id")) for l in links})
    completeness = (round(100.0 * min(linked_slots, expected_slots) / expected_slots, 1)
                    if expected_slots > 0 else (100.0 if links else 0.0))
    adjusted = support - 0.5 * contra
    if not links:
        band = "Low"
    elif completeness < 40:
        band = "Low"
    elif adjusted >= 75 and completeness >= 70:
        band = "High"
    elif adjusted >= 60:
        band = "Medium-High"
    elif adjusted >= 40:
        band = "Medium"
    else:
        band = "Low"
    return {"support_score": support, "contradiction_score": contra,
            "completeness": completeness, "confidence_band": band,
            "support_mass": round(s, 4), "contradiction_mass": round(c, 4)}


def rank_hypotheses(scored: list[dict]) -> list[dict]:
    """Deterministic rank: support desc, contradiction asc, id asc."""
    ordered = sorted(scored,
                     key=lambda h: (-h["support_score"], h["contradiction_score"],
                                    h["hypothesis_id"]))
    for i, h in enumerate(ordered, start=1):
        h["rank"] = i
    return ordered


def separation(scored: list[dict]) -> float:
    """Gap between top-two support scores (0 when <2 scored hypotheses)."""
    if len(scored) < 2:
        return 0.0
    ordered = sorted((h["support_score"] for h in scored), reverse=True)
    return round(ordered[0] - ordered[1], 1)


def independence_factor(evidence_items: list[dict]) -> float:
    """Discount mass when many links share one source (0.5..1.0 multiplier).
    Documented heuristic against double-counting a single origin."""
    if not evidence_items:
        return 1.0
    origins: dict[str, int] = {}
    for e in evidence_items:
        key = f"{e.get('type')}:{e.get('source') or e.get('id')}"
        origins[key] = origins.get(key, 0) + 1
    worst = max(origins.values())
    total = len(evidence_items)
    if total <= 1:
        return 1.0
    return round(1.0 - 0.5 * (worst - 1) / total, 4)


def health_score(*, coverage: float, quality: float, separation_v: float,
                 freshness: float, reliability: float,
                 critical_gaps: int) -> dict:
    """Investigation readiness (NOT diagnosis confidence). All inputs 0..100
    except critical_gaps (count)."""
    def c(x):
        return max(0.0, min(100.0, float(x)))
    parts = {"coverage": c(coverage), "quality": c(quality),
             "separation": c(separation_v), "freshness": c(freshness),
             "reliability": c(reliability)}
    overall = round(sum(parts.values()) / len(parts)
                    - min(30.0, 10.0 * max(0, critical_gaps)), 1)
    overall = max(0.0, overall)
    readiness = ("HIGH" if overall >= 75 and critical_gaps == 0
                 else "MEDIUM" if overall >= 45 else "LOW")
    return {**{k: round(v, 1) for k, v in parts.items()},
            "critical_gaps": critical_gaps, "overall": overall,
            "readiness": readiness}
