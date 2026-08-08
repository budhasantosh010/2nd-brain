---
id: SKL-264ed09b-6474-5a84-9182-4ffd601dff1b
type: skill
title: Compile Knowledge
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 1
---

# Compile Knowledge

## Purpose
Convert preserved/extracted source content into structured, revisable concepts, claims, entities, decisions, project links, tasks, and questions.

## Trigger
A source reaches deterministic extraction and a configured AI provider is available, or a queued `NEEDS_AI` job is retried.

## Inputs
Parsed source/segments, existing relevant knowledge/project context, provider abstraction, schemas, permission/review policy.

## Procedure
Retrieve likely existing matches; ask the provider for structured output only; validate against Pydantic/schema; classify each candidate as NEW, UPDATE, DUPLICATE, CONFLICT, SUPERSEDES, or UNRELATED; create a change plan; auto-apply only low-risk provisional additions; stage ambiguous meaning changes; record provenance and reindex.

## Verification
No unvalidated provider JSON reaches canonical mutation. Every claim has source provenance and every created knowledge item begins provisional unless evidence conditions justify more.

## Failure Conditions
Provider unavailable, invalid structured output after bounded retry, missing source provenance, unsafe proposed mutation, or transaction failure.

## Outputs
Validated extraction, knowledge/relationship rows, materialized important notes, review proposals, updated indexes.

## Side Effects
May create provisional canonical notes through the transaction manager and pending review items.

## Permission Level
Level 1 for new provisional additions; Level 2 for merges/supersession/restructuring.

## Example
A new research PDF yields three claims, one existing concept update candidate, and one contradiction; the new claims are stored while the risky merge is staged.
