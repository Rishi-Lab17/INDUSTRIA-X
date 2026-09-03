"""CSV processor: bounded streaming parse, normalized row=value text that
preserves headers and table shape for future retrieval."""
import csv
from pathlib import Path

from ..core.config import get_settings
from .base import DocumentProcessor, ExtractResult, ProcessingFailed, flatten_sections


class CSVProcessor(DocumentProcessor):
    file_types = ("CSV",)

    def process(self, path: Path, *, original_filename: str) -> ExtractResult:
        s = get_settings()
        try:
            f = open(path, "r", encoding="utf-8-sig", newline="")
        except OSError as e:
            raise ProcessingFailed("Unable to read this CSV file") from e
        with f:
            sample = f.read(8192)
            f.seek(0)
            if not sample.strip():
                raise ProcessingFailed("This CSV file is empty")
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
            except csv.Error:
                dialect = csv.excel
            reader = csv.reader(f, dialect)
            try:
                headers = next(reader)
            except (csv.Error, StopIteration) as e:
                raise ProcessingFailed("Unable to parse this CSV file") from e
            headers = [(h or "").strip() or f"col{i+1}"
                       for i, h in enumerate(headers)]
            if not any(headers):
                raise ProcessingFailed("This CSV file has no columns")
            sections: list[dict] = [
                {"type": "heading", "text": f"CSV: {original_filename}"},
                {"type": "paragraph",
                 "text": "Columns:\n" + ", ".join(headers)},
            ]
            rows_done = 0
            truncated = False
            try:
                for i, row in enumerate(reader, start=1):
                    if rows_done >= s.DOC_MAX_ROWS:
                        truncated = True
                        break
                    if not any((c or "").strip() for c in row):
                        continue
                    pairs = [f"{headers[j] if j < len(headers) else f'col{j+1}'}"
                             f"={(row[j] if j < len(row) else '').strip()}"
                             for j in range(max(len(headers), len(row)))]
                    sections.append({"type": "table", "source": f"Row {i}",
                                     "text": "\n".join(pairs)})
                    rows_done += 1
            except csv.Error as e:
                raise ProcessingFailed("Unable to parse this CSV file") from e
        if rows_done == 0:
            raise ProcessingFailed("This CSV file has no data rows")
        text, hit_limit = flatten_sections(sections, s.EXTRACT_MAX_CHARS)
        note = None
        if truncated:
            note = f"CSV truncated at {s.DOC_MAX_ROWS} rows"
        if hit_limit:
            note = ((note + "; " if note else "") + "extracted text truncated"
                    f" at {s.EXTRACT_MAX_CHARS} characters")
        return ExtractResult(ok=True, extracted_text=text, sections=sections,
                             page_count=None, ocr_used=False, note=note)
