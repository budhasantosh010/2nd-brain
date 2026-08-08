# Phase 2 Acceptance

Phase 2 removes routine manual triggering while preserving Phase 1's local ownership and trust boundaries.

## P2-A — Deterministic ingestion

Watcher, hashing, raw preservation, parser dispatch, manifests, durable jobs, exact dedupe, folder ignores, secret classification and local search indexing work before AI. Required document formats are covered by synthetic tests.

## P2-B/C — AI compiler and structured storage

All providers implement one interface. Structured extraction is schema-validated and cached before mutation. SQLite stores structured entities/claims/projects/states/decisions/relationships/reviews/operations/questions while durable local knowledge ledgers preserve non-materialized compiler output for rebuild.

## P2-D — Hybrid retrieval

FTS5, metadata/exact lookup, local semantic vectors, reciprocal-rank fusion, temporal/current-state weighting, one-hop graph expansion and context budgeting operate as one retrieval service. Fixed synthetic benchmark tests measure Recall@K/MRR/citation/current-state/unsupported-answer behavior.

## P2-E — Verification

Answers require available source provenance. Superseded/stale material is not presented as current truth. Contradictions are surfaced. Unsupported questions return the grounded refusal and become stored knowledge gaps.

## P2-F — Transactions and review

The transaction manager owns canonical mutation, enforces expected hashes and one writer, backs up affected files, atomically replaces targets, rolls files/DB back on apply failure and recovers interrupted operations. Meaning-changing changes stage as review items; protected/destructive paths remain blocked.

## P2-G — Automation

The daemon has a single-instance lock and heartbeat, watches Inbox, processes pre-existing Inbox files after restart, runs durable processing, and executes missed nightly/weekly/monthly work based on Asia/Dubai schedule state.

## P2-H — MCP

The local stdio server registers all required read and safe write/proposal tools. MCP clients do not receive unrestricted filesystem mutation. Ambiguous project state is staged unless explicitly evidence-backed.

## P2-I — Hardening

Windows setup/start/stop/uninstall scripts are syntax/smoke-tested using paths with spaces. Doctor, verify, rebuild/recovery, security/privacy tests, public-repo leakage scan, end-to-end fixtures, documentation and CI are release gates.

## Release rule

Phase 2 is not complete until the final release validation records all required checks as passing and the pushed branch SHA matches the local final SHA. Known limitations may describe non-blocking quality ceilings, but unfinished acceptance gates must be reported as incomplete rather than hidden as future work.
