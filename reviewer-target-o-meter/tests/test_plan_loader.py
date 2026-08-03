"""Unit tests for the plan-loader module (Phase 2, S-01).

Builds a tmp 10x-shaped tree per test to pin: the discovery chain (diff-driven
→ single-active → None), the cap, archive exclusion, the unreadable-file
degrade, and the no-plan.md-dir → None shape (the real consumer shape as of
2026-08-03). Mirrors the test_context_loader.py fixture approach.

Offline (no network, no LLM).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from reviewer_target_o_meter.plan_loader import (
    MAX_PLAN_CHARS,
    load_plan,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _diff(change_id: str) -> str:
    """A diff touching exactly one change dir's plan.md (diff-driven case)."""
    return (
        f"diff --git a/context/changes/{change_id}/plan.md b/context/changes/{change_id}/plan.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/context/changes/{change_id}/plan.md\n"
        "@@ -0,0 +1 @@\n"
        "+plan body\n"
    )


# --- (a) diff-driven: one change touched → that plan --------------------------


def test_diff_touched_single_change_returns_its_plan(tmp_path: Path) -> None:
    _write(tmp_path / "context/changes/feature-x/plan.md", "# Plan X\nbody X\n")

    plan = load_plan(tmp_path, _diff("feature-x"))

    assert plan is not None
    assert "# Plan X" in plan
    assert "body X" in plan


# --- (b) diff touches two change dirs → None (ambiguous) ---------------------


def test_diff_touched_two_changes_is_ambiguous_returns_none(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "context/changes/feature-x/plan.md", "X\n")
    _write(tmp_path / "context/changes/feature-y/plan.md", "Y\n")

    diff = (
        "diff --git a/context/changes/feature-x/plan.md b/context/changes/feature-x/plan.md\n"
        "+++ b/context/changes/feature-x/plan.md\n"
        "+x\n"
        "diff --git a/context/changes/feature-y/plan.md b/context/changes/feature-y/plan.md\n"
        "+++ b/context/changes/feature-y/plan.md\n"
        "+y\n"
    )
    plan = load_plan(tmp_path, diff)

    assert plan is None  # ambiguous diff → no plan (plan-tolerance)
    # No raise; the run stays silent here (ambiguous is a normal "no plan").


# --- (c) diff touches nothing under context/changes/ but one active change ----


def test_no_diff_change_but_single_active_change_returns_that_plan(tmp_path: Path) -> None:
    _write(tmp_path / "context/changes/feature-x/plan.md", "ACTIVE PLAN\n")
    # A diff that touches only source, nothing under context/changes/.
    diff = (
        "diff --git a/src/app.py b/src/app.py\n"
        "+++ b/src/app.py\n"
        "+pass\n"
    )

    plan = load_plan(tmp_path, diff)

    assert plan is not None
    assert "ACTIVE PLAN" in plan


# --- (d) zero or two active change dirs + no diff-touched change → None -------


def test_zero_active_changes_and_no_diff_change_returns_none(tmp_path: Path) -> None:
    _write(tmp_path / "src/app.py", "pass\n")
    diff = "diff --git a/src/app.py b/src/app.py\n+++ b/src/app.py\n+pass\n"

    assert load_plan(tmp_path, diff) is None


def test_two_active_changes_and_no_diff_change_returns_none(tmp_path: Path) -> None:
    _write(tmp_path / "context/changes/feature-x/plan.md", "X\n")
    _write(tmp_path / "context/changes/feature-y/plan.md", "Y\n")
    diff = "diff --git a/src/app.py b/src/app.py\n+++ b/src/app.py\n+pass\n"

    assert load_plan(tmp_path, diff) is None  # single-active can't disambiguate


# --- (e) context/archive/<id>/plan.md is never picked ------------------------


def test_archive_only_change_is_not_picked(tmp_path: Path) -> None:
    _write(tmp_path / "context/archive/old/plan.md", "ARCHIVED\n")
    diff = "diff --git a/src/app.py b/src/app.py\n+++ b/src/app.py\n+pass\n"

    # single-active excludes archive → no active change → None.
    assert load_plan(tmp_path, diff) is None


# --- (f) over-budget plan is truncated with the marker -----------------------


def test_oversize_plan_is_truncated_with_marker(tmp_path: Path) -> None:
    big = "P" * (MAX_PLAN_CHARS + 5_000)
    _write(tmp_path / "context/changes/feature-x/plan.md", big)

    plan = load_plan(tmp_path, _diff("feature-x"))

    assert plan is not None
    assert len(plan) <= MAX_PLAN_CHARS + 200  # marker overhead only
    assert "truncated" in plan.lower()


# --- (g) missing plan.md (change dir exists, no plan file) → None + WARNING --


