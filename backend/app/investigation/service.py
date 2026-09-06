"""DB-facing Stage 7 orchestration: scoring runs, AI-review hook, snapshots.

Routers stay thin; all score math lives in scoring.py / missing.py.
"""
import json

from ..agents import orchestrator
from ..ai.registry import cached_health
from . import scoring as S
from .common import company_settings
from .missing import evidence_slot, slots_for_hypothesis


def evidence_with_quality(con, inv_id: int, settings: dict,
                          now: float | None = None) -> list[dict]:
    rows = con.execute("SELECT * FROM evidence WHERE investigation_id = ?"
                       " AND is_active = 1 ORDER BY id", (inv_id,)).fetchall()
    out = []
    for r in rows:
        ev = dict(r)
        try:
            ev["metadata"] = json.loads(ev.get("metadata") or "{}")
        except (ValueError, TypeError):
            ev["metadata"] = {}
        try:
            ev["provenance"] = json.loads(ev.get("provenance") or "{}")
        except (ValueError, TypeError):
            ev["provenance"] = {}
        ev["_quality"] = S.evidence_quality(ev, settings, now)
        ev["_slot"] = evidence_slot(ev)
        out.append(ev)
    return out


def score_investigation(con, inv: dict, settings: dict, equipment_type: str,
                        trigger: str) -> list[dict]:
    """Score all hypotheses, persist snapshots, auto-adjust ACTIVE statuses.
    Returns ranked hypothesis views with support/contradict/neutral lists."""
    from .missing import slots_for_hypothesis as _slots
    hyps = [dict(r) for r in con.execute(
        "SELECT * FROM hypotheses WHERE investigation_id = ? ORDER BY id",
        (inv["id"],)).fetchall()]
    evidence = evidence_with_quality(con, inv["id"], settings)
    ev_by_id = {e["id"]: e for e in evidence}
    links = [dict(r) for r in con.execute(
        "SELECT * FROM evidence_links WHERE hypothesis_id IN"
        " (SELECT id FROM hypotheses WHERE investigation_id = ?)",
        (inv["id"],)).fetchall()]

    views = []
    for h in hyps:
        hlinks = [l for l in links if l["hypothesis_id"] == h["id"]]
        rich = []
        for l in hlinks:
            ev = ev_by_id.get(l["evidence_id"])
            if ev is None:
                continue
            rich.append({"relation": l["relation"], "quality": ev["_quality"]["quality"],
                         "evidence_id": ev["id"], "slot": ev["_slot"],
                         "weight": l.get("weight", 1.0)})
        expected = _slots(h.get("title", ""), h.get("description", ""), equipment_type)
        sc = S.score_hypothesis(rich, len(expected), settings)
        con.execute(
            "INSERT INTO hypothesis_scores (hypothesis_id, support_score,"
            " contradiction_score, completeness, confidence_band, trigger)"
            " VALUES (?,?,?,?,?,?)",
            (h["id"], sc["support_score"], sc["contradiction_score"],
             sc["completeness"], sc["confidence_band"], trigger))
        new_status = h["status"]
        if h["status"] == "ACTIVE":
            if sc["confidence_band"] in ("High", "Medium-High"):
                new_status = "SUPPORTED"
            elif (sc["confidence_band"] == "Low"
                  and sc["contradiction_score"] > sc["support_score"]):
                new_status = "WEAKENED"
        if new_status != h["status"]:
            from ..core.security import utcnow_iso
            con.execute("UPDATE hypotheses SET status = ?, updated_at = ? WHERE id = ?",
                        (new_status, utcnow_iso(), h["id"]))
            h["status"] = new_status
        sup = [ev_by_id[l["evidence_id"]] for l in hlinks
               if l["relation"] == "SUPPORTS" and l["evidence_id"] in ev_by_id]
        con_ = [ev_by_id[l["evidence_id"]] for l in hlinks
                if l["relation"] == "CONTRADICTS" and l["evidence_id"] in ev_by_id]
        neu = [ev_by_id[l["evidence_id"]] for l in hlinks
               if l["relation"] == "NEUTRAL" and l["evidence_id"] in ev_by_id]
        views.append({**h, **sc, "hypothesis_id": h["id"], "_links": rich,
                      "support_ids": [e["id"] for e in sup],
                      "contradict_ids": [e["id"] for e in con_],
                      "independence": S.independence_factor(
                          [{"type": ev_by_id[l["evidence_id"]]["type"],
                            "source": ev_by_id[l["evidence_id"]]["source"],
                            "id": l["evidence_id"]}
                           for l in hlinks if l["evidence_id"] in ev_by_id]),
                      "supporting": sup, "contradicting": con_, "neutral": neu,
                      "expected_slots": expected})
    con.commit()
    return S.rank_hypotheses(views)


def ai_review(*, sess: dict, ai_session_id: int | None,
              prompt: str) -> dict:
    """Optional AI enhancement via the Stage 5 orchestrator. Offline (or no
    session) → {available: False, note}. Never fabricates."""
    if ai_session_id is None:
        return {"available": False,
                "note": "No AI session attached; deterministic analysis only."}
    if cached_health().get("status") != "ONLINE":
        return {"available": False,
                "note": "MODEL UNAVAILABLE: no local AI runtime connected."}
    con = None
    try:
        from ..db import connect as _connect
        con = _connect()
        own = con.execute("SELECT * FROM ai_sessions WHERE id = ? AND company_id = ?",
                          (ai_session_id, sess["company_id"])).fetchone()
    finally:
        if con is not None:
            con.close()
    if own is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="AI session not found")
    res = orchestrator.execute(
        sess={**sess, "equipment_id": sess.get("equipment_id")},
        session_id=ai_session_id, user_message=prompt[:4000],
        task_type="document_qa", prompt_template="rag_answer")
    return {"available": res.get("status") == "COMPLETED",
            "answer": res.get("answer", ""),
            "citations": res.get("citations", []),
            "note": None if res.get("status") == "COMPLETED"
            else f"AI run {res.get('status')}: {res.get('error')}"}
