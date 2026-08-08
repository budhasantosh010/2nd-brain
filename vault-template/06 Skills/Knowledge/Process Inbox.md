---
id: SKL-49ed84bc-019b-5669-809d-6d2c73a63702
type: skill
title: Process Inbox
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 1
---

# Process Inbox

## Purpose
Turn unsorted captures into preserved, indexed, provenance-backed brain material without requiring manual filing.

## Trigger
User asks to process the Inbox, or the daemon detects settled Inbox content.

## Inputs
Files/folders under `01 Inbox`, runtime ingestion policy, parser registry, source database.

## Procedure
1. Enumerate eligible inputs without following arbitrary symlinks.
2. Exclude brain-generated/runtime directories and ignored build/cache directories.
3. For each item run the deterministic ingestion state machine from `DETECTED` through preservation/extraction/indexing.
4. Exact-deduplicate by SHA256.
5. If AI is allowed/healthy, run structured knowledge compilation; otherwise mark `NEEDS_AI` after deterministic work.
6. Apply Level 1 reversible additions through the transaction manager and stage Level 2 changes.
7. Refresh processing status and source index.

## Verification
Every completed item has a source ID, matching raw hash, source record, parser/extraction status, and indexed structured state.

## Failure Conditions
Hash/copy mismatch, unsafe path/symlink/archive, unsupported parser, database/transaction failure, or unhandled parser exception.

## Outputs
Preserved raw sources, records, extraction, processing jobs, indexes, optional provisional knowledge/reviews.

## Side Effects
Creates local runtime files/database rows and may remove an Inbox working copy only after verified canonical preservation according to engine policy.

## Permission Level
Level 1 for routine reversible work; Level 2 proposals may be produced but not silently applied.

## Example
`Process my Inbox` processes all settled eligible inputs and reports completed, duplicate, waiting, review, and failed counts.