def test_change_dir_without_plan_md_returns_none(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    # Diff-driven change resolves to a dir that has NO plan.md.
    _write(tmp_path / "context/changes/feature-x/frame.md", "frame only\n")
    capfd.readouterr()  # clear

    plan = load_plan(tmp_path, _diff("feature-x"))

    assert plan is None
    captured = capfd.readouterr()
    assert "WARNING" in captured.err or "WARNING" in captured.out


# --- (h) single active change whose only doc is verification.md → None -------


def test_single_active_change_with_only_verification_doc_returns_none(tmp_path: Path) -> None:
    # The real consumer shape (2026-08-03): a change dir carrying only
    # verification.md, not plan.md. Must NOT be treated as a plan.
    _write(tmp_path / "context/changes/bootstrap-verification/verification.md", "v\n")
    diff = "diff --git a/src/app.py b/src/app.py\n+++ b/src/app.py\n+pass\n"

    assert load_plan(tmp_path, diff) is None


# --- extras: degrade on missing checkout; frame/research.md drive the diff ---


def test_missing_checkout_returns_none(tmp_path: Path) -> None:
    assert load_plan(tmp_path / "does-not-exist", "") is None


def test_diff_touched_change_via_frame_md_resolves(tmp_path: Path) -> None:
    # frame.md / research.md in the diff also identify the current change.
    _write(tmp_path / "context/changes/feature-x/plan.md", "THE PLAN\n")
    diff = (
        "diff --git a/context/changes/feature-x/frame.md b/context/changes/feature-x/frame.md\n"
        "+++ b/context/changes/feature-x/frame.md\n"
        "+frame\n"
    )
    plan = load_plan(tmp_path, diff)
    assert plan is not None
    assert "THE PLAN" in plan


def test_unreadable_plan_file_degrades_to_none(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    if os.geteuid() == 0:
        pytest.skip("chmod 000 does not deny root; can't exercise the degrade path")
    plan_path = tmp_path / "context/changes/feature-x/plan.md"
    _write(plan_path, "SECRET PLAN\n")
    os.chmod(plan_path, 0o200)  # write-only: owner cannot read
    os.chmod(plan_path.parent, stat.S_IRWXU)
    capfd.readouterr()

    try:
        plan = load_plan(tmp_path, _diff("feature-x"))
    finally:
        os.chmod(plan_path, stat.S_IRWXU)

    assert plan is None
    captured = capfd.readouterr()
    assert "WARNING" in captured.err or "WARNING" in captured.out


# --- (F1) non-UTF-8 and oversized plans degrade instead of crashing ----------


def test_non_utf8_plan_does_not_raise(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    # A plan.md carrying invalid UTF-8 (e.g. a binary blob, a Windows-1252 doc).
    # UnicodeDecodeError is a ValueError, NOT an OSError — a plain `except
    # OSError` would let it escape and crash the pipeline. The loader must
    # decode leniently (errors="replace") and return a plan, never raise.
    plan_path = tmp_path / "context/changes/feature-x/plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_bytes(b"# Plan\nbefore \xff\xfe bad bytes\nafter\n")
    capfd.readouterr()

    plan = load_plan(tmp_path, _diff("feature-x"))

    # Lenient decode → the plan still loads (no WARNING, no raise); the
    # replacement chars just appear where the bad bytes were.
    assert plan is not None
    assert "# Plan" in plan
    captured = capfd.readouterr()
    assert not (captured.err or captured.out)  # no WARNING — this is normal


def test_oversize_binary_plan_does_not_oom(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    # A multi-GB-shaped plan.md: well over the cap but written as bytes so we
    # don't materialize the full string in the test either. read_text() would
    # load the whole file into RAM before _cap truncated it (MemoryError is
    # NOT an OSError → would crash). The bounded read must keep peak memory
    # at O(cap) and still truncate with the visible marker.
    plan_path = tmp_path / "context/changes/feature-x/plan.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    overage = MAX_PLAN_CHARS + 50_000
    plan_path.write_bytes(b"P" * overage)
    capfd.readouterr()

    plan = load_plan(tmp_path, _diff("feature-x"))

    assert plan is not None
    assert len(plan) <= MAX_PLAN_CHARS + 200  # cap + marker overhead only
    assert "truncated" in plan.lower()
    captured = capfd.readouterr()
    assert not (captured.err or captured.out)  # truncation is silent, not a warning


# --- (F3) a crafted change-id can't traverse out of context/changes/ ---------


def test_path_traversal_change_id_is_rejected(tmp_path: Path) -> None:
    # A hostile diff names `..` as the change id (or any segment outside the 10x
    # charset). Today the regex's `[^/]` + pathlib normalization already block
    # this, but the explicit `_validate_change_id` guard must reject it too — a
    # future loosening of the capture regex must not silently open traversal.
    # Plant a real file at the traversal target so the test FAILS if the guard
    # ever lets the id through (it would read this file instead of degrading).
    _write(tmp_path / "context/plan.md", "SHOULD NOT BE READ\n")
    hostile_diff = (
        "diff --git a/context/changes/../plan.md b/context/changes/../plan.md\n"
        "+++ b/context/changes/../plan.md\n"
        "+hostile\n"
    )

    plan = load_plan(tmp_path, hostile_diff)

    assert plan is None  # rejected by the charset guard, never read the target


def test_shell_metachar_change_id_is_rejected(tmp_path: Path) -> None:
    # A change id carrying shell metacharacters (e.g. "; rm -rf") is outside
    # the 10x charset and must degrade to None before reaching a path join.
    hostile_diff = (
        "diff --git a/context/changes/feature;rm/plan.md "
        "b/context/changes/feature;rm/plan.md\n"
        "+++ b/context/changes/feature;rm/plan.md\n"
        "+hostile\n"
    )

    assert load_plan(tmp_path, hostile_diff) is None
