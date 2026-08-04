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
    assert cfg.model == "deepseek/deepseek-v4-flash-0731"
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


# --- Phase 5: env-driven mode switch (post_to_github) -------------------------


def _set_pr_env(monkeypatch: pytest.MonkeyPatch, *, pr: str | None = "7", token: str | None = "tok", repo: str | None = "owner/repo") -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    for var, val in (("PR_NUMBER", pr), ("GITHUB_TOKEN", token), ("GITHUB_REPOSITORY", repo)):
        if val is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, val)


def test_post_to_github_true_when_all_three_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_pr_env(monkeypatch)
    cfg = Config.from_env()
    assert cfg.pr_number == 7
    assert cfg.github_repository == "owner/repo"
    assert cfg.post_to_github is True


def test_post_to_github_false_when_pr_number_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_pr_env(monkeypatch, pr=None)
    assert Config.from_env().post_to_github is False


def test_post_to_github_false_when_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_pr_env(monkeypatch, token=None)
    assert Config.from_env().post_to_github is False


def test_post_to_github_false_when_repository_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_pr_env(monkeypatch, repo=None)
    assert Config.from_env().post_to_github is False


def test_post_to_github_false_when_pr_number_non_integer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # A non-integer PR_NUMBER parses to None (forgiving) + a WARNING; the
    # switch stays False rather than crashing the pipeline.
    _set_pr_env(monkeypatch, pr="not-a-number")
    with caplog.at_level("WARNING", logger="reviewer_target_o_meter"):
        cfg = Config.from_env()
    assert cfg.pr_number is None
    assert cfg.post_to_github is False
    assert "WARNING" in caplog.text and "PR_NUMBER" in caplog.text


def test_config_reads_base_ref_and_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("BASE_REF", "develop")
    monkeypatch.setenv("GITHUB_API_URL", "https://gh.example/api")
    cfg = Config.from_env()
    assert cfg.base_ref == "develop"
    assert cfg.github_api_url == "https://gh.example/api"


def test_github_token_never_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_pr_env(monkeypatch, token="sk-secret-tok")
    cfg = Config.from_env()
    assert "sk-secret-tok" not in repr(cfg)


def test_base_ref_defaults_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.delenv("BASE_REF", raising=False)
    assert Config.from_env().base_ref is None
