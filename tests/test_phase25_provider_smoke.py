from __future__ import annotations

from second_brain.config import load_config
from second_brain.paths import BrainPaths
from second_brain.providers.smoke import provider_smoke


def test_provider_smoke_reports_not_verified_when_no_real_provider_is_configured(
    isolated_brain: BrainPaths,
) -> None:
    result = provider_smoke(load_config(isolated_brain))
    assert result.provider == "none"
    assert result.credential_configured is False
    assert result.structured_generation_smoke == "NOT VERIFIED"
    assert result.real_provider_acceptance == "NOT VERIFIED"
    assert result.detail == "REAL PROVIDER ACCEPTANCE: NOT VERIFIED"


def test_mock_provider_structured_smoke_passes_but_is_not_real_acceptance(
    isolated_brain: BrainPaths,
) -> None:
    config = load_config(isolated_brain)
    config.ai.provider = "mock"
    result = provider_smoke(config)
    assert result.provider == "mock"
    assert result.sdk_available is True
    assert result.credential_configured is True
    assert result.health == "available"
    assert result.structured_generation_smoke == "PASS"
    assert result.real_provider_acceptance == "NOT VERIFIED"
