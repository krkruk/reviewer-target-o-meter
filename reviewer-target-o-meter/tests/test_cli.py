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


def test_cli_emits_optional_findings_with_O_ids_in_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stdout JSON carries optional_findings with O{n} ids (separate counter
    from F{n}); they never affect exit_code."""
    _set_env(monkeypatch)
    report = FindingsReport(
        findings=[Finding(
            file="src/app.py", line=3, severity=Severity.CRITICAL, impact=Impact.HIGH,
            dimension=Dimension.SECURITY, title="SQLi", detail="concat")],
        optional_findings=[Finding(
            file="src/app.py", line=1, severity=Severity.OBSERVATION, impact=Impact.LOW,
            dimension=Dimension.MAINTAINABILITY, title="style note", detail="nit")],
    )
    monkeypatch.setattr(cli_mod, "run_review", lambda cfg, inputs: report)

    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])
    payload = json.loads(result.stdout)
    assert "optional_findings" in payload
    assert len(payload["optional_findings"]) == 1
    assert payload["optional_findings"][0]["id"] == "O1"
    # Exit driven only by main findings (the CRITICAL → exit 1); optional doesn't add.
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


# --- Phase 2: INFO breadcrumbs + the Markdown preview --------------------------


def test_cli_emits_info_breadcrumbs_to_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Representative INFO breadcrumbs appear in result.output (the stderr trace)."""
    _set_env(monkeypatch)
    monkeypatch.setattr(cli_mod, "run_review", lambda cfg, inputs: _flagged_report())
    monkeypatch.setattr(cli_mod, "compute_diff", lambda *a, **k: "diff")
    monkeypatch.setattr(cli_mod, "load_context", lambda *a, **k: None)

    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])

    assert result.exit_code == 1, result.output
    # Breadcrumbs are metadata-only step markers; the exact phrasing is prompt-
    # resident but these tokens are the contract the smoke + GHA run lean on.
    assert "review start" in result.output.lower()
    assert "diff computed" in result.output.lower()
    assert "review complete" in result.output.lower()


def test_cli_dumps_redacted_env_at_debug_and_uses_base_ref_override_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At LOG_LEVEL=DEBUG the CLI dumps the redacted env (tokens never echoed) and
    labels the base-ref override field correctly instead of the misleading
    ``base_ref=None`` (the *resolved* base is diff.py's line, not the CLI's)."""
    _set_env(monkeypatch)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_secret_value")
    monkeypatch.setenv("PR_NUMBER", "28")
    monkeypatch.setattr(cli_mod, "run_review", lambda cfg, inputs: _clean_report())
    monkeypatch.setattr(cli_mod, "compute_diff", lambda *a, **k: "diff")
    monkeypatch.setattr(cli_mod, "load_context", lambda *a, **k: None)

    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])

    assert result.exit_code == 0, result.output
    out = result.output
    # Env dump present: the token var is named but redacted; a non-secret is visible.
    assert "OPENROUTER_API_KEY" in out
    assert "<redacted,set>" in out
    assert "PR_NUMBER" in out and "28" in out
    # The secret value NEVER appears anywhere in the trace.
    assert "ghs_secret_value" not in out
    # The misleading `base_ref=None` label is replaced by the override label.
    assert "base_ref_override=" in out
    assert "base_ref=None" not in out


def test_cli_emits_markdown_preview_to_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """The render_comment() Markdown is echoed to stderr before the post-vs-stdout branch."""
    _set_env(monkeypatch)
    monkeypatch.setattr(cli_mod, "run_review", lambda cfg, inputs: _flagged_report())
    monkeypatch.setattr(cli_mod, "compute_diff", lambda *a, **k: "diff")
    monkeypatch.setattr(cli_mod, "load_context", lambda *a, **k: None)

    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])

    assert result.exit_code == 1, result.output
    # The preview is the exact render_comment() payload: header + finding title.
    assert "# reviewer-target-o-meter" in result.output
    assert "SQLi" in result.output  # the fixture finding's title


def test_cli_stdout_stays_pure_json_with_trace_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stdout is uncontaminated by the stderr trace + preview across the CLI cases."""
    _set_env(monkeypatch)
    monkeypatch.setattr(cli_mod, "run_review", lambda cfg, inputs: _flagged_report())
    monkeypatch.setattr(cli_mod, "compute_diff", lambda *a, **k: "diff")
    monkeypatch.setattr(cli_mod, "load_context", lambda *a, **k: None)

    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])

    assert result.exit_code == 1, result.output
    # stdout parses as JSON and carries the report — never the trace or preview.
    payload = json.loads(result.stdout)
    assert payload["findings"][0]["id"] == "F1"
    assert "# reviewer-target-o-meter" not in result.stdout
    assert "review start" not in result.stdout.lower()


def test_cli_log_lines_are_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """No input body text (diff/context/plan/report) appears in the log lines.

    Metadata-only invariant (AGENTS.md §e): logs carry sizes/counts/refs, never
    the diff/context/plan/report bodies. The report body is shown once via the
    dedicated Markdown preview, intentionally.
    """
    _set_env(monkeypatch)
    secret_diff_body = "SUPER_SECRET_DIFF_CONTENT_XYZ"
    secret_context_body = "SUPER_SECRET_CONTEXT_BODY_ZZZ"
    monkeypatch.setattr(cli_mod, "run_review", lambda cfg, inputs: _flagged_report())
    monkeypatch.setattr(cli_mod, "compute_diff", lambda *a, **k: secret_diff_body)
    monkeypatch.setattr(cli_mod, "load_context", lambda *a, **k: secret_context_body)

    result = runner.invoke(cli_mod.app, ["tests/fixtures/sample-repo"])

    assert result.exit_code == 1, result.output
    # The log lines (everything before the Markdown preview header) must not
    # carry the diff/context bodies. The preview header marks where the
    # intended report-body echo begins.
    preview_idx = result.output.find("# reviewer-target-o-meter")
    log_region = result.output[:preview_idx] if preview_idx != -1 else result.output
    assert secret_diff_body not in log_region
    assert secret_context_body not in log_region
