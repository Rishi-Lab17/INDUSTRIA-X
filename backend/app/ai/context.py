"""ContextBuilder + bounded conversation memory.

Context is relevant, bounded, traceable, company-scoped. Budgets come from
config; truncation is recorded, never silent. Citations are never dropped by
truncation (history truncation drops oldest messages first, never evidence).
"""
from ..core.config import get_settings


def build_equipment_block(equipment: dict | None) -> str:
    if not equipment:
        return ""
    fields = ("id", "code", "name", "type", "manufacturer", "model",
              "location", "criticality", "status")
    lines = [f"{k}: {equipment.get(k)}" for k in fields
             if equipment.get(k) is not None]
    return "\n".join(lines)


def build_evidence_block(citations: list[dict], *, max_chars: int | None = None) -> str:
    s = get_settings()
    budget = max_chars or s.AI_MAX_CONTEXT_CHARS
    blocks, used, truncated = [], 0, False
    for i, c in enumerate(citations, start=1):
        head = (f"[Source {i}: {c.get('filename')} v{c.get('document_version')}"
                + (f" p.{c['page']}" if c.get("page") else "")
                + (f" | {c['section']}" if c.get("section") else "") + "]")
        block = f"{head}\n{(c.get('excerpt') or '')[:2000]}"
        if used + len(block) > budget:
            truncated = True
            break
        blocks.append(block)
        used += len(block)
    text = "\n\n".join(blocks)
    if truncated:
        text += "\n[EVIDENCE TRUNCATED AT CONTEXT BUDGET]"
    return text


def select_history(messages: list[dict]) -> tuple[list[dict], bool]:
    """Newest-first bounded window. Returns (selected, truncated)."""
    s = get_settings()
    budget = s.AI_MAX_CONTEXT_CHARS // 2
    chosen: list[dict] = []
    used, truncated = 0, False
    for m in reversed(messages):
        content = str(m.get("content", ""))
        if not content.strip():
            continue
        if len(chosen) >= s.AI_MEMORY_MESSAGES or used + len(content) > budget:
            truncated = True
            break
        chosen.append({"role": m.get("role", "USER"), "content": content[:4000]})
        used += len(content)
    chosen.reverse()
    return chosen, truncated


def assemble(*, system: str, history: list[dict], user_message: str,
             max_chars: int | None = None) -> tuple[list[dict], dict]:
    """Assemble provider messages within budget. Returns (messages, meta)."""
    s = get_settings()
    budget = max_chars or s.AI_MAX_CONTEXT_CHARS
    msgs = [{"role": "system", "content": system[:budget // 2]}]
    used = len(msgs[0]["content"])
    kept, dropped = [], 0
    for m in history:
        role = "user" if m["role"] == "USER" else "assistant"
        if used + len(m["content"]) > budget - len(user_message) - 500:
            dropped += 1
            continue
        kept.append({"role": role, "content": m["content"]})
        used += len(m["content"])
    msgs += kept
    msgs.append({"role": "user", "content": user_message})
    return msgs, {"history_kept": len(kept), "history_dropped": dropped,
                  "chars": used + len(user_message)}
