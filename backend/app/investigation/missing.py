"""Missing evidence, Next-Best-Evidence ranking, and what-if simulation.

Methodology (documented, no fake Bayesian claims):
- Each hypothesis has expected evidence *slots* from a deterministic catalog
  keyed by equipment-type and hypothesis keywords.
- A slot is filled when linked SUPPORTS/CONTRADICTS evidence matches it
  (explicit metadata slot or keyword match on title+description).
- `what_if(hypothesis, slot, outcome)` recomputes ALL hypothesis scores with
  one hypothetical link added (quality = candidate reliability × 0.8) and
  returns real score deltas + rank changes. This is the calculation behind
  both the NBE "Discriminative Value" and the what-if simulator.
- NBE value(c) = coverage_gain + max over outcomes of separation change,
  ranked by value desc, effort asc, safety asc. All terms are explainable.
"""
import re

PRIORITY_W = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
EFFORT_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
SAFETY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# slot -> attributes. kind maps to candidate kinds for recommendations.
SLOTS = {
    "bearing_temperature": {
        "title": "Bearing temperature history", "kind": "MEASUREMENT",
        "priority": "HIGH", "effort": "LOW", "safety": "LOW",
        "time": "minutes", "reliability": 0.85,
        "keywords": ["temperature", "thermal", "heat", "bearing temp"],
    },
    "lubrication_state": {
        "title": "Lubrication state / history", "kind": "INSPECTION",
        "priority": "HIGH", "effort": "LOW", "safety": "LOW",
        "time": "minutes", "reliability": 0.75,
        "keywords": ["lubricat", "oil", "grease"],
    },
    "shaft_alignment": {
        "title": "Shaft alignment measurement", "kind": "MEASUREMENT",
        "priority": "HIGH", "effort": "MEDIUM", "safety": "MEDIUM",
        "time": "1-2 hours", "reliability": 0.9,
        "keywords": ["align", "laser", "dial indicator"],
    },
    "vibration_trend": {
        "title": "Vibration trend recording", "kind": "SENSOR_READING",
        "priority": "HIGH", "effort": "LOW", "safety": "LOW",
        "time": "minutes", "reliability": 0.9,
        "keywords": ["vibration", "rms", "spectrum", "fft", "accelerometer"],
    },
    "mounting_inspection": {
        "title": "Mounting / foundation inspection", "kind": "INSPECTION",
        "priority": "MEDIUM", "effort": "LOW", "safety": "LOW",
        "time": "30 minutes", "reliability": 0.75,
        "keywords": ["mount", "foundation", "bolt", "loose", "baseplate", "grout"],
    },
    "maintenance_history": {
        "title": "Maintenance / replacement history", "kind": "HISTORY",
        "priority": "MEDIUM", "effort": "LOW", "safety": "LOW",
        "time": "minutes", "reliability": 0.7,
        "keywords": ["maintenance", "history", "replacement", "overhaul", "service record"],
    },
    "acoustic_check": {
        "title": "Acoustic / listening check", "kind": "MEASUREMENT",
        "priority": "MEDIUM", "effort": "LOW", "safety": "LOW",
        "time": "minutes", "reliability": 0.6,
        "keywords": ["acoustic", "noise", "listening", "ultrasound", "stethoscope"],
    },
    "operating_load": {
        "title": "Operating load / process conditions", "kind": "MEASUREMENT",
        "priority": "MEDIUM", "effort": "LOW", "safety": "LOW",
        "time": "minutes", "reliability": 0.7,
        "keywords": ["load", "flow", "pressure", "rpm", "operating point", "process"],
    },
    "calibration_record": {
        "title": "Sensor calibration record", "kind": "DOCUMENT",
        "priority": "MEDIUM", "effort": "LOW", "safety": "LOW",
        "time": "minutes", "reliability": 0.8,
        "keywords": ["calibrat", "certificate", "sensor record"],
    },
    "thermography": {
        "title": "Thermographic survey", "kind": "MEASUREMENT",
        "priority": "MEDIUM", "effort": "MEDIUM", "safety": "LOW",
        "time": "1 hour", "reliability": 0.75,
        "keywords": ["thermo", "infrared", "hotspot", "thermal image"],
    },
    "oil_analysis": {
        "title": "Oil / lubricant analysis", "kind": "TEST",
        "priority": "MEDIUM", "effort": "MEDIUM", "safety": "LOW",
        "time": "days (lab)", "reliability": 0.85,
        "keywords": ["oil analysis", "lubricant sample", "wear debris", "ferrography"],
    },
    "previous_cases": {
        "title": "Previous similar cases", "kind": "HISTORY",
        "priority": "LOW", "effort": "LOW", "safety": "LOW",
        "time": "minutes", "reliability": 0.6,
        "keywords": ["previous case", "history", "past failure", "similar"],
    },
}

