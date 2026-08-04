"""Unit tests for the context-loader module (Phase 2, F-02).

Builds a tmp tree per test to pin: scope priority, archive exclusion, the cap,
None-when-empty, and the unreadable-file skip (degrade convention).

Offline (no network, no LLM).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from reviewer_target_o_meter.context_loader import (
    MAX_CONTEXT_CHARS,
    load_context,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# --- (a) scope priority + concatenation ---------------------------------------


def test_loads_agents_foundation_and_change_in_priority_order(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "# Agents\nagents body\n")
    _write(tmp_path / "context/foundation/prd.md", "# PRD\nprd body\n")
    _write(tmp_path / "context/changes/c-1/plan.md", "# Plan\nplan body\n")

    ctx = load_context(tmp_path)

    assert ctx is not None
    # All three sources are present.
    assert "agents body" in ctx
    assert "prd body" in ctx
    assert "plan body" in ctx
    # AGENTS.md is highest-signal → it appears before foundation, which appears
    # before the change doc (priority order is load-bearing for the model).
    assert ctx.index("agents body") < ctx.index("prd body") < ctx.index("plan body")


def test_loads_frame_and_research_alongside_plan(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "agents\n")
    _write(tmp_path / "context/changes/c-1/plan.md", "PLAN\n")
    _write(tmp_path / "context/changes/c-1/frame.md", "FRAME\n")
    _write(tmp_path / "context/changes/c-1/research.md", "RESEARCH\n")

    ctx = load_context(tmp_path)
    assert ctx is not None
    for token in ("PLAN", "FRAME", "RESEARCH"):
        assert token in ctx


# --- (b) archive exclusion ----------------------------------------------------


def test_archive_changes_are_excluded(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "agents\n")
    _write(tmp_path / "context/changes/active/plan.md", "ACTIVE\n")
    _write(tmp_path / "context/archive/old/plan.md", "ARCHIVED\n")

    ctx = load_context(tmp_path)
    assert ctx is not None
    assert "ACTIVE" in ctx
    assert "ARCHIVED" not in ctx


# --- (c) None when empty ------------------------------------------------------


def test_returns_none_when_no_context(tmp_path: Path) -> None:
    # An empty tree — nothing to load.
    assert load_context(tmp_path) is None


def test_returns_none_when_only_unrelated_files(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "readme\n")
    _write(tmp_path / "src/app.py", "x = 1\n")
    # Neither AGENTS.md nor the context/ tree → no reviewable context.
    assert load_context(tmp_path) is None


# --- (d) the cap --------------------------------------------------------------


def test_oversize_context_is_truncated_with_marker(tmp_path: Path) -> None:
    # A single AGENTS.md large enough to exceed the cap on its own.
    big = "A" * (MAX_CONTEXT_CHARS + 5_000)
    _write(tmp_path / "AGENTS.md", big)

    ctx = load_context(tmp_path)
    assert ctx is not None
    assert len(ctx) <= MAX_CONTEXT_CHARS + 200  # marker overhead only
    assert "truncated" in ctx.lower()


# --- (e) unreadable-file skip (degrade) ---------------------------------------


def test_unreadable_file_is_skipped_not_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    if os.geteuid() == 0:
        pytest.skip("chmod 000 does not deny root; can't exercise the degrade path")
    _write(tmp_path / "AGENTS.md", "agents\n")
    secret = tmp_path / "context/foundation/secret.md"
    _write(secret, "SECRET\n")
    # Write-only (0o200): owner cannot read. Parent stays traversable.
    os.chmod(secret, 0o200)
    os.chmod(secret.parent, stat.S_IRWXU)

    try:
        with caplog.at_level("WARNING", logger="reviewer_target_o_meter"):
            # Must not raise; the unreadable file is skipped with a WARNING.
            ctx = load_context(tmp_path)
        assert ctx is not None
        assert "agents" in ctx
        assert "SECRET" not in ctx
        assert "WARNING" in caplog.text
    finally:
        # Restore so pytest can clean up.
        os.chmod(secret, stat.S_IRWXU)


def test_nonexistent_path_returns_none(tmp_path: Path) -> None:
    # Degrade convention: a missing checkout degrades to None, not a crash.
    assert load_context(tmp_path / "does-not-exist") is None
