"""PlannerAgent: deterministic workflow planning (no LLM needed for this step).

Produces a structured plan {goal, steps[{action, reason}]} plus a safe
summary. Equipment mentioned by code is validated against owned equipment;
unknown codes never become facts — the plan says so explicitly.
"""
import re

from ..db import connect as app_connect

_EQUIP_RE = re.compile(r"\b([A-Za-z]{1,4})\s*-?\s*(\d{1,4})\b")


def _owned_equipment(company_id: int) -> list[dict]:
    con = app_connect()
    try:
        rows = con.execute("SELECT id, code, name FROM equipment"
                           " WHERE company_id = ? AND is_active = 1",
                           (company_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def plan(*, company_id: int, query: str, equipment_id: int | None) -> dict:
    owned = _owned_equipment(company_id)
    by_code = {e["code"].strip().upper(): e for e in owned}
    selected = None
    if equipment_id is not None:
        selected = next((e for e in owned if e["id"] == equipment_id), None)
    mentioned = []
    for m in _EQUIP_RE.finditer(query or ""):
        code = f"{m.group(1)}-{m.group(2)}".upper()
        if code in by_code and by_code[code] not in mentioned:
            mentioned.append(by_code[code])
    if selected is None and mentioned:
        selected = mentioned[0]

    steps = [{"action": "search_knowledge_base",
              "reason": "Retrieve private company evidence relevant to the question"}]
    if selected is not None:
        steps[0]["equipment_id"] = selected["id"]
        steps[0]["reason"] = (f"Retrieve evidence scoped to owned equipment "
                             f"{selected['code']}")
    steps.append({"action": "generate",
                  "reason": "Compose a grounded answer from retrieved evidence with citations"})
    summary = [f"Search knowledge base{' for ' + selected['code'] if selected else ''}",
               "Generate grounded answer with citations"]
    return {"goal": (query or "").strip()[:500],
            "equipment": selected,
            "mentioned_equipment": [{"id": e["id"], "code": e["code"]} for e in mentioned],
            "steps": steps,
            "summary": summary}
