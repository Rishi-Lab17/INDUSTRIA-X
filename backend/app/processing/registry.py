"""Processor registry. Stage 4 reuses get_processor + section schema."""
from .base import DocumentProcessor
from .csv_tbl import CSVProcessor
from .docx import DOCXProcessor
from .image import ImageProcessor
from .pdf import PDFProcessor
from .txt import TXTProcessor
from .xlsx import XLSXProcessor

_PROCESSORS: list[DocumentProcessor] = [
    PDFProcessor(), DOCXProcessor(), TXTProcessor(), CSVProcessor(),
    XLSXProcessor(), ImageProcessor(),
]


def get_processor(file_type: str) -> DocumentProcessor | None:
    for p in _PROCESSORS:
        if p.handles(file_type):
            return p
    return None


SUPPORTED_TYPES = ("PDF", "DOCX", "TXT", "CSV", "XLSX", "JPG", "JPEG", "PNG")
