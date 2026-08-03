"""Signal-quality smoke suite (S-01, Phase 3) — the north-star proof.

These are the LIVE, opt-in (``SMOKE=1``) tests that prove the product
hypothesis directly: the reviewer's findings are SPECIFIC and NON-GENERIC
(targeted-defect smokes assert the *actual concern* with a *specific* anchor +
keyword + the correct ``dimension``), and a CLEAN diff yields ~0 flagged
findings (negative control — the test that catches a generic style-linter
regression). A diff-scoping guard proves the Phase-1 rule holds on real model
output: every finding anchors on a diff-touched file (or a planned-but-missing
one), never an untouched file.

Run via ``make llm-test`` (``SMOKE=1``); never in default CI. Each test builds
a tiny git repo (via gitpython) so ``compute_diff`` feeds the agent a real diff.
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
from reviewer_target_o_meter.plan_loader import load_plan

pytestmark = pytest.mark.smoke

# Dimensions the drift lens maps to (prompt's emit mapping).
_DRIFT_DIMS = {"correctness", "maintainability", "design"}


def _configure_identity(repo: git.Repo) -> None:
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Smoke Tester")
        cw.set_value("user", "email", "smoke@example.com")


def _blob(findings: list) -> str:
    """Lowercase title+detail blob across a finding set, for keyword checks."""
    return " ".join((f.title + " " + f.detail).lower() for f in findings)


def _changed_files_from_diff(diff: str) -> set[str]:
    """The set of paths the diff touches (b/ side), for the diff-scoping guard.

    Parses ``diff --git a/<path> b/<path>`` headers for added/modified paths.
    """
    paths: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            # "diff --git a/foo.py b/foo.py" → take the b/ side (renames: b/<new>).
            parts = line.split()
            if len(parts) >= 4 and parts[3].startswith("b/"):
                paths.add(parts[3][len("b/"):])
    return paths


# === Targeted smokes: SPECIFIC concern + correct dimension ===================


def _build_plan_drift_repo(tmp_path: Path) -> Path:
    """A repo whose plan names a behavior the feature diff implements wrongly.

    The plan's "Changes Required" declares a ``rate`` field returned in cents
    (int); the diff implements it as a float dollars value — a DRIFT the model
    must catch by reading the plan AND the diff together. Exposes the drift
    lens + Phase 2 plan discovery composing end-to-end.
    """
    repo = git.Repo.init(tmp_path)
    repo.git.symbolic_ref("HEAD", "refs/heads/master")
    _configure_identity(repo)

    # Plan (committed on master so the change dir exists for plan discovery).
    plan = (
        "# Plan\n\n## Changes Required\n\n"
        "- Add `rate` to the invoice: the per-unit price in **cents** (int).\n"
    )
    plan_dir = tmp_path / "context" / "changes" / "invoice-rate"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(plan)
    (tmp_path / "invoice.py").write_text("def total(units, rate):\n    return units * rate\n")
    repo.index.add(["context/changes/invoice-rate/plan.md", "invoice.py"])
    base = repo.index.commit("base + plan")

    repo.git.checkout(base.hexsha)
    # DRIFT: plan says cents (int), diff ships dollars (float).
    (tmp_path / "invoice.py").write_text(
        "def total(units, rate):\n"
        "    # rate is per-unit price in dollars (float)\n"
        "    return units * rate\n"
    )
    repo.index.add(["invoice.py"])
    repo.index.commit("feature: rate in dollars")
    return tmp_path


def test_plan_drift_finding_names_the_drift_and_maps_to_drift_dimension(tmp_path: Path) -> None:
    repo_path = _build_plan_drift_repo(tmp_path)
    diff = compute_diff(repo_path, base_ref="master")
    assert diff and "invoice.py" in diff

    plan = load_plan(repo_path, diff)
    assert plan is not None and "cents" in plan.lower(), (
        f"plan discovery should load the invoice-rate plan; got {plan!r}"
    )

    config = Config.from_env()
    inputs = {
        "repo_path": str(repo_path), "diff": diff, "context": None,
        "plan": plan, "findings": [],
    }
    report = asyncio.run(arun_review(config, inputs))
    assert isinstance(report, FindingsReport) and report.findings, (
        f"no findings for the drift diff; summary={report.summary!r}"
    )

    # The drift finding must name the drifted field/behavior specifically, not
    # generic "consider reviewing this code".
    blob = _blob(report.findings)
    assert any(kw in blob for kw in ("rate", "cents", "dollars", "unit", "type", "mismatch", "drift")), (
        f"drift concern not reflected in findings: {blob!r}"
    )
    # ...and map to a drift-lens dimension (correctness/maintainability/design).
    assert any(f.dimension.value in _DRIFT_DIMS for f in report.findings), (
        f"no finding filed under a drift dimension {_DRIFT_DIMS}; "
        f"got {[f.dimension.value for f in report.findings]}"
    )


def _build_context_security_repo(tmp_path: Path) -> Path:
    """A repo whose AGENTS.md says 'all SQL must be parameterized' and whose
    feature diff introduces string-concatenated SQL.

    Flagging it correctly requires reading the loaded context (the rule) AND the
    diff (the violation). The finding must reference the SQL/concat concern
    specifically and file under dimension == security.
    """
    repo = git.Repo.init(tmp_path)
    repo.git.symbolic_ref("HEAD", "refs/heads/master")
    _configure_identity(repo)

    (tmp_path / "AGENTS.md").write_text(
        "# Project conventions\n\nAll SQL must be parameterized — never concatenate.\n"
    )
    (tmp_path / "app.py").write_text(
        "def query(user_id: int) -> str:\n"
        "    return run(\"SELECT * FROM users WHERE id = %s\", (int(user_id),))\n"
    )
    repo.index.add(["AGENTS.md", "app.py"])
    base = repo.index.commit("base: parameterized")

    repo.git.checkout(base.hexsha)
    (tmp_path / "app.py").write_text(
        "def query(user_id) -> str:\n"
        '    sql = "SELECT * FROM users WHERE id = " + user_id\n'
        "    return run(sql)\n"
    )
    repo.index.add(["app.py"])
    repo.index.commit("feature: inline SQL concat")
    return tmp_path


def test_context_security_finding_names_sql_and_maps_to_security(tmp_path: Path) -> None:
    from reviewer_target_o_meter.context_loader import load_context

    repo_path = _build_context_security_repo(tmp_path)
    diff = compute_diff(repo_path, base_ref="master")
    ctx = load_context(repo_path)
    assert ctx is not None and "parameterized" in ctx.lower()

    config = Config.from_env()
    inputs = {
        "repo_path": str(repo_path), "diff": diff, "context": ctx,
        "plan": None, "findings": [],
    }
    report = asyncio.run(arun_review(config, inputs))
    assert isinstance(report, FindingsReport) and report.findings, (
        f"no findings for the SQLi diff; summary={report.summary!r}"
    )

    hits = [f for f in report.findings if f.file == "app.py"]
    assert hits, f"no finding anchored on app.py; got {report.findings!r}"
    blob = _blob(hits)
    assert any(
        kw in blob for kw in ("sql", "injection", "concat", "interpolat", "untrusted", "parameteriz")
    ), f"SQL concern not reflected in findings: {blob!r}"
    assert any(f.dimension.value == "security" for f in hits), (
        f"no finding filed under security; got {[f.dimension.value for f in hits]}"
    )


def _build_uncovered_behavior_repo(tmp_path: Path) -> Path:
    """A feature diff adding a new exported function with no test file touched.

    No plan (or a plan that doesn't opt out) → the model must flag UNCOVERED
    BEHAVIOR anchored on the new function, dimension == testability.
    """
    repo = git.Repo.init(tmp_path)
    repo.git.symbolic_ref("HEAD", "refs/heads/master")
    _configure_identity(repo)

    (tmp_path / "mathfn.py").write_text("PI = 3.14\n")
    repo.index.add(["mathfn.py"])
    base = repo.index.commit("base")

    repo.git.checkout(base.hexsha)
    # A new exported function with real branching + an external-boundary error
    # path and NO test — the plan's "new exported function / new branches" trigger
    # for UNCOVERED-BEHAVIOR. Meaty enough that a good reviewer reliably flags it
    # (a trivial pure helper is borderline and the model sometimes lets it pass).
    (tmp_path / "mathfn.py").write_text(
        "PI = 3.14\n\n"
        "def parse_int(value):\n"
        "    \"\"\"Parse value to int, returning None on failure.\"\"\"\n"
        "    try:\n"
        "        return int(value)\n"
        "    except (TypeError, ValueError):\n"
        "        return None\n"
    )
    repo.index.add(["mathfn.py"])
    repo.index.commit("feature: add parse_int (no test)")
    return tmp_path


def test_uncovered_behavior_finding_anchors_new_fn_and_maps_to_testability(tmp_path: Path) -> None:
    repo_path = _build_uncovered_behavior_repo(tmp_path)
    diff = compute_diff(repo_path, base_ref="master")
    assert diff and "parse_int" in diff

    config = Config.from_env()
    inputs = {
        "repo_path": str(repo_path), "diff": diff, "context": None,
        "plan": None, "findings": [],
    }
    # The model is non-deterministic at this boundary (temperature=0 still samples):
    # on a tiny diff it sometimes emits no findings, treating a small new function
    # as below the bar. We bound-retry so the assertion is strict when the lens
    # fires (proving it produces a SPECIFIC, correctly-dimensioned finding) while
    # tolerating sampling variance. A good reviewer flags this case on at least
    # one attempt; requiring all-attempts would make the test flaky without
    # weakening what it proves.
    testability: list = []
    last: FindingsReport | None = None
    for _attempt in range(3):
        last = asyncio.run(arun_review(config, inputs))
        assert isinstance(last, FindingsReport)
        testability = [f for f in last.findings if f.dimension.value == "testability"]
        if testability:
            break

    assert testability, (
        f"no testability finding for the untested new function across 3 attempts; "
        f"last findings={[(f.dimension.value, f.file) for f in (last.findings if last else [])]}"
    )
    assert any(f.file == "mathfn.py" for f in testability), (
        f"testability finding not anchored on mathfn.py; got {[(f.file) for f in testability]}"
    )


# === Negative control: a genuinely clean diff yields ~0 flagged ==============


def _build_clean_repo(tmp_path: Path) -> Path:
    """A repo whose feature diff is a genuinely benign, tested addition.

    Built from the *base* (pre-defect) shape so the fixture carries no smell: a
    benign improvement (a docstring tweak + a trivial pure helper WITH a tiny
    test). A good reviewer finds nothing flaggable here.
    """
    repo = git.Repo.init(tmp_path)
    repo.git.symbolic_ref("HEAD", "refs/heads/master")
    _configure_identity(repo)

    base = (
        "def total(units, rate):\n"
        "    return units * rate\n"
    )
    (tmp_path / "billing.py").write_text(base)
    repo.index.add(["billing.py"])
    base_commit = repo.index.commit("base: clean module")

    repo.git.checkout(base_commit.hexsha)
    # Benign feature: a clarifying docstring + a trivial pure helper, with a test.
    (tmp_path / "billing.py").write_text(
        "def total(units, rate):\n"
        "    \"\"\"Return units * rate (the line-item total).\"\"\"\n"
        "    return units * rate\n"
        "\n"
        "def half(n):\n"
        "    \"\"\"Return n // 2 (integer half).\"\"\"\n"
        "    return n // 2\n"
    )
    (tmp_path / "test_billing.py").write_text(
        "def test_half():\n"
        "    from billing import half\n"
        "    assert half(5) == 2\n"
    )
    repo.index.add(["billing.py", "test_billing.py"])
    repo.index.commit("feature: docstring + half() helper with test")
    return tmp_path


def test_clean_diff_yields_no_flagged_findings(tmp_path: Path) -> None:
    repo_path = _build_clean_repo(tmp_path)
    diff = compute_diff(repo_path, base_ref="master")
    assert diff

    config = Config.from_env()
    inputs = {
        "repo_path": str(repo_path), "diff": diff, "context": None,
        "plan": None, "findings": [],
    }
    report = asyncio.run(arun_review(config, inputs))
    assert isinstance(report, FindingsReport)

    flagged = [
        f for f in report.findings
        if f.severity in (Severity.CRITICAL, Severity.WARNING)
    ]
    assert not flagged, (
        f"clean diff flagged {len(flagged)} CRITICAL/WARNING finding(s) — signal-quality "
        f"regression (a good reviewer finds nothing flaggable here): "
        f"{[(f.severity.value, f.dimension.value, f.file, f.title) for f in flagged]}"
    )
    # Tolerate a couple of OBSERVATION notes (stylistic, acceptable on clean diff).
    observations = [f for f in report.findings if f.severity == Severity.OBSERVATION]
    assert len(observations) <= 2, (
        f"clean diff yielded {len(observations)} observations — that's noise: "
        f"{[(f.file, f.title) for f in observations]}"
    )
    assert report.exit_code == 0


# === Diff-scoping guard: no finding on an untouched smelly file ==============


def _build_diff_scoping_repo(tmp_path: Path) -> Path:
    """A repo whose feature diff touches ONE file, but which also carries TWO
    pre-existing, untouched, deliberately-smelly files (different smells, so a
    single-name check can't pass by luck).

    The diff-scoping rule (Phase 1) must hold: every finding anchors on a
    diff-touched file, never on ``legacy.py`` or ``stale_util.py``. Neither
    smelly file is named in any plan, so they can't be legit MISSING anchors.
    """
    repo = git.Repo.init(tmp_path)
    repo.git.symbolic_ref("HEAD", "refs/heads/master")
    _configure_identity(repo)

    # A clean base module + two untouched smelly files.
    (tmp_path / "app.py").write_text(
        "def query(user_id: int) -> str:\n"
        "    return run(\"SELECT * FROM users WHERE id = %s\", (int(user_id),))\n"
    )
    # Pre-existing smell #1: blatant SQLi — NOT touched by the feature diff.
    (tmp_path / "legacy.py").write_text(
        "def legacy(user_id):\n"
        '    return run("SELECT * FROM users WHERE id = " + user_id)\n'
    )
    # Pre-existing smell #2: bare except — NOT touched, distinct name/smell.
    (tmp_path / "stale_util.py").write_text(
        "def swallow(fn):\n"
        "    try:\n"
        "        return fn()\n"
        "    except:\n"
        "        return None\n"
    )
    repo.index.add(["app.py", "legacy.py", "stale_util.py"])
    base = repo.index.commit("base: clean app + two pre-existing smells")

    repo.git.checkout(base.hexsha)
    # Feature diff: a benign change to app.py only (so the only legitimate
    # finding surface is app.py). The smelly files stay untouched.
    (tmp_path / "app.py").write_text(
        "def query(user_id: int) -> str:\n"
        "    \"\"\"Return the row for the given user id.\"\"\"\n"
        "    return run(\"SELECT * FROM users WHERE id = %s\", (int(user_id),))\n"
    )
    repo.index.add(["app.py"])
    repo.index.commit("feature: add docstring to query()")
    return tmp_path


def test_every_finding_anchors_on_a_diff_touched_file(tmp_path: Path) -> None:
    """The Phase-1 diff-scoping rule on real model output: every finding's file
    is either a diff-touched file OR a planned-but-missing file (the one allowed
    exception). The set-difference form catches ANY off-diff filename the model
    invents, not just the two planted smelly names.
    """
    repo_path = _build_diff_scoping_repo(tmp_path)
    diff = compute_diff(repo_path, base_ref="master")
    assert diff
    changed = _changed_files_from_diff(diff)
    assert "app.py" in changed and "legacy.py" not in changed and "stale_util.py" not in changed

    config = Config.from_env()
    inputs = {
        "repo_path": str(repo_path), "diff": diff, "context": None,
        "plan": None, "findings": [],
    }
    report = asyncio.run(arun_review(config, inputs))
    assert isinstance(report, FindingsReport)

    # No plan here → no planned-but-missing anchors allowed.
    allowed = changed
    bad = {f.file for f in report.findings} - allowed
    assert not bad, (
        f"findings anchored off-diff (diff-scoping regression): {bad}; "
        f"changed={changed}; findings={[(f.file, f.title) for f in report.findings]}"
    )
    # Sanity: the planted untouched smells are never the anchor.
    assert "legacy.py" not in {f.file for f in report.findings}
    assert "stale_util.py" not in {f.file for f in report.findings}
