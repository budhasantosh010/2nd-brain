# Privacy and Data Ownership

## Local ownership by default

Canonical brain data belongs to the user as ordinary local files plus local structured state. Obsidian, an AI vendor, an embedding implementation, SQLite or an MCP client is not the sole owner of the knowledge.

The public Git repository contains product code, templates, schemas, tests, documentation and default configuration. The personal runtime vault is `vault/` and is Git-ignored.

## What is local runtime data

Examples include imported documents, chat exports, customer material, screenshots, raw audio/video, source records, personal identity notes, project knowledge, generated briefs, SQLite files, vector indexes, manifests, ledgers, logs, caches and AI results tied to personal sources.

These must not be committed to the public repository.

## AI egress

The default configuration is:

- AI provider: none
- cloud AI: disabled
- semantic embeddings: local
- unknown imports: private/local-only

A cloud adapter is optional. Cloud use requires explicit runtime configuration and a compatible source egress classification. Credential-like sources are blocked by the secret scanner. Source text is not logged merely because a model call occurs.

## Logs

Runtime logs stay under `vault/.brain/logs`. They record operational metadata such as operation/job/source IDs, stage, duration, provider/model, cache/result/error class. Secret-like values and explicitly sensitive keys are redacted.

## Backups and deletion

Operation history lives locally under `vault/.brain/history`. V1 does not automatically delete old knowledge or raw sources. Windows uninstall removes integration/optionally the environment but deliberately leaves the personal vault intact.

## Public-template identity

The public `09 Identity` files are blank/generic templates. Real profile/goals/preferences/working style/constraints belong only in runtime copies populated during user onboarding.
