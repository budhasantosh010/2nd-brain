# Testing and Quality Gates

## Local developer checks

```text
uv sync --extra dev
uv run ruff check .
uv run mypy src/second_brain
uv run pytest -q
uv run python scripts/verify_public_repo.py
uv run python scripts/export_schemas.py
uv build
```

`second-brain doctor` and `second-brain verify` are runtime acceptance checks rather than replacements for the developer suite.

## Fixture policy

Tests use synthetic data only. Temporary runtime vaults are created outside the repository's personal `vault/`; fixtures deliberately include paths with spaces. No test should require a live cloud API or a real credential.

## Required behavior groups

- Bootstrap: exact structure, idempotence, no overwrite, paths with spaces.
- Ingestion: required text/document/spreadsheet/email formats and recursive folders.
- Preservation/dedupe: verified hash copies, duplicate idempotence, filename-content version distinction, mutation detection.
- Security: credential egress block, prompt injection containment, archive traversal, symlinks.
- Failure handling: raw evidence retained, job error/stage recorded.
- Knowledge: provisional creation, duplicate matching, staged meaning changes, contradictions, supersession.
- Projects: creation, state history, handoff, ambiguous updates.
- Retrieval: exact/semantic/hybrid, current/history, project scope, global discovery.
- Verification: citations, stale/superseded handling, contradiction surfacing, grounded refusal and gap creation.
- Transactions/review: expected-hash checks, writer lock, rollback, crash recovery, approve/reject.
- Maintenance: idempotent dated outputs, missed schedule recovery, watcher/Inbox automation.
- Rebuild: non-materialized structured knowledge and search/vector state restored.
- MCP: required tool registration, read access, safe proposals and protected-path blocks.
- Public safety: actual tracked-file scan.

## Retrieval benchmarks

`tests/fixtures/retrieval_benchmark.json` is the fixed synthetic benchmark format. Each case declares a question, expected source/object evidence, required facts and forbidden unsupported facts. `tests/test_retrieval_benchmark.py` computes Recall@K, MRR, citation accuracy, unsupported-answer rate and current-state accuracy. Thresholds are explicit in the test, not inferred from a demo.

## CI

GitHub Actions runs on Windows and Linux using Python 3.12. It installs dev dependencies, checks public-repo safety, validates schemas/templates, runs Ruff, mypy, pytest and a package build. Live cloud calls are forbidden; deterministic/mock providers are used.
