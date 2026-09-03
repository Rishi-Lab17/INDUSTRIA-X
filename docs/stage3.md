# Stage 3 — Knowledge Base + local document processing

Stage 3 adds company-local document management with real local extraction.
No embeddings, vector DB, or RAG (Stage 4). No external calls of any kind.

## Architecture

```
Upload (multipart)
  → validate (extension + magic bytes + MIME cross-check, size cap)
  → stream to temp (chunked, SHA-256 while writing)
  → equipment ownership check (same company)
  → deterministic versioning (company + filename + equipment; identical bytes → duplicate)
  → atomic move to storage/{documents|images}/{company_id}/{doc_id}/original.<ext>
  → UPLOADED → QUEUED → PROCESSING → COMPLETED | FAILED (persisted states)
  → normalized sections → documents.extracted_text + extracted_json
```

Pipeline modules (`backend/app/processing/`): `base` (contracts + section
flattening), `validate`, `ocr` (provider abstraction), `pdf`, `docx`, `txt`,
`csv_tbl`, `xlsx`, `image`, `registry`. One processor per format — no mega-function.

## Storage

`storage/documents/{company_id}/{doc_id}/original.<ext>`,
`storage/images/...` for images, `processed/` reserved for Stage 4.
Keys are generated (never raw filenames); `_safe_join` resolve-guards every access.

## Supported formats

PDF (pypdf text + page count; embedded-image OCR where practical),
DOCX (headings/paragraphs/tables → sections), TXT (encoding chain + control-char
guard), CSV (bounded sniffed parse → `col=value` rows), XLSX (read-only,
cached values only, per-sheet), JPG/JPEG/PNG (PIL verify + dimensions + local OCR).

## OCR

`OCRProvider` → `TesseractOCRProvider` (tesseract CLI via subprocess, timeout).
Enabled via `OCR_ENABLED`/`OCR_PROVIDER`. **Current machine has no tesseract
binary**: images store fine with `ocr_used=false` + clear note; scanned PDFs
with no text fail honestly with "needs a local OCR engine". Nothing is faked,
nothing leaves the machine.

## Database

`documents` table (see `database/schema.sql`): company/equipment/uploader FKs,
storage_key, type/mime/size/sha256, version + parent chain, 7 processing
states + timestamps + sanitized error + note, extracted_text + extracted_json
(`{source_document_id, sections[]}` — the Stage 4 contract), page_count,
ocr_used, is_archived. Fresh installs via schema; existing DBs need no
migration (new table only).

## Versioning rule

Same company + same filename (case-insensitive) + same equipment link
(null-safe) → new version (`version=max+1`, `parent_document_id=latest`).
Identical SHA-256 → HTTP 200 `{duplicate: true}`, no new version/file.
Retry never versions. Old versions stay retrievable and auditable.

## RBAC

Upload/list/detail/preview/download: all roles. Retry: ADMIN + ENGINEER.
Archive/delete: ADMIN only. All enforced server-side (`require_roles`);
frontend only hides buttons.

## API

`POST /api/documents` (201; 200+duplicate / 409 none / 413 oversize / 422 validation) ·
`GET /api/documents` (filters: equipment_id, file_type, status, archived, search, page/page_size; list items carry only a 300-char preview) ·
`GET /{id}` · `GET /{id}/preview` (full text + sections) ·
`GET /{id}/download` (streamed, safe filename) ·
`POST /{id}/retry` (FAILED only, 409 otherwise) ·
`POST /{id}/archive` (soft; hidden by default) ·
`DELETE /{id}` (admin, permanent bytes+row, audit kept).
Cross-company ids → 404 everywhere (no oracle). Errors sanitized (no paths/traces).

## Audit

DOCUMENT_UPLOADED / _VERSION_CREATED / _EQUIPMENT_ASSOCIATED /
_PROCESSING_STARTED / _COMPLETED / _FAILED / _RETRIED / _VIEWED /
_DOWNLOADED / _ARCHIVED / _DELETED — all with entity_type=document.

## Configuration (.env)

`MAX_UPLOAD_SIZE_MB=50`, `OCR_ENABLED=true`, `OCR_PROVIDER=tesseract`,
plus `OCR_TIMEOUT_S`, `DOC_MAX_ROWS=20000`, `EXTRACT_MAX_CHARS=500000`.
No API keys required for Stage 3.

## Testing

`tests/test_stage3_documents.py` (14 tests): auth, RBAC matrix, all-format
uploads + content assertions, rejections (type/MIME/traversal/empty/oversize),
malformed-PDF safety + leak scan, retry paths, hash/duplicate/versioning,
storage layout, isolation (all endpoints), download/preview shape, filters +
injection probe, archive/delete, full audit trail, OCR-honesty.

## Limitations

- Tesseract not installed → image/scanned-PDF text unavailable (honest state).
- Processing is synchronous in the upload request (prototype scale; background
  queue is a Stage 10 concern).
- No un-archive endpoint (archived docs stay archived + auditable).
- QR payload uses relative passport paths (absolute base URL is Stage 9/10).

## Stage 4 boundary

Consume `documents` rows where `processing_status='COMPLETED'`: chunk
`extracted_json.sections` (stable `{type, text, page?, source?}` schema),
embed locally, store vectors locally, retrieve with document/page provenance.
No Stage 3 changes needed except a read API if desired.
