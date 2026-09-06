"""Historical case similarity over resolved investigations.

Deterministic structured similarity (0..100, labelled "similarity", never a
probability):
  equipment type match ............ 30
  category match .................. 25
  problem-statement token Jaccard . 25
  evidence-title token overlap .... 20
Only RESOLVED/CLOSED cases of the same company. Below threshold 40 the UI
shows "No sufficiently similar historical cases found."
"""
import re

STOP = frozenset(
    "a an the and or of to in on for with what which pump has have had is are was"
    " were be been this that these those from into about pump-204 abnormal".split())

SIMILARITY_THRESHOLD = 40.0


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if t not in STOP and len(t) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(target: dict, candidate: dict) -> dict:
    """target/candidate: {equipment_type, category, problem_statement,
    evidence_titles[]}. Returns {score, parts}."""
    parts = {}
    parts["equipment_type"] = 30.0 if (
        target.get("equipment_type") and
        target.get("equipment_type") == candidate.get("equipment_type")) else 0.0
    parts["category"] = 25.0 if (
        target.get("category") and target.get("category") != "UNKNOWN"
        and target.get("category") == candidate.get("category")) else 0.0
    parts["problem"] = round(25.0 * jaccard(tokens(target.get("problem_statement", "")),
                                            tokens(candidate.get("problem_statement", ""))), 1)
    ta = set()
    for t in target.get("evidence_titles", []):
        ta |= tokens(t)
    ca = set()
    for t in candidate.get("evidence_titles", []):
        ca |= tokens(t)
    parts["evidence"] = round(20.0 * jaccard(ta, ca), 1)
    return {"score": round(sum(parts.values()), 1), "parts": parts}
