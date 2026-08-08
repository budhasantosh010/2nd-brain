# REVIEW POLICY — Human Attention Only for Real Ambiguity/Risk

Review exists to preserve trustworthy automation without making the user approve routine filing.

## Requires review

Stage changes when they can alter meaning or current truth and evidence is ambiguous: concept merges, ambiguous decision supersession, important ambiguous project-state changes, major hierarchy restructuring, and identity interpretation changes.

Routine reversible additions—preservation, records, provisional knowledge/links, generated indexes/briefs/logs, knowledge gaps—do not require review.

Level 3 destructive/external actions remain blocked; a review item does not automatically authorize them.

## Review item fields

Each item carries review ID, type, risk, status, creation time, operation ID, affected paths, decision, proposal, reason, evidence, current state, proposed state, risks, rollback, and recommendation.

## Priority and expiration

Risk and user impact determine priority. Review items may expire when their operation preconditions/hashes no longer match current canonical state. Expiration means regenerate/reassess rather than blindly apply a stale proposal.

## Approval

Approval is tied to the exact reviewed operation and preconditions. Before applying, recheck expected hashes and policy, then apply through the transaction manager. Mark applied only after successful commit/ledger update.

## Rejection

Rejection records the decision and reason where provided. It must not silently delete the proposal history. Rejected operations are not retried unchanged.

## Rollback

Applied reviewed changes use the same operation history/backups as other canonical writes. Rollback restores previous file state and corresponding structured state where supported, while preserving the operation ledger.

## Dashboard

`00 Home/Needs Review.md` is generated from pending review items. The user may approve/reject by CLI/MCP-safe workflow or by an explicit decision field that the daemon recognizes. The dashboard itself is a view, not the canonical review database.
<!-- PHASE25_FINAL -->
## Phase 2.5 hardening

Advisory restructuring proposals require a separate concrete reversible operation before application. Approved meaning changes retain transaction and resolution history.
