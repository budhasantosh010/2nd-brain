---
id: SKL-bfca9687-a3e4-5cf3-8cd4-bb53f4e02381
type: skill
title: Update Project State
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 1
---

# Update Project State

## Purpose
Keep one concise current operational truth while preserving historical state and evidence.

## Trigger
Verified project progress, explicit user state update, completed work, new blocker, or accepted decision.

## Inputs
Current STATE hash/content, new evidence, project ID, decisions/open loops, permission policy.

## Procedure
Retrieve current state and relevant newest evidence; distinguish factual progress from interpretation; build replacement `STATE.md`; retain old version in operation history; update structured project-state history; stage ambiguous objective/meaning changes; atomically apply and refresh handoff/current-context views.

## Verification
State includes current state, last completed, current work, next action, blockers, open questions, latest verified evidence, and verification timestamp.

## Failure Conditions
Conflicting evidence, stale precondition, missing project, or major objective change without review.

## Outputs
New current STATE plus retained history and updated indexes.

## Side Effects
Canonical project-state write through transaction manager.

## Permission Level
Level 1 for unambiguous evidence-backed progress; Level 2 for ambiguous important change.

## Example
After tests and commit succeed, STATE moves the completed milestone to Last Completed and identifies the next implementation action.
