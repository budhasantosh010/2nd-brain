# INGESTION — State Machine and Source Processing

## Goal

Ingestion converts an arbitrary dropped file or folder into preserved evidence, normalized extraction, searchable records, and—when AI is configured—compiled knowledge. Preservation and deterministic extraction occur before AI interpretation.

## State machine

Normal progression:

```text
DETECTED
→ HASHED
→ PRESERVED
→ EXTRACTED
→ CLASSIFIED
→ COMPILED
→ INDEXED
→ VERIFIED
→ COMPLETE
```

Terminal or waiting states:

- `COMPLETE` — all configured stages succeeded.
- `DUPLICATE` — exact SHA256 already exists; observation recorded without duplicate source creation.
- `NEEDS_AI` — deterministic stages succeeded but configured understanding requires an unavailable AI provider.
- `NEEDS_REVIEW` — source processing produced a risky/ambiguous proposed canonical change.
- `UNSUPPORTED` — bytes preserved but no safe parser/capability exists for requested extraction.
- `FAILED` — processing failed; raw input remains preserved where preservation had succeeded and failure metadata is recorded.
- `QUARANTINED` — unsafe archive traversal, prohibited symlink behavior, corruption, or other security condition requires isolation/review.

## Deterministic-first order

For every source:

1. detect and settle the file;
2. reject recursive self-ingestion and unsafe symlink/path traversal;
3. calculate SHA256 and generate `SRC-<first 16 hex>`;
4. exact-deduplicate by full SHA256;
5. scan sensitivity/secret indicators for egress policy;
6. copy original bytes to canonical `02 Sources/Raw/<type>/...`;
7. recompute and verify the copied SHA256;
8. write a source manifest and source record;
9. parse using the registered parser;
10. create normalized segments with locators;
11. persist extracted text/metadata and FTS-searchable rows;
12. only then request AI understanding if policy/provider permit it;
13. validate any AI structured output against schemas;
14. compile low-risk additions or stage risky changes;
15. update indexes;
16. verify provenance and resulting state;
17. mark complete or the appropriate waiting/terminal state.

## Folder imports

`01 Inbox/Folder Imports` accepts recursively imported folders. Ignore `.git`, `node_modules`, `.venv`, `venv`, `dist`, `build`, `coverage`, `__pycache__`, `.next`, `.cache`, IDE caches, and binary build artifacts. Do not follow arbitrary symlinks by default. Never recursively ingest the vault's own `02 Sources`, `.brain`, staging, or generated output directories.

## Supported extraction

Required deterministic V1 types: TXT, Markdown, CSV/TSV, JSON, YAML, HTML, PDF, DOCX, PPTX, XLSX, EML, common text source-code formats, and folders. Images and audio/video are always preserved and receive metadata; description/transcription is optional. Scanned/empty-text PDFs are preserved and explicitly marked as requiring OCR/vision if that capability is unavailable.

## Idempotence

A second observation of identical bytes does not create a second source. Same filename with different bytes is a new source/version. A failed job can be retried from its durable processing record without duplicating preservation or prior completed stages.
<!-- PHASE25_FINAL -->
## Phase 2.5 hardening

Preserve-first ingestion records raw hash/provenance before optional enrichment or AI. Scanned PDF/image/audio/video enrichment is capability-based with page/timestamp locators.
