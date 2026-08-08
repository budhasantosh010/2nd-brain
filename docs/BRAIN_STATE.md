# Durable vs Generated Brain State

Durable: raw source bytes; canonical Markdown; source manifests; canonical-resolution ledgers; append-only project-state and knowledge-gap histories; transaction/review history; provenance; trust/egress audit state.

Generated/rebuildable: SQLite tables, FTS, vectors, maps/briefs where regenerated, extracted caches, model caches, logs, queue runtime, heartbeat, locks and temporary files. Backups intentionally prioritize durable state and regeneration instructions over copying disposable indexes.
