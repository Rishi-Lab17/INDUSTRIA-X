"""Vision ingestion: strict validation + metadata + quality assessment.

Quality heuristics (documented, not calibrated): resolution floors, Laplacian-
variance blur estimate (<100 → blurry on 0-~10000 scale for natural images),
mean brightness extremes. POOR blocks reasoning with a reason; nothing is
faked when the image is unusable.
"""
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from ..core.config import get_settings

ALLOWED = {
    ".jpg": ("JPEG", "image/jpeg"),
    ".jpeg": ("JPEG", "image/jpeg"),
    ".png": ("PNG", "image/png"),
    ".webp": ("WEBP", "image/webp"),
}


class VisionError(Exception):
    pass


def validate_image(filename: str, client_mime: str | None,
                   data: bytes) -> tuple[str, str]:
    if not data:
        raise VisionError("Image file is empty")
    s = get_settings()
    if len(data) > s.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise VisionError(f"Image too large (limit {s.MAX_UPLOAD_SIZE_MB} MB)")
    lowered = (filename or "").strip().lower()
    dot = lowered.rfind(".")
    if dot < 0 or lowered[dot:] not in ALLOWED:
        raise VisionError("Unsupported image type (JPG, JPEG, PNG, WEBP only)")
    if "/" in lowered or "\\" in lowered or "\x00" in lowered:
        raise VisionError("Unsafe filename")
    fmt, mime = ALLOWED[lowered[dot:]]
    try:
        with Image.open(BytesIO(data)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise VisionError("Corrupt or unreadable image file") from e
    # Declared format must match actual content (never trust extension alone).
    try:
        with Image.open(BytesIO(data)) as img:
            actual = (img.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise VisionError("Corrupt or unreadable image file") from e
    if fmt == "JPEG" and actual not in ("JPEG", "JPG", "MPO"):
        raise VisionError("File content does not match its extension")
    if fmt in ("PNG", "WEBP") and actual != fmt:
        raise VisionError("File content does not match its extension")
    void = (client_mime or "").lower()
    if void and void not in ("application/octet-stream", mime):
        raise VisionError("Declared MIME type does not match image content")
    return fmt, mime


def open_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(BytesIO(data)).convert("RGB")
        img.load()
        return img
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise VisionError("Corrupt or unreadable image file") from e


def assess_quality(img: Image.Image) -> dict:
    """Returns {status: GOOD|WARNING|POOR, reasons[], width, height, ...}."""
    import numpy as np
    s = get_settings()
    w, h = img.size
    reasons: list[str] = []
    score = 100.0
    if max(w, h) > s.IMAGE_MAX_DIMENSION:
        reasons.append(f"very large image ({w}x{h}); analysis uses a downscaled copy")
        score -= 5
    if min(w, h) < 320:
        reasons.append("very low resolution; insufficient visual information")
        score -= 60
    elif min(w, h) < 480:
        reasons.append("low resolution")
        score -= 15
    g = np.asarray(img.convert("L"), dtype=float)
    brightness = float(g.mean())
    if brightness < 30:
        reasons.append("extremely dark image")
        score -= 15
    elif brightness > 245:
        reasons.append("extremely bright image")
        score -= 15
    # Variance of Laplacian (blur estimate); heuristic threshold.
    padded = np.pad(g, 1, mode="edge")
    lap = (padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2]
           + padded[1:-1, 2:] - 4 * padded[1:-1, 1:-1])
    blur = float(lap.var())
    if blur < 100:
        reasons.append(f"excessive blur (focus metric {blur:.1f})")
        score -= 25
    score = max(0.0, round(score, 1))
    if min(w, h) < 320 or score < 40:
        status = "POOR"
    elif score < 80:
        status = "WARNING"
    else:
        status = "GOOD"
    return {"status": status, "score": score, "reasons": reasons,
            "width": w, "height": h, "brightness": round(brightness, 1),
            "blur_metric": round(blur, 1),
            "note": "Heuristic quality estimate, not a calibrated probability."}
