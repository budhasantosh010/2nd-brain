# KNOWLEDGE SCHEMA — Canonical Types and Metadata

All canonical Markdown notes use validated YAML frontmatter. Machine schemas live in the product repository under `schemas/` and are exported from typed models where applicable.

## Common fields

Canonical note types share, where applicable:

```yaml
id:
type:
title:
status:
created_at:
updated_at:
source_ids: []
project_ids: []
tags: []
```

IDs are stable and never depend solely on filenames. Sources use content-addressed `SRC-<sha256-prefix>` IDs with full SHA256 retained. Other examples: `KNO-`, `CLM-`, `DEC-`, `PRJ-`, `ENT-`, `SKL-`, `RVW-`, and `OP-` plus UUID.

## Types

### source
Deterministic record describing preserved evidence. Required fields include source type, original filename/path, content hash, size, creation/import time, processing status, authority, sensitivity, project IDs, topics, and raw/extracted location.

### concept
Reusable compiled understanding. Contains summary, current understanding, evidence, important claims, connections, contradictions, implications, source list, and change history. New auto-generated concepts are provisional.

### claim
Atomic source-backed statement. Every extracted claim exists structurally in SQLite/ledger. Materialize Markdown only when important, reusable, controversial, contradicted, decision-critical, or frequently retrieved. Fields include statement, evidence state, source/locator, validity window, supersession, and projects.

### decision
A choice plus context, alternatives, reasoning, assumptions, evidence, consequences, reversal conditions, and history. Decisions are never silently overwritten; supersession links old and new.

### project
Stable purpose: goal, desired outcome, success criteria, scope, constraints, related areas, important resources.

### project-state
Current operational truth: current state, last completed, current work, next action, blockers, open questions, latest verified evidence, last verified timestamp. Historical state remains in history/ledger.

### entity
A person, company, product, tool, technology, or other named entity with aliases, evidence, projects, and relationships.

### skill
A reusable operating procedure containing Purpose, Trigger, Inputs, Procedure, Verification, Failure Conditions, Outputs, Side Effects, Permission Level, and Example.

### brief
Generated daily/weekly/monthly/project synthesis. Briefs are views over canonical state, not replacements for sources or project files.

### review-item
A staged risky change with risk, status, operation ID, affected paths, proposal, reason, evidence, current/proposed state, risks, rollback, recommendation, and explicit decision.

### question
An answered or unresolved question, including retrieval attempts, expected evidence, and resolution link where available.

### lesson
A reusable conclusion backed by sources and context, with applicability limits and contradictions.

### framework
A structured reusable model or method with assumptions, steps, evidence, use cases, and limitations.

### anti-pattern
A recurring harmful/ineffective pattern with evidence, detection cues, consequences, and alternatives.

## Evidence state

Use `verified`, `supported`, `provisional`, `uncertain`, `contradicted`, or `stale`. Numeric scores are ranking aids only and cannot replace evidence state.
