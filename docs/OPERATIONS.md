# Operations Guide

## Normal user workflow

1. Open the runtime vault in Obsidian: `<repo>/vault`.
2. Drop files into `01 Inbox` (folders into `Folder Imports` are fine).
3. Keep the daemon running or run `second-brain ingest` manually.
4. Ask questions through the CLI or an MCP-connected AI.
5. Review only items surfaced in `00 Home/Needs Review.md`.

The user should not manually maintain indexes, backlinks, PARA moves, handoffs or generated status pages.

## Useful commands

```text
second-brain init
second-brain doctor
second-brain status
second-brain ingest [path]
second-brain watch
second-brain daemon
second-brain search "query"
second-brain ask "question"
second-brain review list
second-brain review show RVW-...
second-brain review approve RVW-...
second-brain review reject RVW-...
second-brain maintain nightly|weekly|monthly
second-brain verify
second-brain rebuild
second-brain recover
second-brain mcp serve
```

## Processing states

`NEEDS_AI` is not data loss: preservation/extraction/indexing succeeded, but optional AI compilation cannot run. `FAILED` and `QUARANTINED` retain raw evidence when preservation already occurred. See Processing Status and Failed Processing for next actions.

## Needs Review

Risky meaning changes are serialized as proposed operation bundles and rendered under `12 Staging`. Approval runs the same transaction manager used elsewhere; rejection leaves canonical targets unchanged. Review dashboards are generated from structured review state.

## Maintenance

Nightly work processes Inbox backlog, retries AI work, refreshes project handoffs/operations pages, creates the daily brief and samples raw integrity. Weekly work audits duplicates/orphans/conflicts/stale projects/failures. Monthly synthesis surfaces archive candidates, recurring clusters, stale assumptions and higher-level structural proposals without deleting history.

Schedules use `Asia/Dubai` by default. The scheduler records last success and recognizes missed daily/weekly/monthly work after restart. Inbox processing is continuous and is also attempted immediately on daemon startup.

## Recovery

Canonical writes create backups under `.brain/history/<operation-id>` and transaction manifests under `.brain/transactions/<operation-id>`. `second-brain recover` rolls back operations left in an applying state. `second-brain rebuild` archives the generated database before rebuilding source/knowledge/project/skill search state from local evidence and ledgers.

## Corruption

If `verify` reports a raw hash mismatch, treat it as corruption. Do not edit the stored Raw copy to “fix” it. Recover from an external backup/original source and investigate how the immutable file changed.
