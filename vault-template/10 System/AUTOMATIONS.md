# AUTOMATIONS — Continuous and Recoverable Maintenance

All schedules are configurable and interpreted in `Asia/Dubai` by default. The system must not assume the machine is continuously online.

## Continuous ingestion

When enabled, the daemon watches `01 Inbox`, settles new files/folders, and places durable jobs into the processing queue. Restarting the daemon must not duplicate already preserved sources.

## Nightly compilation

Nightly maintenance processes outstanding inbox work, retries `NEEDS_AI` when appropriate, compiles pending knowledge, rebuilds/refreshes indexes, detects contradictions and stale project state, attempts knowledge-gap resolution, updates handoffs/operations dashboards, generates the next daily brief, and samples raw-source integrity.

## Daily brief

Generate `08 Briefs/Daily/YYYY-MM-DD.md` containing Main Priority, Active Projects, Current State, Next Actions, Open Loops, New Important Knowledge, Knowledge Gaps, Needs Review, and Potentially Stalled Work. Keep it concise and source-derived.

## Weekly audit

Find orphan knowledge, duplicate concepts, conflicting claims, unresolved reviews, stale projects, projects without a next action, dead links, repeated processing failures, retrieval failures, and restructuring candidates. Generate weekly synthesis.

## Monthly synthesis

Identify completed/abandoned projects, recurring patterns and mistakes, emerging knowledge clusters, stale assumptions, and higher-level structural proposals. Archive where policy permits; never auto-delete old knowledge.

## Missed-job recovery

Persist last successful run timestamps. On daemon startup, determine which enabled scheduled routine should have run while the machine was offline. Run the missed routine once when appropriate, record recovery, and advance its last-run marker. Maintenance routines must be idempotent so recovery does not multiply briefs or state changes.
