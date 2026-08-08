# Ingestion Pipeline

## State machine

```text
DETECTED -> HASHED -> PRESERVED -> EXTRACTED -> CLASSIFIED -> COMPILED -> INDEXED -> VERIFIED -> COMPLETE
```

Terminal/holding states include `DUPLICATE`, `NEEDS_AI`, `NEEDS_REVIEW`, `UNSUPPORTED`, `FAILED`, and `QUARANTINED`.

## Deterministic work comes first

For every input the engine tries to perform, in order:

1. Resolve and security-check the local path; arbitrary symlinks and brain self-ingestion are blocked.
2. Compute SHA256 and source ID.
3. Detect exact duplicate content by hash.
4. Scan for likely secrets and classify egress sensitivity.
5. Copy bytes into canonical Raw storage.
6. Recompute the copied SHA256 before considering preservation successful.
7. Write source manifest and Source Record.
8. Dispatch to a deterministic parser.
9. Normalize output to `ParsedDocument` + locatable segments.
10. Index extracted text into FTS5 and local semantic vectors.
11. Only then invoke optional AI compilation.

If AI is absent, the source remains preserved/searchable and the job becomes `NEEDS_AI` rather than failing.

## Supported V1 inputs

Text/Markdown, CSV/TSV, JSON/YAML, HTML, PDF, DOCX, PPTX, XLSX, EML, common source-code formats and folder imports are extracted deterministically.

Images and audio/video are preserved and receive deterministic metadata. Description/transcription is optional and must be configured. A PDF with no extractable text is explicitly marked as likely scanned / requiring OCR; the engine does not claim extraction succeeded.

## Folder imports

Recursive imports ignore common dependency/build/cache directories such as `.git`, `node_modules`, `.venv`, `dist`, `build`, coverage output, `__pycache__`, `.next`, `.cache`, and IDE caches. Arbitrary symlinks are not followed.

## Failure guarantees

A parser or downstream failure after preservation does not delete the raw source. The durable job records stage, exception class, retry count and next action. Unsafe archives can therefore be quarantined while retaining their original bytes for evidence/review.

## Integrity

`second-brain verify` and maintenance integrity checks recompute source hashes. A changed raw source is reported as corruption, not accepted as an edit.
