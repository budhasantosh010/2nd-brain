"""CI validation for schemas and the tracked vault template."""

from __future__ import annotations

import json
from pathlib import Path

from second_brain.validation import validate_vault


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors: list[str] = []
    schema_paths = sorted((root / "schemas").glob("*.schema.json"))
    if not schema_paths:
        errors.append("No exported JSON schemas found under schemas/.")
    for path in schema_paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.relative_to(root)}: invalid JSON: {exc}")
            continue
        if not isinstance(value, dict) or value.get("type") != "object":
            errors.append(f"{path.relative_to(root)}: expected top-level JSON Schema object type")

    report = validate_vault(root / "vault-template")
    errors.extend(report.errors)
    if errors:
        print("Project validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        f"Project validation passed: {len(schema_paths)} schemas; "
        f"{report.checked} templates/skills checked."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
