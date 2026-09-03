"""Upload validation: extension + magic-byte/content sniffing. Never trusts the
client filename or MIME alone."""

MAX_FILENAME_LEN = 255

EXT_TO_TYPE = {
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".txt": "TXT",
    ".csv": "CSV",
    ".xlsx": "XLSX",
    ".jpg": "JPG",
    ".jpeg": "JPEG",
    ".png": "PNG",
}

TYPE_TO_MIME = {
    "PDF": "application/pdf",
    "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "TXT": "text/plain",
    "CSV": "text/csv",
    "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "JPG": "image/jpeg",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
}

DANGEROUS_NAMES = (".exe", ".bat", ".cmd", ".ps1", ".sh", ".js", ".html",
                   ".htm", ".svg", ".msi", ".dll", ".scr", ".com", ".jar")


class ValidationError(Exception):
    pass


def _sniff(data: bytes) -> str | None:
    """Return detected family or None: PDF / ZIP / PNG / JPEG / TEXT."""
    if data.startswith(b"%PDF"):
        return "PDF"
    if data.startswith(b"PK\x03\x04"):
        return "ZIP"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    try:
        data.decode("utf-8")
        return "TEXT"
    except UnicodeDecodeError:
        return None


def validate_upload(filename: str, client_mime: str | None,
                    head: bytes) -> tuple[str, str]:
    """Returns (file_type, mime_type). Raises ValidationError on any problem."""
    if not filename or not filename.strip():
        raise ValidationError("A filename is required")
    name = filename.strip()
    if "/" in name or "\\" in name or "\x00" in name or name.startswith("."):
        raise ValidationError("Unsafe filename")
    if len(name) > MAX_FILENAME_LEN:
        raise ValidationError("Filename too long")
    lowered = name.lower()
    if any(lowered.endswith(ext) for ext in DANGEROUS_NAMES):
        raise ValidationError("Unsupported file type")
    dot = lowered.rfind(".")
    if dot < 0:
        raise ValidationError("File must have an extension")
    ext = lowered[dot:]
    file_type = EXT_TO_TYPE.get(ext)
    if file_type is None:
        raise ValidationError(
            f"Unsupported file type '{ext}'. Supported: PDF, DOCX, TXT, CSV,"
            " XLSX, JPG, JPEG, PNG")
    family = _sniff(head)
    if family is None:
        raise ValidationError("File content not recognized (binary/unknown)")
    expected = {"PDF": "PDF", "DOCX": "ZIP", "XLSX": "ZIP",
                "TXT": "TEXT", "CSV": "TEXT",
                "JPG": "JPEG", "JPEG": "JPEG", "PNG": "PNG"}[file_type]
    if family != expected:
        # Allow: text-based CSV/TXT cross and PNG/JPEG only within family.
        if not (file_type in ("TXT", "CSV") and family == "TEXT"):
            raise ValidationError(
                f"File content does not match its .{ext} extension")
    # DOCX/XLSX are ZIPs: magic is verified above; structural validity is
    # verified by the format processor on the complete file.
    # Client MIME is advisory only (browsers/OSes send many vendor variants,
    # e.g. Windows maps .csv to application/vnd.ms-excel). Reject only on
    # definite contradiction with the sniffed content family.
    void = (client_mime or "").lower()
    if void and void != "application/octet-stream":
        top = void.split("/")[0]
        ok = False
        if file_type in ("TXT", "CSV"):
            ok = top in ("text", "application")
        elif file_type in ("DOCX", "XLSX", "PDF"):
            ok = top == "application"
        elif file_type in ("JPG", "JPEG", "PNG"):
            ok = top == "image"
        if not ok:
            raise ValidationError("Declared MIME type does not match file content")
    return file_type, TYPE_TO_MIME[file_type]
