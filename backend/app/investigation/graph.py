"""Dynamic evidence graph builder. Nodes and edges are derived live from
database relationships — never a static diagram.

Node kinds: equipment, investigation, evidence, hypothesis, sensor, document,
image, observation (technician), case (historical), test (recommended).
Edge kinds: SUPPORTS, CONTRADICTS, DERIVED_FROM, RELATED_TO, MEASURES,
OBSERVED_ON, SIMILAR_TO, REQUIRES, VERIFIES, has_problem.
"""
from .common import GRAPH_RELATIONS


def _node(kind: str, ref: str, label: str, **attrs) -> dict:
    return {"id": f"{kind}:{ref}", "kind": kind, "ref": str(ref),
            "label": label, **attrs}


def _edge(src: str, dst: str, relation: str, **attrs) -> dict:
    assert relation in GRAPH_RELATIONS or relation == "has_problem", relation
    return {"from": src, "to": dst, "relation": relation, **attrs}


KIND_MAP = {"SENSOR": "sensor", "DOCUMENT": "document", "IMAGE": "image",
            "OCR": "evidence", "RAG": "evidence", "TECHNICIAN": "observation",
            "MANUAL": "evidence", "MAINTENANCE_HISTORY": "evidence",
            "INSPECTION": "observation", "SYSTEM": "evidence",
            "EXTERNAL_INTEGRATION": "evidence"}


def _remap(ntype: str, nid: int, ev_kind: dict[int, str]) -> str:
    if ntype == "evidence":
        return f"{ev_kind.get(nid, 'evidence')}:{nid}"
    return f"{ntype}:{nid}"


def build_graph(*, investigation: dict, equipment: dict | None,
                evidence: list[dict], hypotheses: list[dict],
                links: list[dict], relations: list[dict],
                similar_cases: list[dict], recommendations: list[dict]) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add(n):
        nodes.setdefault(n["id"], n)

    inv_id = f"inv:{investigation['id']}"
    add(_node("investigation", investigation["id"], investigation["title"],
              status=investigation["status"]))
    if equipment:
        eq_id = f"equipment:{equipment['id']}"
        add(_node("equipment", equipment["id"],
                  f"{equipment.get('code', '')} {equipment.get('name', '')}".strip(),
                  criticality=equipment.get("criticality")))
        edges.append(_edge(eq_id, inv_id, "has_problem"))

    ev_by_id = {e["id"]: e for e in evidence}
    ev_kind: dict[int, str] = {}
    for e in evidence:
        ev_kind[e["id"]] = KIND_MAP.get(e["type"], "evidence")
    for e in evidence:
        kind = ev_kind[e["id"]]
        add(_node(kind, e["id"], e["title"], evidence_type=e["type"]))
        edges.append(_edge(inv_id, f"{kind}:{e['id']}", "RELATED_TO"))
        prov = e.get("provenance") or {}
        if e["type"] == "SENSOR" and prov.get("dataset_id"):
            add(_node("sensor", prov["dataset_id"],
                      f"dataset:{prov['dataset_id']}"))
            edges.append(_edge(f"{kind}:{e['id']}",
                               f"sensor:{prov['dataset_id']}", "DERIVED_FROM"))
        if e["type"] in ("DOCUMENT", "RAG") and prov.get("document_id"):
            add(_node("document", prov["document_id"],
                      prov.get("file_name") or f"doc:{prov['document_id']}"))
            edges.append(_edge(f"{kind}:{e['id']}",
                               f"document:{prov['document_id']}", "DERIVED_FROM"))
        if e["type"] in ("IMAGE", "OCR") and prov.get("image_id"):
            add(_node("image", prov["image_id"],
                      prov.get("file_name") or f"img:{prov['image_id']}"))
            edges.append(_edge(f"{kind}:{e['id']}",
                               f"image:{prov['image_id']}", "DERIVED_FROM"))
        if equipment:
            edges.append(_edge(f"{kind}:{e['id']}",
                               f"equipment:{equipment['id']}", "OBSERVED_ON"))

    hyp_by_id = {h["id"]: h for h in hypotheses}
    for h in hypotheses:
        add(_node("hypothesis", h["id"], h["title"], status=h["status"],
                  support=h.get("support_score"), band=h.get("confidence_band")))
        edges.append(_edge(inv_id, f"hypothesis:{h['id']}", "RELATED_TO"))
    for link in links:
        h, e = hyp_by_id.get(link["hypothesis_id"]), ev_by_id.get(link["evidence_id"])
        if h is None or e is None:
            continue
        ekind = nodes.get(f"evidence:{e['id']}", {}).get("kind", "evidence")
        # resolve actual node kind used above
        for k in ("sensor", "document", "image", "observation", "evidence"):
            if f"{k}:{e['id']}" in nodes:
                ekind = k
                break
        edges.append(_edge(f"{ekind}:{e['id']}", f"hypothesis:{h['id']}",
                           link["relation"]))

    for r in relations:
        src, dst = _remap(r["from_type"], r["from_id"], ev_kind), _remap(
            r["to_type"], r["to_id"], ev_kind)
        if src in nodes and dst in nodes and r["relation"] in GRAPH_RELATIONS:
            edges.append(_edge(src, dst, r["relation"]))

    for c in similar_cases:
        cid = f"case:{c['id']}"
        add(_node("case", c["id"], c["title"], similarity=c.get("similarity")))
        edges.append(_edge(inv_id, cid, "SIMILAR_TO",
                           similarity=c.get("similarity")))

    for rec in recommendations:
        rid = f"test:{rec['id']}"
        add(_node("test", rec["id"], rec["title"], status=rec.get("status", "PENDING")))
        edges.append(_edge(inv_id, rid, "REQUIRES"))

    return {"nodes": list(nodes.values()), "edges": edges,
            "counts": {"nodes": len(nodes), "edges": len(edges)}}