# hypothesis keyword -> relevant slots (first match wins; default at end).
HYPOTHESIS_SLOTS = [
    (("bearing", "wear", "degrad", "spall", "brinell"),
     ("bearing_temperature", "lubrication_state", "vibration_trend",
      "maintenance_history", "acoustic_check")),
    (("misalign",),
     ("shaft_alignment", "vibration_trend", "thermography", "operating_load")),
    (("imbalance", "rotor", "unbalance"),
     ("vibration_trend", "operating_load", "mounting_inspection",
      "maintenance_history")),
    (("mount", "loose", "foundation", "soft foot", "baseplate"),
     ("mounting_inspection", "vibration_trend", "operating_load")),
    (("sensor", "instrument", "transducer", "cable", "mounting problem"),
     ("calibration_record", "operating_load", "vibration_trend")),
    (("lubric", "oil", "grease"),
     ("lubrication_state", "oil_analysis", "bearing_temperature")),
    ((), ("vibration_trend", "maintenance_history", "operating_load",
          "previous_cases")),
]

ROTATING_TYPES = ("pump", "compressor", "motor", "fan", "blower", "turbine",
                  "gearbox", "bearing", "rotor", "centrifuge", "mixer")


def slots_for_hypothesis(title: str, description: str,
                         equipment_type: str = "") -> list[str]:
    text = f"{title} {description}".lower()
    for keywords, slots in HYPOTHESIS_SLOTS:
        if not keywords or any(k in text for k in keywords):
            base = list(slots)
            break
    et = (equipment_type or "").lower()
    if any(t in et for t in ROTATING_TYPES) and "vibration_trend" not in base:
        base = ["vibration_trend"] + base
    # Deduplicate, preserve order.
    seen, out = set(), []
    for s in base:
        if s not in seen and s in SLOTS:
            seen.add(s)
            out.append(s)
    return out


def _slot_keywords(slot: str) -> list[str]:
    return SLOTS[slot]["keywords"]


def evidence_slot(evidence: dict) -> str | None:
    """Best-effort slot match for an evidence item (metadata slot wins)."""
    meta = evidence.get("metadata") or {}
    if isinstance(meta, dict) and meta.get("slot") in SLOTS:
        return meta["slot"]
    text = f"{evidence.get('title', '')} {evidence.get('description', '')}".lower()
    for slot in SLOTS:
        if any(k in text for k in _slot_keywords(slot)):
            return slot
    return None


def missing_for_hypothesis(hypothesis: dict, linked_slots: set[str],
                           equipment_type: str = "") -> list[dict]:
    expected = slots_for_hypothesis(hypothesis.get("title", ""),
                                    hypothesis.get("description", ""),
                                    equipment_type)
    out = []
    for slot in expected:
        if slot not in linked_slots:
            info = SLOTS[slot]
            out.append({"slot": slot, "title": info["title"], "kind": info["kind"],
                        "priority": info["priority"], "effort": info["effort"],
                        "safety": info["safety"], "time": info["time"],
                        "reliability": info["reliability"]})
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(out, key=lambda m: (order[m["priority"]], m["title"]))


def _simulate(scores_fn, scored: list[dict], target_hid: int, slot: str,
              outcome: str, reliability: float):
    """Recompute all scores with one hypothetical link. Returns
    {deltas: {hid: new-old}, ranks_before, ranks_after}."""
    from .scoring import rank_hypotheses
    before = {h["hypothesis_id"]: h["support_score"] for h in scored}
    before_rank = {h["hypothesis_id"]: h.get("rank", 0) for h in scored}
    hypo_links: dict[int, list[dict]] = {}
    for h in scored:
        hypo_links[h["hypothesis_id"]] = [
            {"relation": l["relation"], "quality": l["quality"],
             "evidence_id": l.get("evidence_id"), "slot": l.get("slot")}
            for l in h.get("_links", [])]
    hypo_links.setdefault(target_hid, []).append({
        "relation": "SUPPORTS" if outcome == "positive" else "CONTRADICTS",
        "quality": max(0.0, min(1.0, reliability * 0.8)),
        "evidence_id": f"hypothetical:{slot}:{outcome}",
        "slot": slot,
    })
    # Reuse the scoring formula via scores_fn(hypothesis_id) -> scored dict.
    new_scored = scores_fn(hypo_links)
    ranked = rank_hypotheses(new_scored)
    after_map = {h["hypothesis_id"]: h for h in ranked}
    before_comp = {h["hypothesis_id"]: h.get("completeness", 0.0) for h in scored}
    return {
        "deltas": {hid: round(after_map[hid]["support_score"] - before.get(hid, 0.0), 1)
                   for hid in before},
        "completeness": {hid: round(
            after_map[hid].get("completeness", 0.0) - before_comp.get(hid, 0.0), 1)
            for hid in before},
        "ranks_before": before_rank,
        "ranks_after": {h["hypothesis_id"]: h["rank"] for h in ranked},
        "scored": ranked,
    }


