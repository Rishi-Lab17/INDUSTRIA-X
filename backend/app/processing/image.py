"""Image processor: verifies integrity, records dimensions, runs LOCAL OCR
when an engine exists. Without OCR: honest COMPLETED with empty text,
ocr_used=false and a clear note — never fake output, never cloud calls."""
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .base import DocumentProcessor, ExtractResult, ProcessingFailed
from .ocr import OCRError, get_ocr_provider, ocr_available


class ImageProcessor(DocumentProcessor):
    file_types = ("JPG", "JPEG", "PNG")

    def process(self, path: Path, *, original_filename: str) -> ExtractResult:
        try:
            with Image.open(path) as img:
                img.verify()
            with Image.open(path) as img:
                width, height = img.size
                fmt = (img.format or "").upper()
        except (UnidentifiedImageError, OSError, ValueError) as e:
            raise ProcessingFailed("Unable to read this image file") from e
        sections = [{"type": "paragraph",
                     "text": f"Image: {original_filename} ({fmt or 'image'},"
                             f" {width}x{height}px)"}]
        if ocr_available():
            try:
                out = get_ocr_provider().image_to_text(path)
            except OCRError as e:
                raise ProcessingFailed(
                    "Local OCR could not read this image") from e
            if out:
                sections.append({"type": "paragraph", "text": out})
                return ExtractResult(
                    ok=True, extracted_text="\n".join(
                        s["text"] for s in sections),
                    sections=sections, page_count=None, ocr_used=True, note=None)
            note = ("Local OCR ran but found no readable text in this image")
            return ExtractResult(
                ok=True,
                extracted_text=sections[0]["text"],
                sections=sections, page_count=None, ocr_used=True, note=note)
        return ExtractResult(
            ok=True, extracted_text=sections[0]["text"], sections=sections,
            page_count=None, ocr_used=False,
            note=("Local OCR engine unavailable (tesseract not installed);"
                  " image preserved, text extraction skipped"))
