# Data Model

## Stable identifiers

Filenames are labels, not identity. Stable IDs are used throughout:

- `SRC-<first 16 SHA256 hex>` for byte-addressed sources; full SHA256 is also stored.
- `KNO-<uuid>` concepts/knowledge.
- `CLM-<uuid>` claims.
- `DEC-<uuid>` decisions.
- `PRJ-<uuid>` projects.
- `ENT-<uuid>` entities.
- `SKL-<uuid>` skills.
- `RVW-<uuid>` review items.
- `OP-<uuid>` operations.
- `QUE-<uuid>` unresolved questions.

## Canonical Markdown

Canonical note families use validated YAML frontmatter with common identity/status/provenance fields. Templates live in `vault-template/11 Templates`; runtime notes live in the corresponding vault areas.

Important types:

- source
- concept
- claim (materialized only when important/reusable/controversial/decision-critical/frequently retrieved)
- decision
- project / project-state / project-handoff
- entity
- skill
- brief
- review-item
- question / lesson / framework / anti-pattern

## SQLite

`vault/.brain/db/brain.sqlite` is generated structured/query state. Foreign keys are enabled and schema changes use migrations.

Core tables:

`sources`, `source_segments`, `notes`, `concepts`, `claims`, `entities`, `projects`, `project_states`, `decisions`, `relationships`, `skills`, `processing_jobs`, `review_items`, `operations`, `conflicts`, `questions`, `retrieval_events`, `feedback`, `ai_cache`.

Additional operational tables include `open_loops`, `project_candidates` and rebuildable `vector_items`.

## Provenance

A source row points to the immutable raw path, full content hash, original filename/path, import time, sensitivity and extraction path. Source segments keep navigation locators such as page, slide, cell range, heading or line range.

Derived records retain `source_ids` and relationships such as `derived-from` or `supports`. Verification follows these links back to available raw evidence.

## Supersession

Decisions and claims are not silently overwritten. A new record may set `supersedes`; the predecessor is marked superseded and receives `superseded_by`. Historical queries may retrieve it; current-state verification treats it as stale for current truth.

## Claims

Every extracted claim is structured in SQLite and the durable per-source knowledge ledger. Markdown materialization is selective to avoid a vault full of tiny files. This is why the compiler writes `.brain/ledgers/knowledge-SRC-....json`: rebuild must not lose non-materialized claims.

## Relationships

Allowed semantic relations include:

`supports`, `contradicts`, `supersedes`, `derived-from`, `related-to`, `part-of`, `applies-to`, `created-by`, `mentions`, `depends-on`, `result-of`.

Links are evidence-bearing semantics, not graph-density decoration.
<!-- PHASE25_FINAL -->
## Phase 2.5 durable records

Schema version 2 adds active embedding profiles. Durable file contracts include canonical-resolution ledgers per source, append-only project-state events, append-only knowledge-gap events, transaction snapshots, egress/trust audit events and backup manifests. Decision records carry `supersedes` / `superseded_by`; predecessor Markdown, DB and indexes move together and are rollback-scoped.

Source sensitivity is one of `local_only`, `cloud_allowed`, `sensitive`, or `blocked`. This value is persisted in source DB/manifests/records and explicit changes are audited. Generated vector rows embed provider/model/revision/dimensions/schema metadata so profile changes invalidate stale vectors.
