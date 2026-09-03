"""XLSX processor: read-only, cached values only (data_only=True — formulas
are never executed; only stored cached results are read)."""
from pathlib import Path

from openpyxl import load_workbook

from ..core.config import get_settings
from .base import DocumentProcessor, ExtractResult, ProcessingFailed, flatten_sections


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    return str(v).strip()


class XLSXProcessor(DocumentProcessor):
    file_types = ("XLSX",)

    def process(self, path: Path, *, original_filename: str) -> ExtractResult:
        s = get_settings()
        try:
            wb = load_workbook(str(path), read_only=True, data_only=True)
        except Exception as e:
            raise ProcessingFailed("Unable to read this spreadsheet") from e
        sections: list[dict] = [
            {"type": "heading", "text": f"Workbook: {original_filename}"}]
        sheets_done = 0
        truncated = False
        try:
            for ws in wb.worksheets:
                rows = list(ws.iter_rows(values_only=True))
                rows = [r for r in rows if any(_cell(c) for c in (r or ()))]
                if not rows:
                    continue
                sheets_done += 1
                sections.append({"type": "heading",
                                 "text": f"Sheet: {ws.title}"})
                headers = [_cell(c) or f"col{i+1}"
                           for i, c in enumerate(rows[0])]
                sections.append({"type": "paragraph",
                                 "text": "Columns:\n" + " | ".join(headers)})
                done = 0
                for i, row in enumerate(rows[1:], start=2):
                    if done >= s.DOC_MAX_ROWS:
                        truncated = True
                        break
                    pairs = [f"{headers[j] if j < len(headers) else f'col{j+1}'}"
                             f"={_cell(row[j]) if j < len(row) else ''}"
                             for j in range(max(len(headers), len(row)))]
                    if not any(p.split("=", 1)[1] for p in pairs):
                        continue
                    sections.append({"type": "table",
                                     "source": f"{ws.title} row {i}",
                                     "text": "\n".join(pairs)})
                    done += 1
                if truncated:
                    break
        except Exception as e:
            raise ProcessingFailed("Unable to parse this spreadsheet") from e
        finally:
            try:
                wb.close()
            except Exception:
                pass
        if sheets_done == 0:
            raise ProcessingFailed("This spreadsheet has no readable data")
        text, hit_limit = flatten_sections(sections, s.EXTRACT_MAX_CHARS)
        note = None
        if truncated:
            note = f"Spreadsheet truncated at {s.DOC_MAX_ROWS} rows per sheet"
        if hit_limit:
            note = ((note + "; " if note else "") + "extracted text truncated"
                    f" at {s.EXTRACT_MAX_CHARS} characters")
        return ExtractResult(ok=True, extracted_text=text, sections=sections,
                             page_count=None, ocr_used=False, note=note)
