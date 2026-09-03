"""TXT processor: safe decoding with fallback chain. Never crashes the server
on malformed bytes — returns a clear error instead."""
from pathlib import Path

from ..core.config import get_settings
from .base import DocumentProcessor, ExtractResult, ProcessingFailed, flatten_sections

ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


class TXTProcessor(DocumentProcessor):
    file_types = ("TXT",)

    def process(self, path: Path, *, original_filename: str) -> ExtractResult:
        try:
            raw = path.read_bytes()
        except OSError as e:
            raise ProcessingFailed("Unable to read this text file") from e
        if not raw.strip():
            raise ProcessingFailed("This text file is empty")
        text = None
        for enc in ENCODINGS:
            try:
                text = raw.decode(enc)
                break
            except (UnicodeDecodeError, ValueError):
                continue
        if text is None or not text.strip():
            raise ProcessingFailed("Unable to decode this text file")
        stripped = text.strip()
        # Guard against binary masquerading as text (control-char soup).
        ctrl = sum(1 for ch in stripped if ord(ch) < 32 and ch not in "\n\r\t")
        if len(stripped) > 0 and ctrl / len(stripped) > 0.05:
            raise ProcessingFailed("This file does not contain readable text")
        s = get_settings()
        sections = [{"type": "paragraph", "text": stripped}]
        flat, truncated = flatten_sections(sections, s.EXTRACT_MAX_CHARS)
        note = ("extracted text truncated"
                f" at {s.EXTRACT_MAX_CHARS} characters") if truncated else None
        return ExtractResult(ok=True, extracted_text=flat, sections=sections,
                             page_count=None, ocr_used=False, note=note)
