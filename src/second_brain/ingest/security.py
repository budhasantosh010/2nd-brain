"""Local source security, secret detection and egress classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from second_brain.exceptions import SecurityViolation
from second_brain.models import Sensitivity

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


def classify_source(path: Path, *, scan_secrets: bool = True) -> SecurityClassification:
    reasons: list[str] = []
    name = path.name.lower()
    if name in SECRET_FILENAMES or (name.startswith(".env") and name != ".env.example"):
        reasons.append("credential-filename")
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        reasons.append("credential-file-extension")

    if scan_secrets and path.is_file():
        try:
            with path.open("rb") as handle:
                sample = handle.read(2 * 1024 * 1024)
        except OSError:
            sample = b""
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(sample):
                reasons.append(label)

    if reasons:
        return SecurityClassification(Sensitivity.BLOCKED, tuple(sorted(set(reasons))), False)
    # Unknown imports default to local-only/private.
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
