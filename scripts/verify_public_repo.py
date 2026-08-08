"""Fail when Git tracks private/runtime content forbidden in the public repository."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PATH_PATTERNS = [
    re.compile(r"(^|/)vault/", re.IGNORECASE),
    re.compile(r"(^|/)\.brain/", re.IGNORECASE),
    re.compile(r"(^|/)private(?:-data)?/", re.IGNORECASE),
    re.compile(r"(^|/)raw-sources?/", re.IGNORECASE),
    re.compile(r"(^|/)logs?/", re.IGNORECASE),
    re.compile(r"(^|/)cache/", re.IGNORECASE),
]
FORBIDDEN_EXTENSIONS = {".db", ".sqlite", ".sqlite3", ".pem", ".p12", ".pfx"}
FORBIDDEN_FILENAMES = {".env", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
]
TEXT_EXTENSIONS = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ps1", ".sh"}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, text=True, capture_output=True, check=True
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def violations() -> list[str]:
    problems: list[str] = []
    for rel in tracked_files():
        path = Path(rel)
        posix = rel.replace("\\", "/")
        safe_template_config = posix == "vault-template/.brain/config.yaml"
        if not safe_template_config and any(
            pattern.search(posix) for pattern in FORBIDDEN_PATH_PATTERNS
        ):
            problems.append(f"forbidden runtime/private path tracked: {rel}")
        if path.suffix.lower() in FORBIDDEN_EXTENSIONS:
            problems.append(f"forbidden private/runtime extension tracked: {rel}")
        if path.name.lower() in FORBIDDEN_FILENAMES:
            problems.append(f"forbidden secret filename tracked: {rel}")

        full = ROOT / path
        if path.suffix.lower() in TEXT_EXTENSIONS and full.is_file():
            try:
                text = full.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if rel == "scripts/verify_public_repo.py":
                continue
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    problems.append(f"possible credential material tracked: {rel}")
                    break
    return sorted(set(problems))


def main() -> int:
    problems = violations()
    if problems:
        print("PUBLIC REPOSITORY SAFETY CHECK FAILED")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("Public repository safety check passed: no forbidden tracked runtime/private content.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
