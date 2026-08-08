"""Small deterministic classification helpers used around provider extraction."""

from __future__ import annotations

from second_brain.models import ParsedDocument


def source_purpose_hint(document: ParsedDocument) -> str:
    lowered = document.text[:4000].lower()
    if "decision:" in lowered:
        return "decision-bearing source"
    if "project:" in lowered or "next action" in lowered:
        return "project/operational source"
    if document.mime_type == "message/rfc822":
        return "conversation/email source"
    return "general knowledge source"
