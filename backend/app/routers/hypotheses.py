"""Hypotheses, scoring, evidence graph, missing evidence, NBE, simulation,
confidence history, similar cases. All math deterministic and documented;
scores are Evidence Support Scores, never probabilities."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from ..audit import log_event
from ..core.deps import get_current_session, require_roles
from ..core.rate_limit import allow
from ..core.security import utcnow_iso
from ..db import connect
from ..investigation import graph as graph_mod
from ..investigation import missing as missing_mod
from ..investigation import scoring as scoring_mod
from ..investigation import similarity as similarity_mod
from ..investigation.common import HYP_STATUSES, company_settings
from ..investigation.service import ai_review, evidence_with_quality, score_investigation
from .cases import _ip, _limited, _row_to_evidence, get_owned_hypothesis
from ..investigation.common import get_owned_investigation

router = APIRouter(prefix="/api/cases", tags=["hypotheses"])


# ---------- shared view helpers (also used by cases.py) ----------

def full_view(con, inv: dict, settings: dict) -> dict:
    """Scored hypotheses + evidence + missing + equipment for an investigation."""
    eq = con.execute("SELECT * FROM equipment WHERE id = ?",
                     (inv["equipment_id"],)).fetchone()
    equipment = dict(eq) if eq else None
    etype = (equipment or {}).get("type", "")
    scored = score_investigation(con, inv, settings, etype, trigger="view")
    evidence = evidence_with_quality(con, inv["id"], settings)
    missing = []
    for h in scored:
        linked = {l["slot"] for l in h["_links"] if l.get("slot")}
        for m in missing_mod.missing_for_hypothesis(h, linked, etype):
            missing.append({**m, "hypothesis_id": h["id"],
                            "hypothesis": h["title"]})
    return {"investigation": inv, "equipment": equipment,
            "equipment_type": etype, "hypotheses": scored,
            "evidence": evidence, "missing": missing}


def stored_recommendations(con, inv_id: int) -> list[dict]:
    rows = con.execute("SELECT * FROM evidence_recommendations"
                       " WHERE investigation_id = ? AND status = 'PENDING'"
                       " ORDER BY rank", (inv_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["rationale"] = json.loads(d.get("rationale") or "{}")
        except (ValueError, TypeError):
            d["rationale"] = {}
        out.append(d)
    return out


def health_for(con, inv: dict, settings: dict) -> dict:
    import time as _time
    view = full_view(con, inv, settings)
    ev = view["evidence"]
    exp_slots: set = set()
    for h in view["hypotheses"]:
        exp_slots |= set(h.get("expected_slots", []))
    linked: set = set()
    for h in view["hypotheses"]:
        for l in h.get("_links", []):
            if l.get("slot"):
                linked.add(l["slot"])
    coverage = 100.0 * len(linked & exp_slots) / max(1, len(exp_slots)) if exp_slots else 0.0
    quals = [e["_quality"]["quality"] for e in ev]
    quality = 100.0 * (sum(quals) / len(quals)) if quals else 0.0
    separation = scoring_mod.separation(view["hypotheses"]) * 4.0
    now = _time.time()
    fresh = [scoring_mod.freshness_factor(e.get("timestamp"), settings, now)[0]
             for e in ev]
    freshness = 100.0 * (sum(fresh) / len(fresh)) if fresh else 50.0
    rel = [scoring_mod.trust_for(settings, e.get("type", "")) for e in ev]
    reliability = 100.0 * (sum(rel) / len(rel)) if rel else 50.0
    crit_gaps = sum(1 for m in view["missing"] if m["priority"] == "HIGH")
    return scoring_mod.health_score(
        coverage=coverage, quality=quality, separation_v=min(100.0, separation),
        freshness=freshness, reliability=reliability, critical_gaps=crit_gaps)


def readiness_for(con, inv: dict, company_id: int) -> dict:
    from ..investigation import copilot as copilot_mod
    settings = company_settings(con, company_id)
    health = health_for(con, inv, settings)
    open_conf = con.execute("SELECT COUNT(*) FROM conflicts"
                            " WHERE investigation_id = ? AND status = 'OPEN'",
                            (inv["id"],)).fetchone()[0]
    tech_verified = bool(con.execute(
        "SELECT 1 FROM evidence WHERE investigation_id = ? AND is_active = 1"
        " AND type = 'TECHNICIAN' AND COALESCE(reliability, 0.7) >= 0.7 LIMIT 1",
        (inv["id"],)).fetchone())
    view = full_view(con, inv, settings)
    return copilot_mod.readiness(health=health, open_conflicts=open_conf,
                                 scored=view["hypotheses"],
                                 technician_verified=tech_verified,
                                 settings=settings)


# ---------- hypotheses ----------

class HypothesisIn(BaseModel):
    title: str
    description: str = ""
    category: str = "UNKNOWN"

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title must not be empty")
        return v.strip()[:300]

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        from ..investigation.common import CATEGORIES as _C
        if v not in _C:
            raise ValueError(f"category must be one of {_C}")
        return v


@router.get("/{inv_id}/hypotheses")
def list_hypotheses(inv_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        settings = company_settings(con, sess["company_id"])
        view = full_view(con, inv, settings)
    finally:
        con.close()
    return {"hypotheses": [_public_h(h) for h in view["hypotheses"]]}


def _public_h(h: dict) -> dict:
    return {
        "id": h["id"], "title": h["title"], "description": h["description"],
        "category": h["category"], "status": h["status"],
        "support_score": h["support_score"],
        "contradiction_score": h["contradiction_score"],
        "completeness": h["completeness"],
        "confidence_band": h["confidence_band"], "rank": h["rank"],
        "supporting": [_public_e(e) for e in h["supporting"]],
        "contradicting": [_public_e(e) for e in h["contradicting"]],
        "neutral": [_public_e(e) for e in h["neutral"]],
        "expected_slots": h.get("expected_slots", []),
        "independence": h.get("independence", 1.0),
        "created_at": h["created_at"], "updated_at": h["updated_at"],
    }


def _public_e(e: dict) -> dict:
    return {"id": e["id"], "type": e["type"], "title": e["title"],
            "quality": e["_quality"]["quality"],
            "freshness_band": e["_quality"]["freshness_band"]}


@router.post("/{inv_id}/hypotheses", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_hypothesis(inv_id: int, body: HypothesisIn, request: Request,
                      sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        dup = con.execute("SELECT id FROM hypotheses WHERE investigation_id = ?"
                          " AND lower(title) = lower(?)",
                          (inv_id, body.title)).fetchone()
        if dup:
            raise HTTPException(status_code=409, detail="Hypothesis already exists")
        cur = con.execute(
            "INSERT INTO hypotheses (investigation_id, company_id, title, description,"
            " category, status, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,'ACTIVE',?,?,?)",
            (inv_id, sess["company_id"], body.title, body.description.strip()[:2000],
             body.category, sess["user_id"], utcnow_iso(), utcnow_iso()))
        hid = cur.lastrowid
        con.commit()
        settings = company_settings(con, sess["company_id"])
        view = full_view(con, inv, settings)
    finally:
        con.close()
    log_event("hypothesis_created",
              {"investigation_id": inv_id, "hypothesis_id": hid, "title": body.title},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    target = next(h for h in view["hypotheses"] if h["id"] == hid)
    return _public_h(target)


class GenerateIn(BaseModel):
    ai_session_id: int | None = None


@router.post("/{inv_id}/hypotheses/generate",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def generate_hypotheses(inv_id: int, body: GenerateIn, request: Request,
                        sess: dict = Depends(get_current_session)):
    from ..investigation import hypotheses as hyp_engine
    _limited(sess, "cases:generate")
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        settings = company_settings(con, sess["company_id"])
        eq = con.execute("SELECT * FROM equipment WHERE id = ?",
                         (inv["equipment_id"],)).fetchone()
        evidence = evidence_with_quality(con, inv_id, settings)
        existing = {r["title"] for r in con.execute(
            "SELECT title FROM hypotheses WHERE investigation_id = ?",
            (inv_id,)).fetchall()}
        candidates, notes = hyp_engine.generate_candidates(
            equipment_type=(eq["type"] if eq else ""), evidence=evidence,
            existing_titles=existing)
        created = []
        for c in candidates:
            cur = con.execute(
                "INSERT INTO hypotheses (investigation_id, company_id, title,"
                " description, category, status, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?,?,'ACTIVE',?,?,?)",
                (inv_id, sess["company_id"], c["title"], c["description"],
                 c["category"], sess["user_id"], utcnow_iso(), utcnow_iso()))
            created.append({"id": cur.lastrowid, **c})
        con.commit()
        view = full_view(con, inv, settings)
    finally:
        con.close()
    if created:
        log_event("hypothesis_generated",
                  {"investigation_id": inv_id,
                   "titles": [c["title"] for c in created]},
                  company_id=sess["company_id"], user_id=sess["user_id"],
                  ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    ai = ai_review(sess=sess, ai_session_id=body.ai_session_id, prompt=(
        "Review these investigation hypotheses for completeness. Evidence-backed "
        "additions only; reply as JSON list of {title, description, category} or [].\n"
        + "\n".join(f"- {c['title']}: {c['description'][:200]}" for c in created)
        or "(no new candidates)")) if body.ai_session_id is not None else {
            "available": False, "note": "No AI session attached."}
    ai_added = []
    if ai.get("available") and isinstance(ai.get("answer"), str):
        import json as _json
        try:
            parsed = _json.loads(ai["answer"])
            if isinstance(parsed, list):
                ai_added = [p for p in parsed if isinstance(p, dict) and p.get("title")]
        except (ValueError, TypeError):
            ai_added = []
    return {"created": created, "notes": notes, "hypotheses": [_public_h(h) for h in view["hypotheses"]],
            "ai": {"available": ai.get("available"), "note": ai.get("note"),
                   "suggestions": ai_added[:5]}}


class StatusPatch(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _st(cls, v: str) -> str:
        from ..investigation.common import HYP_STATUSES as _H
        if v not in _H:
            raise ValueError(f"status must be one of {_H}")
        return v


@router.patch("/{inv_id}/hypotheses/{hid}",
              dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def update_hypothesis(inv_id: int, hid: int, body: StatusPatch, request: Request,
                      sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        row = get_owned_hypothesis(con, hid, inv_id)
        con.execute("UPDATE hypotheses SET status = ?, updated_at = ? WHERE id = ?",
                    (body.status, utcnow_iso(), hid))
        con.commit()
        row = con.execute("SELECT * FROM hypotheses WHERE id = ?", (hid,)).fetchone()
    finally:
        con.close()
    log_event("hypothesis_updated",
              {"investigation_id": inv_id, "hypothesis_id": hid,
               "status": body.status},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return dict(row)


class LinkIn(BaseModel):
    evidence_id: int
    relation: str
    weight: float = 1.0

    @field_validator("relation")
    @classmethod
    def _rel(cls, v: str) -> str:
        from ..investigation.common import RELATIONS as _R
        if v not in _R:
            raise ValueError(f"relation must be one of {_R}")
        return v

    @field_validator("weight")
    @classmethod
    def _w(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError("weight must be within 0..2")
        return v


@router.post("/{inv_id}/hypotheses/{hid}/links",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def link_evidence(inv_id: int, hid: int, body: LinkIn, request: Request,
                  sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        get_owned_hypothesis(con, hid, inv_id)
        ev = con.execute("SELECT id FROM evidence WHERE id = ? AND investigation_id = ?"
                         " AND is_active = 1", (body.evidence_id, inv_id)).fetchone()
        if ev is None:
            raise HTTPException(status_code=404, detail="Evidence not found")
        con.execute("INSERT INTO evidence_links (hypothesis_id, evidence_id, relation,"
                    " weight, created_by) VALUES (?,?,?,?,?)"
                    " ON CONFLICT(hypothesis_id, evidence_id) DO UPDATE SET"
                    " relation = excluded.relation, weight = excluded.weight",
                    (hid, body.evidence_id, body.relation, body.weight,
                     sess["user_id"]))
        con.commit()
        settings = company_settings(con, sess["company_id"])
        view = full_view(con, inv, settings)
    finally:
        con.close()
    log_event("evidence_linked",
              {"investigation_id": inv_id, "hypothesis_id": hid,
               "evidence_id": body.evidence_id, "relation": body.relation},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return {"hypotheses": [_public_h(h) for h in view["hypotheses"]]}


@router.delete("/{inv_id}/hypotheses/{hid}/links/{eid}",
               dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def unlink_evidence(inv_id: int, hid: int, eid: int, request: Request,
                    sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        get_owned_hypothesis(con, hid, inv_id)
        cur = con.execute("DELETE FROM evidence_links WHERE hypothesis_id = ?"
                          " AND evidence_id = ?", (hid, eid))
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Link not found")
        settings = company_settings(con, sess["company_id"])
        view = full_view(con, inv, settings)
    finally:
        con.close()
    log_event("evidence_unlinked",
              {"investigation_id": inv_id, "hypothesis_id": hid, "evidence_id": eid},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return {"hypotheses": [_public_h(h) for h in view["hypotheses"]]}


@router.post("/{inv_id}/rescore",
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def rescore(inv_id: int, request: Request, sess: dict = Depends(get_current_session)):
    _limited(sess)
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        settings = company_settings(con, sess["company_id"])
        view = full_view(con, inv, settings)
    finally:
        con.close()
    log_event("hypothesis_scored",
              {"investigation_id": inv_id,
               "scores": {h["id"]: h["support_score"] for h in view["hypotheses"]}},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return {"hypotheses": [_public_h(h) for h in view["hypotheses"]]}


# ---------- evidence graph ----------

@router.get("/{inv_id}/evidence-graph")
def evidence_graph(inv_id: int, sess: dict = Depends(get_current_session)):
    from ..investigation import graph as graph_mod
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        settings = company_settings(con, sess["company_id"])
        view = full_view(con, inv, settings)
        relations = [dict(r) for r in con.execute(
            "SELECT * FROM evidence_relations WHERE company_id = ?",
            (sess["company_id"],)).fetchall()]
        # historical cases attached to this investigation's graph
        similar = similar_for(con, inv, sess["company_id"], limit=5)
        recs = stored_recommendations(con, inv_id)
        return graph_mod.build_graph(
            investigation=inv, equipment=view["equipment"],
            evidence=view["evidence"], hypotheses=view["hypotheses"],
            links=[dict(r) for r in con.execute(
                "SELECT * FROM evidence_links WHERE hypothesis_id IN"
                " (SELECT id FROM hypotheses WHERE investigation_id = ?)",
                (inv_id,)).fetchall()],
            relations=[r for r in relations if _edge_in_scope(r, view, inv_id)],
            similar_cases=similar, recommendations=recs)
    finally:
        con.close()


def _edge_in_scope(r: dict, view: dict, inv_id: int) -> bool:
    ids = {("investigation", inv_id), ("equipment", (view["equipment"] or {}).get("id"))}
    ids |= {("evidence", e["id"]) for e in view["evidence"]}
    ids |= {("hypothesis", h["id"]) for h in view["hypotheses"]}
    ids |= {("test", t["id"]) for t in view.get("recommendations", [])}
    return (r["from_type"], r["from_id"]) in ids or (r["to_type"], r["to_id"]) in ids


class RelationIn(BaseModel):
    from_type: str
    from_id: int
    to_type: str
    to_id: int
    relation: str

    @field_validator("relation")
    @classmethod
    def _rel(cls, v: str) -> str:
        from ..investigation.common import GRAPH_RELATIONS as _G
        if v not in ("RELATED_TO", "REQUIRES", "VERIFIES", "SIMILAR_TO"):
            raise ValueError("Only RELATED_TO/REQUIRES/VERIFIES/SIMILAR_TO "
                             "can be created manually")
        return v


@router.post("/{inv_id}/relations", status_code=201,
             dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def create_relation(inv_id: int, body: RelationIn, request: Request,
                    sess: dict = Depends(get_current_session)):
    _limited(sess)
    allowed_types = ("evidence", "hypothesis", "test", "investigation", "equipment")
    for t, i in ((body.from_type, body.from_id), (body.to_type, body.to_id)):
        if t not in allowed_types:
            raise HTTPException(status_code=422, detail="Invalid node type")
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        for t, i in ((body.from_type, body.from_id), (body.to_type, body.to_id)):
            if not _node_owned(con, t, i, inv_id, sess["company_id"]):
                raise HTTPException(status_code=404, detail=f"Node not found: {t}/{i}")
        cur = con.execute("INSERT INTO evidence_relations (company_id, from_type, from_id,"
                          " to_type, to_id, relation, created_by)"
                          " VALUES (?,?,?,?,?,?,?)",
                          (sess["company_id"], body.from_type, body.from_id,
                           body.to_type, body.to_id, body.relation, sess["user_id"]))
        con.commit()
        row = con.execute("SELECT * FROM evidence_relations WHERE id = ?",
                          (cur.lastrowid,)).fetchone()
    finally:
        con.close()
    return dict(row)


def _node_owned(con, ntype: str, nid: int, inv_id: int, company_id: int) -> bool:
    if ntype == "investigation":
        return nid == inv_id and con.execute(
            "SELECT 1 FROM investigations WHERE id = ? AND company_id = ?",
            (nid, company_id)).fetchone() is not None
    if ntype == "equipment":
        inv = con.execute("SELECT equipment_id FROM investigations WHERE id = ?",
                          (inv_id,)).fetchone()
        return inv is not None and inv["equipment_id"] == nid
    if ntype == "evidence":
        return con.execute("SELECT 1 FROM evidence WHERE id = ? AND investigation_id = ?",
                           (nid, inv_id)).fetchone() is not None
    if ntype == "hypothesis":
        return con.execute("SELECT 1 FROM hypotheses WHERE id = ? AND investigation_id = ?",
                           (nid, inv_id)).fetchone() is not None
    if ntype == "test":
        return con.execute("SELECT 1 FROM evidence_recommendations WHERE id = ?"
                           " AND investigation_id = ?", (nid, inv_id)).fetchone() is not None
    return False


# ---------- missing evidence + NBE ----------

@router.get("/{inv_id}/missing-evidence")
def missing_evidence(inv_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        settings = company_settings(con, sess["company_id"])
        view = full_view(con, inv, settings)
    finally:
        con.close()
    return {"missing": view["missing"]}


@router.get("/{inv_id}/next-best-evidence")
def next_best_evidence(inv_id: int, request: Request,
                       sess: dict = Depends(get_current_session)):
    from ..investigation import missing as missing_mod
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        settings = company_settings(con, sess["company_id"])
        view = full_view(con, inv, settings)
        missing_by_hyp: dict[int, list] = {}
        for m in view["missing"]:
            missing_by_hyp.setdefault(m["hypothesis_id"], []).append(m)

        def scores_fn(hypo_links: dict[int, list]) -> list[dict]:
            from ..investigation import scoring as _S
            rescored = []
            for h in view["hypotheses"]:
                links = hypo_links.get(h["id"], [])
                expected = len(missing_mod.slots_for_hypothesis(
                    h.get("title", ""), h.get("description", ""),
                    view["equipment_type"]))
                sc = _S.score_hypothesis(links, expected, settings)
                rescored.append({"hypothesis_id": h["id"], "title": h["title"], **sc})
            return rescored

        open_conf = con.execute("SELECT COUNT(*) FROM conflicts"
                                " WHERE investigation_id = ? AND status = 'OPEN'",
                                (inv_id,)).fetchone()[0]
        ranked = missing_mod.rank_candidates(
            scored=view["hypotheses"], scores_fn=scores_fn,
            missing_by_hyp=missing_by_hyp, open_conflicts=open_conf)
        con.execute("DELETE FROM evidence_recommendations WHERE investigation_id = ?"
                    " AND status = 'PENDING'", (inv_id,))
        for c in ranked:
            con.execute("INSERT INTO evidence_recommendations (investigation_id,"
                        " company_id, rank, kind, slot, title, rationale, expected_value,"
                        " priority, effort, safety, status)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,'PENDING')",
                        (inv_id, sess["company_id"], c["rank"], c["kind"], c["slot"],
                         c["title"], json.dumps(c["rationale"]), c["expected_value"],
                         c["priority"], c["effort"], c["safety"]))
        con.commit()
        by_slot = {c["slot"]: c for c in ranked}
        persisted = stored_recommendations(con, inv_id)
        for p in persisted:
            comp = by_slot.get(p.get("slot"), {})
            p["discriminative_value"] = comp.get("discriminative_value")
            p["expected_uncertainty_reduction"] = comp.get(
                "expected_uncertainty_reduction")
            p["value_score"] = comp.get("value_score")
            p["best_outcome"] = comp.get("best_outcome")
            p["previews"] = comp.get("previews", {})
    finally:
        con.close()
    log_event("recommendation_generated",
              {"investigation_id": inv_id, "count": len(persisted),
               "top": persisted[0]["title"] if persisted else None},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return {"recommendations": persisted}


class RecoPatch(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _st(cls, v: str) -> str:
        if v not in ("PENDING", "DONE", "DISMISSED"):
            raise ValueError("status must be PENDING, DONE or DISMISSED")
        return v


@router.patch("/{inv_id}/recommendations/{rid}",
              dependencies=[Depends(require_roles("COMPANY_ADMIN", "ENGINEER"))])
def update_recommendation(inv_id: int, rid: int, body: RecoPatch,
                          sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        row = con.execute("SELECT * FROM evidence_recommendations WHERE id = ?"
                          " AND investigation_id = ?", (rid, inv_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        con.execute("UPDATE evidence_recommendations SET status = ? WHERE id = ?",
                    (body.status, rid))
        con.commit()
        row = con.execute("SELECT * FROM evidence_recommendations WHERE id = ?",
                          (rid,)).fetchone()
    finally:
        con.close()
    return _public_reco(row)


def _public_reco(row) -> dict:
    d = dict(row)
    try:
        d["rationale"] = json.loads(d.get("rationale") or "{}")
    except (ValueError, TypeError):
        d["rationale"] = {}
    return d


class SimulateIn(BaseModel):
    hypothesis_id: int
    slot: str
    outcome: str

    @field_validator("outcome")
    @classmethod
    def _oc(cls, v: str) -> str:
        if v not in ("positive", "negative"):
            raise ValueError("outcome must be positive or negative")
        return v

    @field_validator("slot")
    @classmethod
    def _slot(cls, v: str) -> str:
        from ..investigation.missing import SLOTS
        if v not in SLOTS and v != "repeat_measurement":
            raise ValueError("Unknown evidence slot")
        return v


@router.post("/{inv_id}/simulate")
def simulate_evidence(inv_id: int, body: SimulateIn, request: Request,
                      sess: dict = Depends(get_current_session)):
    from ..investigation import missing as missing_mod
    _limited(sess, "cases:simulate")
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        settings = company_settings(con, sess["company_id"])
        view = full_view(con, inv, settings)
        ids = {h["id"] for h in view["hypotheses"]}
        if body.hypothesis_id not in ids:
            raise HTTPException(status_code=404, detail="Hypothesis not found")
        from ..investigation.missing import SLOTS as _SLOTS
        reliability = _SLOTS[body.slot]["reliability"] \
            if body.slot in _SLOTS else 0.85

        def scores_fn(hypo_links):
            from ..investigation import scoring as _S
            rescored = []
            for h in view["hypotheses"]:
                links = hypo_links.get(h["id"], [])
                expected = len(missing_mod.slots_for_hypothesis(
                    h.get("title", ""), h.get("description", ""),
                    view["equipment_type"]))
                sc = _S.score_hypothesis(links, expected, settings)
                rescored.append({"hypothesis_id": h["id"], "title": h["title"], **sc})
            return rescored

        from ..investigation.missing import _simulate
        sim = _simulate(scores_fn, view["hypotheses"], body.hypothesis_id,
                        body.slot, body.outcome, reliability)
    finally:
        con.close()
    log_event("simulation_executed",
              {"investigation_id": inv_id, "hypothesis_id": body.hypothesis_id,
               "slot": body.slot, "outcome": body.outcome},
              company_id=sess["company_id"], user_id=sess["user_id"],
              ip=_ip(request), entity_type="investigation", entity_id=inv_id)
    return {"hypothesis_id": body.hypothesis_id, "slot": body.slot,
            "outcome": body.outcome, **sim}


# ---------- confidence history ----------

@router.get("/{inv_id}/confidence-history")
def confidence_history(inv_id: int, sess: dict = Depends(get_current_session)):
    con = connect()
    try:
        get_owned_investigation(con, inv_id, sess["company_id"])
        rows = con.execute(
            "SELECT s.*, h.title FROM hypothesis_scores s"
            " JOIN hypotheses h ON h.id = s.hypothesis_id"
            " WHERE h.investigation_id = ? ORDER BY s.id", (inv_id,)).fetchall()
    finally:
        con.close()
    return {"history": [dict(r) for r in rows]}


# ---------- similar cases ----------

@router.get("/{inv_id}/similar-cases")
def similar_cases(inv_id: int, sess: dict = Depends(get_current_session)):
    from ..investigation import similarity as sim_mod
    con = connect()
    try:
        inv = get_owned_investigation(con, inv_id, sess["company_id"])
        eq = con.execute("SELECT type FROM equipment WHERE id = ?",
                         (inv["equipment_id"],)).fetchone()
        ev_titles = [r["title"] for r in con.execute(
            "SELECT title FROM evidence WHERE investigation_id = ? AND is_active = 1",
            (inv_id,)).fetchall()]
        target = {"equipment_type": (eq["type"] if eq else ""),
                  "category": inv["category"],
                  "problem_statement": inv["problem_statement"],
                  "evidence_titles": ev_titles}
        rows = con.execute(
            "SELECT i.*, e.type AS equipment_type FROM investigations i"
            " JOIN equipment e ON e.id = i.equipment_id"
            " WHERE i.company_id = ? AND i.id != ?"
            " AND i.status IN ('RESOLVED','CLOSED')", (sess["company_id"], inv_id)).fetchall()
        out = []
        for r in rows:
            cand_titles = [x["title"] for x in con.execute(
                "SELECT title FROM evidence WHERE investigation_id = ? AND is_active = 1",
                (r["id"],)).fetchall()]
            sim = sim_mod.similarity(target, {
                "equipment_type": r["equipment_type"], "category": r["category"],
                "problem_statement": r["problem_statement"],
                "evidence_titles": cand_titles})
            if sim["score"] >= sim_mod.SIMILARITY_THRESHOLD:
                out.append({"id": r["id"], "title": r["title"],
                            "status": r["status"], "category": r["category"],
                            "similarity": sim["score"], "parts": sim["parts"]})
        out.sort(key=lambda c: -c["similarity"])
    finally:
        con.close()
    return {"cases": out,
            "note": None if out else "No sufficiently similar historical cases found."}


def similar_for(con, inv: dict, company_id: int, limit: int = 5) -> list[dict]:
    """Graph attachment helper (top-N similar resolved cases)."""
    from ..investigation import similarity as sim_mod
    eq = con.execute("SELECT type FROM equipment WHERE id = ?",
                     (inv["equipment_id"],)).fetchone()
    ev_titles = [r["title"] for r in con.execute(
        "SELECT title FROM evidence WHERE investigation_id = ? AND is_active = 1",
        (inv["id"],)).fetchall()]
    target = {"equipment_type": (eq["type"] if eq else ""),
              "category": inv["category"],
              "problem_statement": inv["problem_statement"],
              "evidence_titles": ev_titles}
    rows = con.execute(
        "SELECT i.*, e.type AS equipment_type FROM investigations i"
        " JOIN equipment e ON e.id = i.equipment_id"
        " WHERE i.company_id = ? AND i.id != ? AND i.status IN ('RESOLVED','CLOSED')",
        (company_id, inv["id"])).fetchall()
    out = []
    for r in rows:
        cand_titles = [x["title"] for x in con.execute(
            "SELECT title FROM evidence WHERE investigation_id = ? AND is_active = 1",
            (r["id"],)).fetchall()]
        sim = sim_mod.similarity(target, {
            "equipment_type": r["equipment_type"], "category": r["category"],
            "problem_statement": r["problem_statement"],
            "evidence_titles": cand_titles})
        if sim["score"] >= sim_mod.SIMILARITY_THRESHOLD:
            out.append({"id": r["id"], "title": r["title"], "similarity": sim["score"]})
    out.sort(key=lambda c: -c["similarity"])
    return out[:limit]
