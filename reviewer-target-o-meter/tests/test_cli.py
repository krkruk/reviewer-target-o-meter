"""CLI tests — the console command prints valid FindingsReport JSON + advisory exit.

The graph is mocked (offline) so these never hit OpenRouter. Covers plan criteria
3.3 (bare console command) and the make/make.sh delegations (3.4) are verified
via Makefile invocation in the phase-end check.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from reviewer_target_o_meter import cli as cli_mod
from reviewer_target_o_meter.findings import (
    Dimension,
    Finding,
    FindingsReport,
    Impact,
    Severity,
)

runner = CliRunner()


def _flagged_report() -> FindingsReport:
    return FindingsReport(findings=[Finding(
        file="src/app.py", line=3, severity=Severity.CRITICAL, impact=Impact.HIGH,
        dimension=Dimension.SECURITY, title="SQLi", detail="concat of attacker input",
    )])


def _clean_report() -> FindingsReport:
    return FindingsReport(findings=[], summary="nothing flagged")


def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")


def test_cli_prints_valid_report_json_and_advisory_exit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch)
    monkeypatch.setattr(cli_mod, "run_review", lambda cfg, inputs: _flagged_report())

    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])

    assert result.exit_code == 1, result.output  # flagged -> advisory 1
    payload = json.loads(result.stdout)
    assert "findings" in payload
    assert len(payload["findings"]) == 1
    # F{n} ids are injected during serialization; no `id` on the model itself.
    assert payload["findings"][0]["id"] == "F1"
    assert payload["exit_code"] == 1


def test_cli_exits_zero_when_nothing_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    monkeypatch.setattr(cli_mod, "run_review", lambda cfg, inputs: _clean_report())

    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["findings"] == []
    assert payload["exit_code"] == 0


def test_cli_errors_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])
    # Typer surfaces the ValueError (carrying the var name) as a non-zero exit.
    assert result.exit_code != 0
    message = str(result.exception)
    assert "OPENROUTER_API_KEY" in message  # the variable name, never a value


# --- Phase 5: env-driven mode switch (post / fallback / stdout) ---------------


def _set_pr_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("PR_NUMBER", "7")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")


def test_cli_posts_comment_when_pr_env_set_then_exits_advisory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With PR_NUMBER+GITHUB_TOKEN+GITHUB_REPOSITORY set, the CLI renders the
    report, posts it once via post_comment, and exits with the advisory code."""
    _set_pr_env(monkeypatch)
    monkeypatch.setattr(cli_mod, "run_review", lambda cfg, inputs: _flagged_report())
    monkeypatch.setattr(cli_mod, "compute_diff", lambda *a, **k: "diff")
    monkeypatch.setattr(cli_mod, "load_context", lambda *a, **k: None)

    calls: list[dict] = []

    def _capture(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(cli_mod, "post_comment", _capture)
    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])

    assert result.exit_code == 1, result.output  # flagged -> advisory 1
    assert len(calls) == 1, (
        f"post_comment called {len(calls)} times; expected 1; "
        f"output={result.output!r}"
    )
    call = calls[0]
    assert call["owner"] == "owner"
    assert call["repo"] == "repo"
    assert call["pr_number"] == 7
    assert "reviewer-target-o-meter" in call["body"]
    assert "SQLi" in call["body"]  # the rendered finding is in the posted body


def test_cli_falls_back_to_stdout_when_post_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A posting failure must degrade to stdout JSON + a WARNING, never crash CI."""
    _set_pr_env(monkeypatch)
    monkeypatch.setattr(cli_mod, "run_review", lambda cfg, inputs: _flagged_report())
    monkeypatch.setattr(cli_mod, "compute_diff", lambda *a, **k: "diff")
    monkeypatch.setattr(cli_mod, "load_context", lambda *a, **k: None)

    def _boom(**kwargs):
        raise RuntimeError("post failed")

    monkeypatch.setattr(cli_mod, "post_comment", _boom)
    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])

    # Degrade: still exits advisory (not a crash), and emits stdout JSON.
    assert result.exit_code == 1, result.output
    assert "WARNING" in result.output or "posting failed" in result.output
    payload = json.loads(result.stdout)
    assert len(payload["findings"]) == 1


def test_cli_stdout_only_when_no_pr_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without PR env vars, the CLI emits stdout JSON (today's behavior)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.delenv("PR_NUMBER", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setattr(cli_mod, "run_review", lambda cfg, inputs: _flagged_report())
    monkeypatch.setattr(cli_mod, "compute_diff", lambda *a, **k: "diff")
    monkeypatch.setattr(cli_mod, "load_context", lambda *a, **k: None)

    posted: list = []
    monkeypatch.setattr(cli_mod, "post_comment", lambda **kw: posted.append(kw))
    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])

    assert result.exit_code == 1, result.output
    assert posted == [], "no post attempt without PR env"
    payload = json.loads(result.stdout)
    assert payload["findings"][0]["id"] == "F1"
