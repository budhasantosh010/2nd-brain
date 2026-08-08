# Transaction Recovery

Phase 2.5 transactions declare both file targets and bounded SQLite/FTS/vector mutation scopes. Before APPLYING, the manager persists file backups and database snapshots. A successful apply retains the operation history. Rollback restores the exact prior file + row/index scope and records a new compensating operation; it does not erase the original history.

Writer locking uses PID plus process-start identity so dead owners and PID reuse are distinguishable. Daemon startup clears stale daemon/writer locks and runs interrupted-transaction recovery before acquiring live ownership. Recovery must leave Markdown, SQLite, FTS, vectors and retrieval logically aligned.
