# CHANGE POLICY — Canonical Write Ownership

Canonical information changes through designated workflows, never through arbitrary direct edits by background components.

## Ownership

- **Raw sources:** Ingestion Engine.
- **Source records:** Ingestion Engine.
- **Compiled knowledge:** Knowledge Compiler.
- **Project state:** Project State workflow.
- **Briefs:** Maintenance Engine.
- **Indexes:** Index Engine.
- **System rules:** human-approved development only.

## One writer

Watcher, daemon, maintenance, MCP, AI chat, and CLI may request changes, but canonical mutation goes through one transaction manager. It validates permission/risk, expected hashes/preconditions, acquires a single-writer lock, creates backups, applies atomic file replacement, coordinates database transaction, records the operation ledger, and rolls back on failure.

## Automatic changes

Safe reversible additions such as source preservation/records, generated indexes, provisional links/concepts, briefs, processing logs, and knowledge gaps may apply automatically.

## Staged changes

Meaning-changing actions—including semantic merges, ambiguous supersession, major objective changes, identity reinterpretation, and canonical restructuring—create a review proposal under `12 Staging` and `00 Home/Needs Review.md`.

## Blocked changes

Raw-source deletion, history erasure, protected-rule changes, external communication/publication, and irreversible external actions are not automated.

## History

Canonical knowledge updates should record change history/provenance. Decisions use supersession rather than overwrite. Project state updates retain historical state through operation/history records even when `STATE.md` shows only current truth.
<!-- PHASE25_FINAL -->
## Phase 2.5 hardening

Canonical writes must be reversible across Markdown + declared DB/FTS/vector scope. Rollback is a compensating historical operation. Merge/move/archive/split/rename/hierarchy changes require review.
