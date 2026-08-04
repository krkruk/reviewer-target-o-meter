"""Live logging smoke test (Phase 4) — breadcrumbs + preview fire in the real run.

The automated bridge between the offline CLI assertions (which mock the graph)
and the manual GHA run: invoke the REAL CLI via ``CliRunner`` against the
consumer/sample checkout with a live ``OPENROUTER_API_KEY`` and assert the INFO
breadcrumbs + Markdown preview appear in ``result.output`` while ``result.stdout``
stays the pure JSON contract. Does NOT post (no ``GITHUB_TOKEN``).

Opt-in via ``SMOKE=1`` (the existing gate in ``conftest.py``); run via
``SMOKE=1 OPENROUTER_API_KEY=… make llm-test``. Points at ``$CONSUMER_REPO``
(default ``tests/fixtures/sample-repo``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reviewer_target_o_meter import cli as cli_mod

pytestmark = pytest.mark.smoke

runner = CliRunner()


def _target_repo() -> Path:
    return Path(os.environ.get("CONSUMER_REPO", "tests/fixtures/sample-repo")).resolve()


def test_live_cli_emits_breadcrumbs_and_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real agentic run surfaces the INFO trace + Markdown preview on stderr."""
    repo = _target_repo()
    if not repo.is_dir():
        pytest.skip(f"target checkout not found at {repo} (set CONSUMER_REPO)")
    # The smoke gate already requires OPENROUTER_API_KEY to be useful; confirm it.
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set — live run can't proceed")
    # Ensure stdout (non-posting) mode: no PR env vars.
    for var in ("PR_NUMBER", "GITHUB_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(var, raising=False)

    result = runner.invoke(cli_mod.app, [str(repo)])

    assert result.exit_code in (0, 1), result.output  # advisory; never a crash

    # (a) Representative INFO breadcrumbs appear in the stderr trace.
    out = result.output.lower()
    assert "review start" in out, f"missing 'review start' breadcrumb; output={result.output!r}"
    assert "diff computed" in out, f"missing 'diff computed' breadcrumb; output={result.output!r}"
    assert "review complete" in out, f"missing 'review complete' breadcrumb; output={result.output!r}"

    # (b) The Markdown preview header appears in the stderr trace.
    assert "# reviewer-target-o-meter" in result.output, (
        f"missing Markdown preview header; output={result.output!r}"
    )

    # (c) stdout is valid JSON and is uncontaminated by the stderr trace/preview.
    payload = json.loads(result.stdout)
    assert "findings" in payload
    assert "# reviewer-target-o-meter" not in result.stdout
    assert "review start" not in result.stdout.lower()
