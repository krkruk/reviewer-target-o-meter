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

from reviewer_target_o_meter.agent.nodes import MAX_FINDINGS_PER_DIMENSION
from reviewer_target_o_meter.config import Config
from reviewer_target_o_meter.context_loader import load_context
from reviewer_target_o_meter.diff import compute_diff
from reviewer_target_o_meter.findings import FindingsReport, Severity
from reviewer_target_o_meter.github import render_comment
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


def _build_repo_with_context(tmp_path: Path) -> Path:
    """Build a repo whose AGENTS.md + foundation docs are loadable as context.

    The diff plants the same SQLi as ``_build_buggy_repo``; the context tree
    (AGENTS.md + foundation) is what Phase 2's loader is expected to surface.
    """
    repo = git.Repo.init(tmp_path)
    repo.git.symbolic_ref("HEAD", "refs/heads/master")
    _configure_identity(repo)

    (tmp_path / "AGENTS.md").write_text(
        "# Sample consumer project\n\nAll SQL must be parameterized.\n"
    )
    foundation = tmp_path / "context" / "foundation"
    foundation.mkdir(parents=True)
    (foundation / "prd.md").write_text("# PRD\nA sample PRD for the consumer.\n")

    (tmp_path / "app.py").write_text(
        "def query(user_id: int) -> str:\n"
        "    return run(\"SELECT * FROM users WHERE id = %s\", (int(user_id),))\n"
    )
    repo.index.add(["AGENTS.md", "context/foundation/prd.md", "app.py"])
    base = repo.index.commit("base")

    repo.git.checkout(base.hexsha)
    (tmp_path / "app.py").write_text(
        "def query(user_id) -> str:\n"
        '    sql = "SELECT * FROM users WHERE id = " + user_id\n'
        "    return run(sql)\n"
    )
    repo.index.add(["app.py"])
    repo.index.commit("feature: inline SQL concat")
    return tmp_path


def test_load_context_feeds_real_context_to_live_reviewer(tmp_path: Path) -> None:
    """Phase 2 manual check, automated: ``load_context`` produces the consumer's
    AGENTS.md + foundation docs, and that real context drives a live review that
    still surfaces the planted defect.

    Proves the context pipeline end-to-end: the loader reads real files from the
    checkout (not a hardcoded None), the loaded context is non-empty and carries
    the AGENTS.md signal, and the live agent runs to a valid FindingsReport over
    the combined diff + context inputs.
    """
    repo_path = _build_repo_with_context(tmp_path)

    # (1) load_context returns real content from the checkout.
    ctx = load_context(repo_path)
    assert ctx is not None, "load_context returned None for a repo with context docs"
    assert "Sample consumer project" in ctx
    assert "parameterized" in ctx
    assert "A sample PRD" in ctx

    # (2) compute_diff + load_context together drive a live review.
    diff = compute_diff(repo_path, base_ref="master")
    assert diff and "SELECT * FROM users" in diff

    config = Config.from_env()
    inputs = {
        "repo_path": str(repo_path),
        "diff": diff,
        "context": ctx,
        "plan": None,
        "findings": [],
    }
    report = asyncio.run(arun_review(config, inputs))

    assert isinstance(report, FindingsReport)
    assert report.findings, (
        f"live reviewer returned no findings with diff+context; summary={report.summary!r}"
    )
    hits = [f for f in report.findings if f.file == "app.py"]
    assert hits, f"no finding anchored on app.py; got {report.findings!r}"
    blob = " ".join((f.title + " " + f.detail).lower() for f in hits)
    assert any(
        kw in blob for kw in ("sql", "injection", "concat", "interpolat", "user input", "untrusted")
    ), f"planted SQLi not reflected in findings: {blob!r}"