def rank_candidates(*, scored: list[dict], scores_fn, missing_by_hyp: dict,
                    open_conflicts: int = 0) -> list[dict]:
    """Rank NBE candidates. value = coverage gain + best separation change
    across both outcomes; ties broken by effort, then safety."""
    cands: dict[str, dict] = {}
    for h in scored:
        hid = h["hypothesis_id"]
        for m in missing_by_hyp.get(hid, []):
            slot = m["slot"]
            if slot not in cands:
                info = SLOTS[slot]
                cands[slot] = {
                    "slot": slot, "title": info["title"], "kind": info["kind"],
                    "effort": info["effort"], "safety": info["safety"],
                    "time": info["time"], "reliability": info["reliability"],
                    "informs": [], "priority": m["priority"],
                }
            if h["title"] not in cands[slot]["informs"]:
                cands[slot]["informs"].append(h["title"])
            if PRIORITY_W[m["priority"]] > PRIORITY_W[cands[slot]["priority"]]:
                cands[slot]["priority"] = m["priority"]
    if open_conflicts:
        cands.setdefault("repeat_measurement", {
            "slot": "repeat_measurement",
            "title": "Repeat contested measurement under operating load",
            "kind": "MEASUREMENT", "effort": "LOW", "safety": "LOW",
            "time": "30 minutes", "reliability": 0.85,
            "informs": [h["title"] for h in scored], "priority": "HIGH",
        })
    ranked = []
    for slot, c in cands.items():
        best_change, best_outcome, previews = 0.0, None, {}
        best_coverage, best_comp = 0, 0.0
        for hid in [h["hypothesis_id"] for h in scored
                    if h["title"] in c["informs"]][:4]:
            # Coverage: +1 when this slot is genuinely unfilled for the hypothesis.
            missing_slots = {m["slot"] for m in missing_by_hyp.get(hid, [])}
            cov = 1 if slot in missing_slots else 0
            for outcome in ("positive", "negative"):
                try:
                    sim = _simulate(scores_fn, scored, hid, slot, outcome,
                                    c["reliability"])
                except Exception:
                    continue
                gaps = sorted((v["support_score"] for v in sim["scored"]),
                              reverse=True)
                sep = round(gaps[0] - gaps[1], 1) if len(gaps) > 1 else 0.0
                change = abs(sep - _current_separation(scored))
                comp = sim["completeness"].get(hid, 0.0)
                previews[f"{hid}:{outcome}"] = {
                    "deltas": sim["deltas"], "ranks_after": sim["ranks_after"],
                    "separation": sep, "completeness_gain": comp}
                if change > best_change:
                    best_change, best_outcome = change, outcome
                best_coverage = max(best_coverage, cov)
                best_comp = max(best_comp, comp)
        coverage = best_coverage
        value = round(coverage * 10.0 + best_change, 1)
        top = sorted(scored, key=lambda h: -h["support_score"])[:2]
        names = " vs ".join(h["title"] for h in top)
        ranked.append({
            **c,
            "discriminative_value": round(best_change, 1),
            "expected_uncertainty_reduction": (
                "HIGH" if best_change >= 10 else
                "MEDIUM" if best_change >= 4 else "LOW"),
            "expected_value": ("HIGH" if value >= 25 else
                               "MEDIUM" if value >= 12 else "LOW"),
            "value_score": value,
            "best_outcome": best_outcome,
            "previews": previews,
            "rationale": {
                "why": (f"Fills {c['title'].lower()} for "
                        f"{', '.join(c['informs'])}"
                        + (" (currently unfilled slot)." if coverage else ".")),
                "distinguishes": names,
                "uncertainty": (f"Best simulated separation change "
                                f"{round(best_change, 1)} points"
                                + (f" if outcome is {best_outcome}."
                                   if best_outcome else ".")),
                "if_positive": ("Support rises for the informed hypotheses; "
                                "ranking may change as shown in previews."),
                "if_negative": ("Contradiction mass rises instead; the leading "
                                "hypothesis may weaken — equally informative."),
            },
        })
    ranked.sort(key=lambda c: (-c["value_score"],
                               EFFORT_ORDER[c["effort"]],
                               SAFETY_ORDER[c["safety"]], c["title"]))
    for i, c in enumerate(ranked, start=1):
        c["rank"] = i
    return ranked


def _current_separation(scored: list[dict]) -> float:
    gaps = sorted((h["support_score"] for h in scored), reverse=True)
    return round(gaps[0] - gaps[1], 1) if len(gaps) > 1 else 0.0
