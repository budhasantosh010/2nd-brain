# FAILURE HANDLING — No Silent Loss

Failures are expected operational states, not reasons to discard input or fabricate success.

## Required failure record

Every processing failure records:

- source/job/operation ID where available;
- failing stage;
- exception class/type;
- safe error message with secrets redacted;
- retry count;
- whether the failure appears transient/permanent;
- next action;
- timestamp and duration where available.

It must appear in Processing Status and/or `07 Operations/Failed Processing.md`.

## Preservation first

If raw preservation succeeded, later parser/AI/compiler/index failure must not delete the preserved source. If preservation itself fails, keep the original inbox item untouched and record that preservation is incomplete.

## Optional capability failures

No AI provider → deterministic ingestion/indexing proceeds and job becomes `NEEDS_AI` where compilation is pending. No OCR/vision for scanned PDF → preserve source and mark extraction limitation. No transcription/vision for audio/video/image → preserve and index deterministic metadata only.

## Retry

Retry only stages safe to repeat. Use durable job state and idempotent operations so retry cannot create duplicate sources or reapply a canonical operation. Exponential/backoff policy may be used for transient provider/filesystem errors.

## Transaction failure

Canonical multi-file/database writes must roll back prior file state and database transaction on failure. Interrupted operations are detected by recovery tooling using transaction/ledger state and backups.

## Security failures

Path traversal, unsafe symlink, archive escape, raw-source corruption, or secret-egress violations become quarantined/blocked security events rather than generic retries.

## User visibility

Never reduce a failure to a generic `OK`/`failed` status when actionable detail exists. Status views summarize stage, reason, retry/next action, and affected source without exposing secrets.
