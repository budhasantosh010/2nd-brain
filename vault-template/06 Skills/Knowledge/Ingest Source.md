---
id: SKL-4783658d-21fd-546b-92bb-b3bb289fb419
type: skill
title: Ingest Source
status: active
created_at: 2000-01-01T00:00:00+00:00
updated_at: 2000-01-01T00:00:00+00:00
source_ids: []
project_ids: []
tags: []
permission_level: 1
---

# Ingest Source

## Purpose
Safely ingest one explicit file or directory while preserving evidence before interpretation.

## Trigger
Explicit `brain_ingest`, CLI `second-brain ingest <path>`, or one item selected from the Inbox queue.

## Inputs
Source path and current security/egress/configuration policy.

## Procedure
Validate confinement/symlink rules; hash bytes; detect exact duplicate; classify sensitivity; copy into canonical Raw storage; verify copied hash; write manifest/source record; parse and segment with locators; index deterministic extraction; optionally compile through an allowed provider; verify resulting provenance.

## Verification
Canonical copy SHA256 equals original SHA256 and the source record references the same full hash and stable `SRC-` ID.

## Failure Conditions
Source disappears during read, hash mismatch, unsafe path, unsupported extraction, parser crash, or failed transaction.

## Outputs
Source record, raw copy, extraction/segments, processing state, index entries, optional compiler result.

## Side Effects
Creates canonical evidence and generated index state. Never rewrites original source bytes.

## Permission Level
Level 1.

## Example
`second-brain ingest "C:\Research\paper.pdf"` preserves the PDF, stores page-located extraction, and returns its source ID.
