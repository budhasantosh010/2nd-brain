# Backup and Recovery

`second-brain backup create [destination.zip]` builds a local `second-brain-backup-v1` archive with a `BACKUP_MANIFEST.json`, schema version, timestamp and SHA-256 for every included member. `second-brain backup verify <zip>` rejects missing, altered or unmanifested members and unsafe paths.

Durable content includes raw sources, canonical Markdown, manifests, resolution ledgers, project/gap histories, transaction/review provenance, config/trust rules and other non-generated vault content. Generated SQLite/FTS/vector/index/cache/log/runtime/lock/queue state and rebuildable maps/briefs/extractions are excluded. Recovery restores durable content, then runs migration/rebuild and verify.
