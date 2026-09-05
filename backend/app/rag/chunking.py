"""Structure-aware chunking over Stage 3 extracted sections.

Strategy: headings anchor sections; tables stay whole with their source;
paragraphs accumulate to target size; oversize text splits on sentences;
CSV/XLSX row-groups accumulate with header context; page markers propagate.
Overlap is appended at sentence boundaries. Tiny fragments are dropped unless
they are the only content. Output schema is stable for Stage 4+.
"""
import hashlib
import re

from ..core.config import get_settings

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text.strip()) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_sections(sections: list[dict], *, source_type: str) -> list[dict]:
    """Returns chunk dicts: {text, page, section, source_type, char_count,
    checksum}. Chunk index is assigned by the caller (store order)."""
    s = get_settings()
    target, min_c, max_c = (s.CHUNK_TARGET_CHARS, s.CHUNK_MIN_CHARS,
                            s.CHUNK_MAX_CHARS)
    overlap = s.CHUNK_OVERLAP_CHARS

    # 1. Build blocks: (page, heading, kind, text)
    blocks: list[dict] = []
    heading = None
    for sec in sections or []:
        t = sec.get("type", "paragraph")
        text = (sec.get("text") or "").strip()
        if not text:
            continue
        page = sec.get("page")
        if t == "heading":
            heading = text[:200]
            blocks.append({"page": page, "heading": heading, "kind": "heading",
                           "text": text})
        elif t == "table":
            src = sec.get("source")
            blocks.append({"page": page, "heading": heading, "kind": "table",
                           "text": text, "source": src})
        else:  # paragraph / page
            blocks.append({"page": page, "heading": heading, "kind": "text",
                           "text": text})

    # 2. Pack blocks into chunks.
    chunks: list[dict] = []
    cur: list[dict] = []
    cur_len = 0

    def flush():
        nonlocal cur, cur_len
        if not cur:
            return
        text = "\n\n".join(b["text"] for b in cur).strip()
        if len(text) >= min_c or (not chunks and not pending):
            pages = sorted({b["page"] for b in cur if b.get("page")})
            heads = [b["heading"] for b in cur if b.get("heading")]
            chunks.append({
                "text": text,
                "page": pages[0] if pages else None,
                "pages": pages,
                "section": heads[-1] if heads else None,
                "source_type": source_type,
                "char_count": len(text),
                "checksum": _checksum(text),
            })
        cur, cur_len = [], 0

    pending = len(blocks)
    for b in blocks:
        pending -= 1
        piece = b["text"]
        if b["kind"] == "table" and b.get("source"):
            piece = f"[{b['source']}]\n{piece}"
        if len(piece) > max_c:
            flush()
            # Split oversize block on sentences.
            buf, buf_len = "", 0
            for sent in _sentences(piece):
                if buf_len + len(sent) + 1 > max_c and buf:
                    chunks.append(_mk(buf, b, source_type))
                    tail = _overlap_tail(buf, overlap)
                    buf, buf_len = (tail + " " + sent).strip(), 0
                    buf_len = len(buf)
                else:
                    buf = (buf + " " + sent).strip()
                    buf_len = len(buf)
            if buf.strip():
                chunks.append(_mk(buf, b, source_type))
            continue
        if cur_len + len(piece) + 2 > target and cur:
            flush()
            tail = _overlap_tail(chunks[-1]["text"], overlap) if chunks else ""
            if tail:
                cur = [{"page": b["page"], "heading": b["heading"],
                        "kind": "text", "text": tail}]
                cur_len = len(tail)
        cur.append({**b, "text": piece})
        cur_len += len(piece) + 2
    flush()
    return chunks


def _mk(text: str, b: dict, source_type: str) -> dict:
    text = text.strip()
    return {"text": text, "page": b.get("page"),
            "pages": [b["page"]] if b.get("page") else [],
            "section": b.get("heading"), "source_type": source_type,
            "char_count": len(text), "checksum": _checksum(text)}


def _overlap_tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    cut = max(tail.find(". "), tail.find("\n"))
    tail = tail[cut + 1:].strip() if cut >= 0 else tail.strip()
    return tail if len(tail) >= 40 else ""
