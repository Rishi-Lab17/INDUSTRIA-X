"""Processing pipeline contracts. Pure local parsing — no network, no external
AI/OCR services. Stage 4 will chunk `sections` for embeddings; the schema is
stable for that: {"source_document_id", "sections": [{type, text, ...}]}."""
from abc import ABC, abstractmethod
from pathlib import Path


class ProcessingFailed(Exception):
    """Raised for user-safe, expected extraction failures (message is sanitized)."""


class ExtractResult(dict):
    """Keys: ok(bool), extracted_text(str), sections(list), page_count(int|None),
    ocr_used(bool), note(str|None). On failure processors raise ProcessingFailed."""


class DocumentProcessor(ABC):
    file_types: tuple[str, ...] = ()

    def handles(self, file_type: str) -> bool:
        return file_type in self.file_types

    @abstractmethod
    def process(self, path: Path, *, original_filename: str) -> ExtractResult:
        ...


def flatten_sections(sections: list[dict], max_chars: int) -> tuple[str, bool]:
    """Join sections with structural markers. Returns (text, truncated)."""
    parts: list[str] = []
    for s in sections:
        t = s.get("type", "paragraph")
        text = (s.get("text") or "").strip()
        if not text:
            continue
        if t == "page":
            parts.append(f"\n[PAGE {s.get('page', '?')}] {text}")
        elif t == "heading":
            parts.append(f"\n## {text}")
        elif t == "table":
            src = f" ({s.get('source')})" if s.get("source") else ""
            parts.append(f"\n[TABLE{src}]\n{text}")
        else:
            parts.append(text)
    out = "\n".join(parts).strip()
    if len(out) > max_chars:
        return out[:max_chars], True
    return out, False
