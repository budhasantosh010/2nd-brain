# SYSTEM — Global Brain Architecture

## Purpose

The Global Brain is a local-first knowledge and project-memory system. It accepts unsorted information, preserves original evidence, extracts normalized content, compiles revisable knowledge, maintains project state, retrieves scoped evidence, and verifies answers before presenting stored claims as fact.

Obsidian is the initial interface. The brain itself is the combination of ordinary Markdown, original source files, structured metadata, SQLite, a rebuildable semantic index, a processing engine, a retrieval/verification engine, provider abstractions, and a local MCP/tool surface.

## Canonical layers

1. **Raw evidence** — immutable original bytes in `02 Sources/Raw`.
2. **Source records** — provenance and extraction facts in `02 Sources/Records`.
3. **Compiled knowledge** — concepts, important claims, decisions, entities, lessons, frameworks, and related notes under `03 Knowledge`.
4. **Project memory** — stable purpose plus current state/history under `04 Projects`.
5. **Operational views** — generated current context, tasks, open loops, contradictions, gaps, stale knowledge, failures, and briefs.
6. **Generated machine state** — SQLite, FTS, semantic vectors, queue, ledgers, manifests, caches, logs, locks, and runtime heartbeat in `.brain`.

Generated machine state is disposable. Canonical knowledge must remain recoverable from files and source records without depending solely on a database or AI provider.

## Data ownership

The user's local files own the brain. Obsidian, SQLite, local embeddings, cloud AI, local AI, and MCP clients are replaceable interfaces or accelerators. No provider may become the sole owner of evidence or canonical knowledge.

## One-writer-per-layer model

Canonical write ownership is fixed:

- raw sources and source records → Ingestion Engine;
- compiled knowledge → Knowledge Compiler;
- project state → Project State workflow;
- briefs/operations dashboards → Maintenance Engine;
- indexes → Index Engine;
- system policy → explicit human-approved development.

All canonical writes still pass through the shared transaction manager, which enforces preconditions, backups, atomic replacement, database consistency, ledger records, rollback, and recovery.

## Runtime architecture

```text
Inbox / explicit ingest
        ↓
Deterministic ingestion
(hash → preserve → parse → segment → metadata → security)
        ↓
SQLite + FTS raw extraction
        ↓
Optional AI compiler through provider abstraction
        ↓
Knowledge/project change plan
        ↓
Policy decision: auto / stage / block
        ↓
Transaction manager
        ↓
Canonical Markdown + structured DB + rebuildable indexes
        ↓
Hybrid retrieval → verification → answer
```

The daemon adds filesystem watching, a durable queue, scheduled maintenance, heartbeat, single-instance locking, transient retries, and missed-job recovery.

## Trusted versus generated state

Raw source bytes are immutable evidence. Source records are deterministic provenance. Compiled knowledge is derived and revisable. Operational state is the current working truth but retains history and provenance. Indexes, caches, rankings, briefs, and model outputs are generated products that can be rebuilt or regenerated.

Imported content never gains instruction authority simply because it was indexed or retrieved.

## System invariants

- Raw source bytes cannot be silently changed.
- Every derived claim retains provenance to source and locator where available.
- Generated indexes are disposable and fully rebuildable.
- Canonical knowledge cannot depend solely on SQLite, vectors, or a provider.
- No destructive operation occurs without policy authorization.
- Risky semantic changes are staged rather than silently applied.
- The same source hash is not ingested twice as a new source.
- A filename is never the sole source identifier.
- A model's confidence statement never replaces evidence state.
- A failed optional AI call never causes loss of preserved source material.
- Canonical mutation has one writer and is recoverable after interruption.
- Current state and historical state remain distinguishable.
- Unknown source material is private by default.
