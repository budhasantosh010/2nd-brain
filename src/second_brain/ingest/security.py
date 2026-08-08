"""Local source security, secret detection and egress classification."""

from __future__ import annotations

import builtins
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from second_brain.exceptions import SecurityViolation
from second_brain.models import Sensitivity
from second_brain.paths import BrainPaths
from second_brain.storage.durable import append_jsonl_event, atomic_json

SECRET_FILENAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "secrets.json",
    "passwords.csv",
    "passwords.json",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private-key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("openai-like-key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google-api-key", re.compile(rb"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("authorization-bearer", re.compile(rb"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._~+/-]{12,}")),
    ("password-assignment", re.compile(rb"(?i)(?:password|passwd|secret|token)\s*[=:]\s*[^\s]{8,}")),
)


@dataclass(frozen=True, slots=True)
class SecurityClassification:
    sensitivity: Sensitivity
    reasons: tuple[str, ...]
    cloud_egress_allowed: bool


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


class TrustStore:
    """Durable local trust rules. A trusted path only makes non-secret content cloud-eligible."""

    def __init__(self, paths: BrainPaths | None = None) -> None:
        self.paths = paths or BrainPaths.discover()
        self.path = self.paths.brain / "trust-rules.json"
        self.audit_path = self.paths.brain / "ledgers" / "egress-audit.jsonl"

    def list(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        values = payload.get("trusted_paths", []) if isinstance(payload, dict) else []
        return sorted({str(value) for value in values if str(value).strip()})

    def add(self, path: Path | str) -> builtins.list[str]:
        resolved = str(Path(path).expanduser().absolute())
        values = set(self.list())
        values.add(resolved)
        self._write(sorted(values))
        self._audit("trust_add", {"path": resolved})
        return self.list()

    def remove(self, path: Path | str) -> builtins.list[str]:
        resolved = str(Path(path).expanduser().absolute())
        values = set(self.list())
        values.discard(resolved)
        self._write(sorted(values))
        self._audit("trust_remove", {"path": resolved})
        return self.list()

    def trusted(self, path: Path) -> bool:
        return any(_is_under(path, Path(value)) for value in self.list())

    def _write(self, values: builtins.list[str]) -> None:
        atomic_json(
            self.path,
            {
                "schema_version": "trust-rules-v1",
                "trusted_paths": values,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

    def _audit(self, action: str, metadata: dict[str, Any]) -> None:
        event_id = f"EGR-{os.getpid()}-{datetime.now(UTC).timestamp()}"
        append_jsonl_event(
            self.audit_path,
            {
                "event_id": event_id,
                "action": action,
                "timestamp": datetime.now(UTC).isoformat(),
                "metadata": metadata,
            },
            event_id=event_id,
        )


def ensure_safe_input_path(path: Path, *, vault: Path, allow_symlink: bool = False) -> None:
    if path.is_symlink() and not allow_symlink:
        raise SecurityViolation(f"Symlink input rejected by policy: {path}")
    resolved = path.resolve(strict=True)
    vault_resolved = vault.resolve()
    machine_roots = (
        vault_resolved / ".brain",
        vault_resolved / "02 Sources",
        vault_resolved / "03 Knowledge",
        vault_resolved / "04 Projects",
        vault_resolved / "08 Briefs",
        vault_resolved / "12 Staging",
        vault_resolved / "99 Archive",
    )
    for root in machine_roots:
        if resolved == root or root in resolved.parents:
            raise SecurityViolation(f"Recursive brain self-ingestion rejected: {path}")


def classify_source(
    path: Path,
    *,
    scan_secrets: bool = True,
    explicit_cloud_allowed: bool = False,
    explicit_local_only: bool = False,
    trusted_paths: tuple[Path, ...] = (),
    ai_allowed_root: Path | None = None,
    local_only_root: Path | None = None,
) -> SecurityClassification:
    """Classify egress with strict precedence.

    blocked secret > sensitive > explicit deny/local-only lane > explicit allow > trusted path/
    AI Allowed lane > default local_only.
    """

    blocked_reasons: list[str] = []
    sensitive_reasons: list[str] = []
    name = path.name.lower()
    if name in SECRET_FILENAMES or (name.startswith(".env") and name != ".env.example"):
        blocked_reasons.append("credential-filename")
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        sensitive_reasons.append("credential-file-extension")

    if scan_secrets and path.is_file():
        try:
            with path.open("rb") as handle:
                sample = handle.read(2 * 1024 * 1024)
        except OSError:
            sample = b""
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(sample):
                blocked_reasons.append(label)

    if blocked_reasons:
        return SecurityClassification(
            Sensitivity.BLOCKED,
            tuple(sorted(set(blocked_reasons))),
            False,
        )
    if sensitive_reasons:
        return SecurityClassification(
            Sensitivity.SENSITIVE,
            tuple(sorted(set(sensitive_reasons))),
            False,
        )

    if explicit_local_only or (local_only_root is not None and _is_under(path, local_only_root)):
        return SecurityClassification(Sensitivity.LOCAL_ONLY, ("explicit-local-only",), False)
    if explicit_cloud_allowed:
        return SecurityClassification(Sensitivity.CLOUD_ALLOWED, ("explicit-cloud-allow",), True)
    if ai_allowed_root is not None and _is_under(path, ai_allowed_root):
        return SecurityClassification(Sensitivity.CLOUD_ALLOWED, ("trusted-ai-allowed-lane",), True)
    if any(_is_under(path, root) for root in trusted_paths):
        return SecurityClassification(Sensitivity.CLOUD_ALLOWED, ("trusted-path",), True)
    return SecurityClassification(Sensitivity.LOCAL_ONLY, ("private-by-default",), False)


def can_send_to_cloud(
    classification: SecurityClassification,
    *,
    allow_cloud_ai: bool,
    explicit_cloud_allowed: bool = False,
) -> bool:
    if classification.sensitivity in {Sensitivity.BLOCKED, Sensitivity.SENSITIVE}:
        return False
    return allow_cloud_ai and (
        explicit_cloud_allowed or classification.sensitivity == Sensitivity.CLOUD_ALLOWED
    )
