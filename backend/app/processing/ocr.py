"""Local OCR abstraction. Only on-machine engines (Tesseract CLI via
subprocess) — never cloud OCR. Replaceable: implement OCRProvider."""
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from ..core.config import get_settings


class OCRError(Exception):
    pass


class OCRProvider(ABC):
    name = "base"

    @abstractmethod
    def available(self) -> bool:
        ...

    @abstractmethod
    def image_to_text(self, image_path: Path) -> str:
        ...


class TesseractOCRProvider(OCRProvider):
    name = "tesseract"

    def available(self) -> bool:
        s = get_settings()
        return bool(s.OCR_ENABLED) and shutil.which("tesseract") is not None

    def image_to_text(self, image_path: Path) -> str:
        s = get_settings()
        try:
            proc = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", "eng"],
                capture_output=True, timeout=s.OCR_TIMEOUT_S, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            raise OCRError("Local OCR engine failed to run") from e
        if proc.returncode != 0:
            raise OCRError("Local OCR engine could not read the image")
        try:
            return proc.stdout.decode("utf-8", errors="replace").strip()
        except Exception as e:
            raise OCRError("Local OCR output unreadable") from e


def get_ocr_provider() -> OCRProvider:
    s = get_settings()
    if s.OCR_PROVIDER == "tesseract":
        return TesseractOCRProvider()
    return TesseractOCRProvider()  # only local engine supported; extend here


def ocr_available() -> bool:
    return get_ocr_provider().available()