def _build_multidefect_repo(tmp_path: Path) -> Path:
    """A repo whose feature diff plants several distinct defects so the live
    reviewer has material to flag across more than one dimension.

    Defects: SQL injection (security), a bare ``except:`` that swallows errors
    (correctness/maintainability), and a mutable default argument (correctness).
    None require >5 findings in one dimension from a small diff — the cap is
    exercised host-side regardless of how many the model emits.
    """
    repo = git.Repo.init(tmp_path)
    repo.git.symbolic_ref("HEAD", "refs/heads/master")
    _configure_identity(repo)

    clean = (
        "def query(user_id: int) -> str:\n"
        "    return run(\"SELECT * FROM users WHERE id = %s\", (int(user_id),))\n"
        "\n"
        "def handle(req) -> int:\n"
        "    return int(req.get('n', 0))\n"
        "\n"
        "def add_item(item, dest=None):\n"
        "    if dest is None:\n"
        "        dest = []\n"
        "    dest.append(item)\n"
        "    return dest\n"
    )
    (tmp_path / "app.py").write_text(clean)
    repo.index.add(["app.py"])
    base = repo.index.commit("base: clean module")

    repo.git.checkout(base.hexsha)
    buggy = (
        "def query(user_id) -> str:\n"
        '    sql = "SELECT * FROM users WHERE id = " + user_id\n'
        "    return run(sql)\n"
        "\n"
        "def handle(req) -> int:\n"
        "    try:\n"
        "        return int(req.get('n', 0))\n"
        "    except:\n"
        "        pass\n"
        "\n"
        "def add_item(item, dest=[]):\n"
        "    dest.append(item)\n"
        "    return dest\n"
    )
    (tmp_path / "app.py").write_text(buggy)
    repo.index.add(["app.py"])
    repo.index.commit("feature: multi-defect change")
    return tmp_path


def test_live_review_respects_per_dimension_cap(tmp_path: Path) -> None:
    """Phase 3 manual check, automated: a live review of a multi-defect diff
    never emits more than ``MAX_FINDINGS_PER_DIMENSION`` findings in any single
    dimension, and the host-side cap holds on whatever the real model returned.

    This is the system-level proof of the per-dimension cap: the free model's
    output flows through ``report()``'s host-side enforcement, so even if the
    model over-emits in one dimension (it generally won't on a small diff), the
    invariant is guaranteed. We assert it on real model output, not just the
    synthetic input covered by the unit test.
    """
    repo_path = _build_multidefect_repo(tmp_path)
    diff = compute_diff(repo_path, base_ref="master")
    assert diff and "SELECT * FROM users" in diff

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
    # If the model emitted nothing, the cap is vacuously satisfied but we have
    # no system-level signal — require at least one finding on the planted diff.
    assert report.findings, (
        f"live reviewer returned no findings for a multi-defect diff; "
        f"summary={report.summary!r}"
    )

    # The host-side cap invariant: no dimension exceeds MAX_FINDINGS_PER_DIMENSION.
    per_dim: dict[str, int] = {}
    for f in report.findings:
        per_dim[f.dimension.value] = per_dim.get(f.dimension.value, 0) + 1
    over = {d: n for d, n in per_dim.items() if n > MAX_FINDINGS_PER_DIMENSION}
    assert not over, (
        f"per-dimension cap violated on live output: {over} "
        f"(cap={MAX_FINDINGS_PER_DIMENSION}); findings={report.findings!r}"
    )


def test_render_comment_renders_live_findings_as_valid_markdown(tmp_path: Path) -> None:
    """Phase 4 manual check, automated: ``render_comment`` produces well-formed
    Markdown (header + table + details + disclaimer) over the LIVE reviewer's
    findings, and the rendered rows actually reflect what the model found.

    This validates the renderer against real model output rather than the
    synthetic FindingsReport used by the unit tests: the planted SQLi must
    appear in the table, the F{n} ids must be sequential, and the disclaimer
    must carry the advisory exit code the live run computed.
    """
    repo_path = _build_buggy_repo(tmp_path)
    diff = compute_diff(repo_path, base_ref="master")

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
    assert report.findings, f"live reviewer returned no findings; summary={report.summary!r}"

    md = render_comment(report, repo="owner/sample")

    # Structural shape.
    assert md.lstrip().startswith("# ")
    assert "reviewer-target-o-meter" in md.lower()
    assert "<details>" in md and "</details>" in md
    assert "Advisory exit code" in md and str(report.exit_code) in md

    # The live findings are reflected: each finding's title + anchor is in the
    # rendered table, with sequential F{n} ids.
    for i, f in enumerate(report.findings, start=1):
        assert f"F{i}" in md
        assert f"{f.file}:{f.line}" in md
        assert f.title in md

    # The planted SQLi concern is reflected somewhere in the rendered body.
    blob = md.lower()
    assert any(
        kw in blob for kw in ("sql", "injection", "concat", "interpolat", "user input", "untrusted")
    ), f"planted SQLi not reflected in rendered comment: {blob!r}"
