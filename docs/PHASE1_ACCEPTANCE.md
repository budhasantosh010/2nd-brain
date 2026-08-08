# Phase 1 Acceptance

Phase 1 proves that the local runtime vault can be generated and operated manually by an AI/human without relying on background automation.

## Gates

### P1-A — Foundation and privacy

- Python packaging and `second-brain` CLI exist.
- Public defaults and `.env.example` contain no credentials.
- `vault/` is runtime-only and ignored.
- `scripts/verify_public_repo.py` checks actual Git-tracked paths, not only ignore rules.
- CI is configured for Windows/Linux.

### P1-B — Vault architecture

`second-brain init` copies the tracked `vault-template/` only when the runtime vault does not already exist. Required files/directories and Obsidian configuration are validated. Existing personal files are never overwritten by init.

### P1-C — Operating contracts

`AGENTS.md` is canonical and all `10 System` contracts define ownership, ingestion, retrieval, schemas, source policy, linking, memory, permissions, egress, changes, verification, confidence, restructuring, automation, review and failure behavior. Prompt-injection containment is explicit.

### P1-D — Templates and schemas

Canonical note templates contain YAML metadata and are validated. Machine JSON Schema exports are generated from Pydantic models. Malformed required metadata fails validation rather than being silently accepted.

### P1-E — Projects, identity, skills

The public identity files contain no personal data. Project creation produces PROJECT/STATE/DECISIONS/OPEN LOOPS/CONTEXT/SOURCES/HANDOFF and work folders. Project state updates retain historical rows. All required Skills include purpose, trigger, inputs, procedure, verification, failure conditions, outputs, side effects, permission level and example.

### P1-F — Manual workflow

Without a daemon, the user/AI can:

1. run `second-brain ingest <path>` or process Inbox;
2. preserve/record/extract/index the source;
3. run configured mock/local/provider compilation;
4. search global knowledge;
5. retrieve source-backed evidence;
6. create/update project state and handoff through project/MCP tools.

Phase 1 acceptance evidence is the automated test suite plus successful runtime `init`, `doctor` and `verify` results recorded during release validation.
