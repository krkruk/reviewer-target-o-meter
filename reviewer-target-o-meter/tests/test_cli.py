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
