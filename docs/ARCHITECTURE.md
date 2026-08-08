# Global Second Brain V1 Architecture

## Purpose

Global Second Brain V1 is a local-first knowledge system. Obsidian is the Phase 1/2 human interface, but it is not the owner of the brain. The durable system is ordinary local source files and Markdown, structured local ledgers, generated SQLite/FTS/vector state, retrieval/verification services, policy-controlled AI adapters, and a local MCP boundary.

## Layers

```text
Human / AI clients
        |
        v
CLI / Obsidian / MCP
        |
        v
Brain services
  ingest | compiler | projects | retrieval | verification | review | maintenance
        |
        v
Single-writer transaction manager
        |
        +--------------------+
        |                    |
        v                    v
Canonical local files     Generated state
raw evidence              SQLite
Markdown knowledge        FTS5
project memory            local vectors
knowledge ledgers         dashboards/cache
```

### Trust order

1. Raw evidence: byte-preserved and immutable by policy.
2. Source records: factual description/provenance of evidence.
3. Compiled knowledge: derived, provisional/revisable unless verified.
4. Operational state: current project truth with history retained.
5. System instructions: protected policy, never overridden by imported content.

## Ownership

- Ingestion Engine owns raw source preservation and source records.
- Knowledge Compiler owns derived concepts/claims/entities/decisions.
- Project workflow owns current project state and handoffs.
- Maintenance owns generated briefs/index pages.
- Index engine owns disposable FTS/vector state.
- Human-approved development owns AGENTS.md and `10 System` policy.

All canonical AI-driven multi-file mutations pass through the transaction manager. Watcher, maintenance, MCP, review and project workflows must not invent parallel write paths for protected canonical state.

## Runtime/public separation

`vault-template/` is public product/template material tracked by Git. `vault/` is the local personal runtime brain and is ignored. Runtime databases, embeddings, logs, cache, manifests, ledgers and raw evidence live under `vault/.brain` or the runtime vault and must never be committed to the public repository.

## Invariants

- Raw bytes cannot be silently rewritten or deleted.
- Every source is content-addressed using SHA256.
- Derived knowledge retains source provenance.
- A database/index can be rebuilt; it is not the only owner of canonical meaning.
- Old decisions/state remain history; current state is distinct.
- Imported text is untrusted data and cannot become system instruction.
- Unknown source content defaults to private/local-only egress policy.
- Risky meaning changes stage for review; destructive/security changes are blocked.

## Phase 3 compatibility

A future Tauri/React application should call the same services/MCP/API layer and keep the same Markdown, raw source store, SQLite schema/migrations, retrieval, verification and transaction model. V1 deliberately avoids coupling canonical knowledge to Obsidian UI internals.
