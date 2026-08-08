---
id: SKL-10965e8e-a2fa-58f2-b2a2-5a21dc3e8dbc
type: skill
title: Create Handoff
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 1
---

# Create Handoff

## Purpose
Produce a reliable cross-session resume artifact capturing exact project continuity.

## Trigger
End of a substantial work session, state transition, explicit handoff request, or nightly project maintenance.

## Inputs
PROJECT, STATE, decisions, open loops, recent changes/operations, relevant evidence.

## Procedure
Answer: what are we doing; where exactly are we; what completed; which decisions matter; what changed; what evidence exists; what is blocked; what happens next; what must not happen; how another AI should resume. Prefer current verified state, retain exact identifiers/paths/commits, and cite source/operation evidence.

## Verification
A cold-start session can resume without needing the original conversation and without mistaking old history for current truth.

## Failure Conditions
Current state is inconsistent/unknown or required evidence/identifiers cannot be verified.

## Outputs
Updated `HANDOFF.md` plus structured timestamp/provenance.

## Side Effects
Canonical project handoff update through transaction manager.

## Permission Level
Level 1 for evidence-backed synthesis.

## Example
Handoff records branch, final commit SHA, passed tests, remaining blocker, exact next command, and explicit work not to start.
