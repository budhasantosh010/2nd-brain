---
id: SKL-396dc0a7-c67d-5fd4-8df0-fe98028f2a31
type: skill
title: Check Contradictions
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 1
---

# Check Contradictions

## Purpose
Detect and preserve materially conflicting claims, decisions, or project-state evidence.

## Trigger
New claim/decision ingestion, verification, nightly/weekly maintenance, or explicit request.

## Inputs
Candidate statements, existing claims/decisions, dates, validity windows, source authority and provenance.

## Procedure
Retrieve likely opposing statements; distinguish contradiction from temporal change, scope difference, or supersession; create typed `contradicts` relationships when real conflict exists; update conflict records and operational dashboard without deleting either side.

## Verification
Each conflict cites both endpoints and their evidence; temporal/scope differences are described rather than mislabeled.

## Failure Conditions
No source support, purely linguistic negation without same scope, or missing temporal context.

## Outputs
Conflict records/links, contradiction dashboard updates, verification warnings.

## Side Effects
Creates reversible structured conflict metadata; may trigger review if resolving current canonical truth is ambiguous.

## Permission Level
Level 1 detection; Level 2 for ambiguous resolution/supersession.

## Example
An old decision says "use SQLite only" and a newer source says "move canonical storage to Postgres"; the system preserves conflict until a verified decision supersedes one.
