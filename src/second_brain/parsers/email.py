"""RFC822 .eml parser using Python's standard email package."""

from __future__ import annotations

from contextlib import suppress
from email import policy
from email.parser import BytesParser
from pathlib import Path

from second_brain.models import ParsedSegment
from second_brain.parsers.base import BaseParser


class EmailParser(BaseParser):
    extensions = frozenset({".eml"})

    def parse(self, path: Path, source_id: str):  # type: ignore[no-untyped-def]
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        headers = [
            f"Subject: {message.get('subject', '')}",
            f"From: {message.get('from', '')}",
            f"To: {message.get('to', '')}",
            f"Date: {message.get('date', '')}",
        ]
        segments = [
            ParsedSegment(
                segment_id=f"{source_id}:seg:0",
                text="\n".join(headers),
                locator="headers",
                position=0,
            )
        ]
        body_parts: list[str] = []
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                    try:
                        body_parts.append(str(part.get_content()))
                    except (LookupError, UnicodeDecodeError):
                        continue
        else:
            with suppress(LookupError, UnicodeDecodeError):
                body_parts.append(str(message.get_content()))
        if body_parts:
            segments.append(
                ParsedSegment(
                    segment_id=f"{source_id}:seg:1",
                    text="\n\n".join(body_parts).strip(),
                    locator="message body",
                    position=1,
                )
            )
        doc = self.document(path, source_id, segments, mime_type="message/rfc822")
        subject = str(message.get("subject", "")).strip()
        if subject:
            doc.title = subject
        return doc
