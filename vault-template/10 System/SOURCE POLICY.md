# SOURCE POLICY — Immutable Evidence and Lineage

## Original source rule

The original imported bytes are immutable evidence. Never rewrite, normalize, compress, transcode, edit metadata in-place, or otherwise silently change the canonical raw copy.

For every source retain:

- full SHA256 byte hash;
- stable content-addressed source ID;
- original filename;
- original path where available;
- byte size;
- source/content type;
- import timestamp and source-created timestamp when available;
- authority and sensitivity classification;
- canonical raw path;
- extraction lineage, parser/version, and segment locators;
- processing state and failure/retry history.

## Preservation procedure

Calculate the SHA256 before canonical copy. Copy bytes to `02 Sources/Raw/<category>`. Recalculate the hash from the copied bytes and require equality before considering preservation complete. Then write the source manifest/record and proceed to parsing.

Raw-file mutation is corruption, not an edit. Integrity audits periodically recompute hashes. A mismatch creates an alert/failure record and must not be auto-accepted as a new normal state.

## Duplicates and versions

Exact full-SHA256 duplicate → record duplicate observation, do not create another canonical source. Same filename with different bytes → distinct source/version. Filenames are locators/labels, never identity.

## Extraction lineage

Derived extracted text must identify the source, parser, parser version where practical, extraction time, and locators. Locators should preserve navigation such as PDF page, slide, spreadsheet range, text lines, document heading/paragraph, HTML section, email field/body, or audio/video timestamp.

If extraction is incomplete—such as a scanned PDF without OCR—record that limitation explicitly. Never mark extraction successful merely because preservation succeeded.
