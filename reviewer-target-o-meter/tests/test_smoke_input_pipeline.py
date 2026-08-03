"""System-level smoke tests for the change-input pipeline (F-02).

These are the LIVE, opt-in (``SMOKE=1``) counterparts of the plan's *manual*
verification steps. Per the change brief, unit tests are not enough: each test
launches the real application against a real OpenRouter model and asserts the
reviewer's output actually reflects an issue planted in the fixture code.

Shared fixture: a tiny git repo is built per-test (via gitpython) containing a
known, unambiguous defect (SQL injection by string concatenation). The diff of
that defect against the base is exactly what ``compute_diff`` feeds the agent,
and the model is expected to surface the planted issue — proving the input
pipeline (real diff, not the inline fixture) drives a correct review.

Run via ``make llm-test`` (``SMOKE=1``); never in default CI.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import git
import pytest

from reviewer_target_o_meter.config import Config
from reviewer_target_o_meter.diff import compute_diff
from reviewer_target_o_meter.findings import FindingsReport, Severity
from reviewer_target_o_meter.graph import arun_review

pytestmark = pytest.mark.smoke


def _configure_identity(repo: git.Repo) -> None:
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Smoke Tester")
        cw.set_value("user", "email", "smoke@example.com")


def _build_buggy_repo(tmp_path: Path) -> Path:
    """Build a repo whose HEAD-vs-master diff plants a clear SQLi vulnerability.

    Base (``master``): a clean module. Feature work (HEAD): introduces string-
    concatenated SQL with an attacker-controlled ``user_id`` — a textbook
    correctness+security defect the model should flag.
    """
    repo = git.Repo.init(tmp_path)
    repo.git.symbolic_ref("HEAD", "refs/heads/master")
    _configure_identity(repo)

    clean = (
        "def query(user_id: int) -> str:\n"
        "    # parameterized — safe\n"
        "    return run(\"SELECT * FROM users WHERE id = %s\", (int(user_id),))\n"
    )
    (tmp_path / "app.py").write_text(clean)
    repo.index.add(["app.py"])
    base = repo.index.commit("base: parameterized query")

    # Advance HEAD past base so diff(master, HEAD) is non-empty.
    repo.git.checkout(base.hexsha)
    buggy = (
        "def query(user_id) -> str:\n"
        "    # NOTE: user_id is attacker-controlled\n"
        '    sql = "SELECT * FROM users WHERE id = " + user_id\n'
        "    return run(sql)\n"
    )
    (tmp_path / "app.py").write_text(buggy)
    repo.index.add(["app.py"])
    repo.index.commit("feature: inline SQL concat")
    return tmp_path


def test_compute_diff_feeds_real_diff_to_live_reviewer(tmp_path: Path) -> None:
    """Phase 1 manual check, automated: the real diff (not the fixture) drives a
    live review that surfaces the planted SQL injection.

    This is the system-level proof that the input pipeline works: build a repo
    with a known defect, compute its diff via ``compute_diff``, hand it to the
    real agent, and assert the reviewer actually flags the planted issue.
    """
    repo_path = _build_buggy_repo(tmp_path)

    # (1) The production diff path produces a real diff — not the inline fixture.
    diff = compute_diff(repo_path, base_ref="master")
    assert diff, "compute_diff returned an empty diff for a repo with a real change"
    assert "diff --git" in diff
    assert "app.py" in diff
    # The planted defect text must be in the diff the agent will see.
    assert "SELECT * FROM users" in diff
    assert "user_id" in diff

    # (2) Run the LIVE agent over that diff and confirm it reflects the issue.
    config = Config.from_env()
    inputs = {
        "repo_path": str(repo_path),
        "diff": diff,
        "context": None,
        "plan": None,
        "findings": [],
    }
    report = asyncio.run(arun_review(config, inputs))

    assert isinstance(report, FindingsReport)
    assert report.findings, (
        f"live reviewer returned no findings for a diff with an obvious SQLi; "
        f"summary={report.summary!r}"
    )
    # The planted defect is a security issue with file=app.py. At least one
    # finding must anchor there and reference the SQL/concat concern.
    hits = [
        f for f in report.findings
        if f.file == "app.py" and f.line >= 1
    ]
    assert hits, f"no finding anchored on app.py; got {report.findings!r}"

    blob = " ".join((f.title + " " + f.detail).lower() for f in hits)
    assert any(
        kw in blob for kw in ("sql", "injection", "concat", "interpolat", "user input", "untrusted")
    ), f"planted SQLi not reflected in findings: {blob!r}"

    # (3) The advisory exit reflects the flagged severity (CRITICAL/WARNING flag).
    if any(f.severity in (Severity.CRITICAL, Severity.WARNING) for f in hits):
        assert report.exit_code == 1
