"""Config tests: env-driven provider + cost/latency knobs (OQ#2 mechanism)."""

import pytest

from reviewer_target_o_meter.config import Config


def test_config_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        Config.from_env()


def test_config_defaults_for_model_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    cfg = Config.from_env()
    assert cfg.api_key == "sk-test"
    assert cfg.model == "nvidia/nemotron-3-super-120b-a12b:free"
    assert cfg.base_url == "https://openrouter.ai/api/v1"


def test_config_env_overrides_model_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL", "vendor/paid-slug")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://gateway.example/v1")
    cfg = Config.from_env()
    assert cfg.model == "vendor/paid-slug"
    assert cfg.base_url == "https://gateway.example/v1"


def test_config_cost_latency_knob_constants() -> None:
    # OQ#2 mechanism + the ~5-min wall-clock NFR — central, single-source knobs.
    assert Config.recursion_limit == 40
    assert Config.max_iterations == 12
    assert Config.run_timeout == 120


def test_config_attribution_headers_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    cfg = Config.from_env()
    headers = cfg.attribution_headers
    assert "HTTP-Referer" in headers and "X-Title" in headers


def test_config_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    cfg = Config.from_env()
    with pytest.raises(ValidationError):
        cfg.model = "other"  # type: ignore[misc]
