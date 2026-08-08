# Phase 3 Handoff — Future Custom Application

Phase 3 is intentionally not implemented in V1. The future Tauri/React desktop application should replace or supplement Obsidian as a user interface, not replace the brain's ownership model.

## Preserve unchanged

```text
Custom App
    |
    v
same Brain Engine
    |-- same immutable source store
    |-- same canonical Markdown/project memory
    |-- same durable knowledge ledgers
    |-- same SQLite migrations/generated structured state
    |-- same FTS/vector retrieval service
    |-- same verification/evidence objects
    |-- same transaction/review policies
    `-- same MCP/tool boundary
```

## Recommended UI surfaces

- Drop zone backed by the existing Inbox/ingestion API.
- Ask/search backed by `RetrievalService` + `VerificationService`.
- Source viewer that consumes stable source IDs and locators.
- Project current-state/handoff view backed by ProjectService.
- Needs Review cards backed by ReviewService; buttons should call approve/reject operations, not edit files directly.
- Health/status backed by `doctor`/observability data.
- Settings backed by validated runtime config without exposing secrets into public config.

## Do not do

- Do not migrate canonical knowledge into a proprietary app-only database.
- Do not bypass the transaction manager for UI writes.
- Do not let the UI delete raw sources directly.
- Do not create a second search/index schema when the existing service can be called.
- Do not make an AI provider account required to open/recover the user's knowledge.
- Do not weaken source-data prompt-injection boundaries for convenience.

## API extraction path

If the desktop app needs a process boundary, factor the existing Python services behind a local API or invoke them through MCP/stdio. Preserve model schemas and stable IDs so the transition is additive rather than a destructive migration.

## Known V1 extension points

- Replace the lightweight local hashing embedding provider with a stronger fully local embedding model while keeping `EmbeddingProvider` semantics.
- Add OCR/transcription/vision adapters behind existing optional capability flags.
- Add richer verified answer synthesis only if output remains evidence-checked.
- Improve review UX from Markdown/dashboard to native controls without changing operation bundles.
<!-- PHASE25_FINAL -->
## Phase 2.5 boundary before Phase 3

Do not begin Phase 3 until the Phase 2.5 hardening branch has passed independent review. Phase 3 must treat the Phase 2.5 durable ledgers, rollback/rebuild invariants, security precedence, grounded synthesis validator, backup format and MCP contracts as compatibility boundaries. No Phase 3 functionality is introduced by the hardening branch.
