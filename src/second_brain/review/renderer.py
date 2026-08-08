"""Markdown renderers for staged review items and the dashboard."""

from __future__ import annotations

import yaml

from second_brain.models import ReviewItemModel


def render_review(item: ReviewItemModel) -> str:
    metadata = {
        "review_id": item.review_id,
        "type": item.type,
        "risk": item.risk,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
        "operation_id": item.operation_id,
        "affected_paths": item.affected_paths,
        "decision": item.decision,
    }
    yaml_text = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
    evidence = "\n".join(f"- {value}" for value in item.evidence) or "_No evidence listed._"
    return (
        f"---\n{yaml_text}\n---\n\n# Review {item.review_id}\n\n"
        f"## Proposal\n\n{item.proposal or '_Not supplied._'}\n\n"
        f"## Reason\n\n{item.reason or '_Not supplied._'}\n\n"
        f"## Evidence\n\n{evidence}\n\n"
        f"## Current State\n\n{item.current_state or '_Not supplied._'}\n\n"
        f"## Proposed State\n\n{item.proposed_state or '_Not supplied._'}\n\n"
        f"## Risks\n\n{item.risks or '_Not supplied._'}\n\n"
        f"## Rollback\n\n{item.rollback or 'Use the operation history/rollback command.'}\n\n"
        f"## Recommendation\n\n{item.recommendation or '_No recommendation._'}\n"
    )


def render_dashboard(items: list[ReviewItemModel]) -> str:
    pending = [item for item in items if item.status == "pending"]
    lines = [
        "# Needs Review",
        "",
        "> Generated from pending review items. Routine reversible work should not appear here.",
        "",
    ]
    if not pending:
        lines.append("_No pending review items._")
    else:
        for item in sorted(pending, key=lambda value: value.created_at):
            lines.extend(
                [
                    f"## {item.review_id} — {item.type}",
                    "",
                    f"- Risk: **{item.risk}**",
                    f"- Operation: `{item.operation_id}`",
                    f"- Proposal: {item.proposal}",
                    f"- Affected paths: {', '.join(item.affected_paths) or 'none'}",
                    "",
                ]
            )
    lines.extend(
        [
            "",
            "Use `second-brain review show <id>`, `approve <id>`, or `reject <id>`.",
            "",
        ]
    )
    return "\n".join(lines)
