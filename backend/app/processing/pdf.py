"""PDF processor: real local text extraction (pypdf). Embedded images of
text-empty pages go through local OCR when available. Scanned PDFs without
any rasterizer produce an honest failure — never fake text."""
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ..core.config import get_settings
from .base import DocumentProcessor, ExtractResult, ProcessingFailed, flatten_sections
from .ocr import OCRError, get_ocr_provider, ocr_available

MAX_EMBEDDED_IMAGES = 5


class PDFProcessor(DocumentProcessor):
    file_types = ("PDF",)

    def process(self, path: Path, *, original_filename: str) -> ExtractResult:
        try:
            reader = PdfReader(str(path))
        except (PdfReadError, OSError, ValueError) as e:
            raise ProcessingFailed("Unable to read this PDF file") from e
        try:
            n_pages = len(reader.pages)
        except Exception as e:
            raise ProcessingFailed("Unable to read this PDF file") from e
        if n_pages == 0:
            raise ProcessingFailed("This PDF has no pages")
        sections: list[dict] = []
        empty_pages = 0
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            text = text.strip()
            if text:
                sections.append({"type": "page", "page": i, "text": text})
            else:
                empty_pages += 1
        ocr_used = False
        note = None
        if empty_pages and ocr_available():
            # Best effort: OCR embedded images from text-empty pages.
            ocr_texts: list[str] = []
            seen = 0
            for i, page in enumerate(reader.pages, start=1):
                if seen >= MAX_EMBEDDED_IMAGES:
                    break
                try:
                    images = list(page.images)
                except Exception:
                    continue
                for img in images:
                    if seen >= MAX_EMBEDDED_IMAGES:
                        break
                    seen += 1
                    tmp = path.parent / f"_ocr_p{i}_{img.name}"
                    try:
                        with open(tmp, "wb") as f:
                            f.write(img.data)
                        out = get_ocr_provider().image_to_text(tmp)
                        if out:
                            ocr_texts.append(f"[PAGE {i} OCR]\n{out}")
                            ocr_used = True
                    except OCRError:
                        continue
                    finally:
                        try:
                            tmp.unlink()
                        except OSError:
                            pass
            for t in ocr_texts:
                sections.append({"type": "page", "page": None, "text": t})
            if empty_pages and not ocr_texts:
                note = (f"{empty_pages} of {n_pages} pages had no extractable"
                        " text and local OCR found nothing readable")
        s = get_settings()
        text, truncated = flatten_sections(sections, s.EXTRACT_MAX_CHARS)
        if truncated:
            note = ((note + "; " if note else "") + "extracted text truncated"
                    f" at {s.EXTRACT_MAX_CHARS} characters")
        if not text:
            if ocr_available():
                raise ProcessingFailed(
                    "Unable to extract text from this PDF (scanned pages not readable)")
            raise ProcessingFailed(
                "Unable to extract text from this PDF. Scanned pages need a local"
                " OCR engine, which is not installed")
        return ExtractResult(ok=True, extracted_text=text, sections=sections,
                             page_count=n_pages, ocr_used=ocr_used, note=note)
