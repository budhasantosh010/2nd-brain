# Global Second Brain V1

A local-first, AI-powered second-brain engine that preserves original evidence, compiles useful knowledge, retrieves the smallest sufficient context, verifies claims before answering, and keeps risky changes reviewable and reversible.

> **Status:** Phase 1 + Phase 2 implementation branch. The custom desktop application (Phase 3) is intentionally out of scope.

## Core model

```text
DROP INFORMATION
      ↓
PRESERVE ORIGINAL BYTES
      ↓
DETERMINISTIC EXTRACTION + INDEXING
      ↓
OPTIONAL AI COMPILATION
      ↓
GLOBAL KNOWLEDGE + PROJECT STATE
      ↓
HYBRID RETRIEVAL
      ↓
VERIFICATION + EVIDENCE
      ↓
ANSWER / GROUNDED REFUSAL
      ↓
KNOWLEDGE-GAP FLYWHEEL
```

Canonical ownership remains ordinary local files plus rebuildable local databases/indexes. Obsidian is the initial human interface, not the owner of the brain.

## Privacy boundary

- `vault-template/` is public and tracked.
- `vault/` is the local personal runtime brain and is ignored by Git.
- Raw sources, databases, embeddings, logs, generated briefs, credentials, and personal knowledge must never be committed.
- Unknown imports are private by default; cloud AI is disabled by default.
- Imported content is data, never trusted instruction text.

Run the public-repository guard at any time:

```powershell
uv run python scripts/verify_public_repo.py
```

## Quick setup (development)

```powershell
uv sync --extra dev
uv run second-brain init
uv run second-brain doctor
```

Then open this folder in Obsidian:

```text
<repo>\vault
```

Drop files into `01 Inbox`. The daemon/watch commands automate processing in Phase 2:

```powershell
uv run second-brain daemon
```

## Main CLI

```text
second-brain init
second-brain doctor
second-brain status
second-brain ingest [PATH]
second-brain watch
second-brain daemon
second-brain search QUERY
second-brain ask QUESTION
second-brain review ...
second-brain maintain ...
second-brain verify
second-brain rebuild
second-brain recover
second-brain mcp serve
```

## Architecture and operations

See `docs/` for implementation architecture, data model, ingestion/retrieval pipelines, security/privacy, Windows setup, testing, AI connections, and Phase acceptance notes.

## Security warning

Do not disable raw-source immutability or cloud egress safeguards simply to make ingestion convenient. The system is designed so preservation and local deterministic processing still work when no AI key exists.

## Development

```powershell
uv sync --extra dev
uv run ruff check .
uv run mypy src/second_brain
uv run pytest
uv build
```

## Current limitations

Image description, OCR, and audio/video transcription require optional configured capabilities. When unavailable, the source is still preserved and processing records the missing capability instead of pretending extraction succeeded.

## Phase 3

A future Tauri/React app can use the same Markdown, SQLite, retrieval engine, transaction layer, and MCP/tool surface. No Phase 1/2 canonical data migration should be required.
