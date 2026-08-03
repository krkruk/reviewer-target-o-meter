"""System-level smoke test for the consumer integration (Phase 6, F-02/S-02).

The bridge between the offline tests and the manual "post a real comment" step:
a live, opt-in (``SMOKE=1``) test proving the input pipeline works against a
REAL, diffable consumer checkout. It does NOT post (no token in CI); it asserts
the diff + context loaders surface real content from the consumer and the graph
runs to completion over them.

Points at ``$CONSUMER_REPO`` (default ``../target-o-meter``) — the consumer
checkout. Run via ``make llm-test`` (``SMOKE=1``); never in default CI.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from reviewer_target_o_meter.config import Config
from reviewer_target_o_meter.context_loader import load_context
from reviewer_target_o_meter.diff import compute_diff
from reviewer_target_o_meter.findings import FindingsReport
from reviewer_target_o_meter.graph import arun_review

pytestmark = pytest.mark.smoke


def _consumer_repo() -> Path:
    return Path(os.environ.get("CONSUMER_REPO", "../target-o-meter")).resolve()


def test_input_pipeline_runs_against_real_consumer_checkout() -> None:
    """Phase 6 manual check 6.3/6.4, automated: against the real consumer
    checkout, ``load_context`` surfaces the consumer's AGENTS.md + foundation
    docs, and the live graph runs to a valid FindingsReport over them.

    The diff may be empty when the consumer's HEAD equals its base (e.g. on
    master) — that's a valid state (context-only review still runs, per the
    degrade philosophy). What matters here is that the input pipeline loads the
    REAL consumer context and the graph completes, not that the diff is nonzero.
    """
    repo = _consumer_repo()
    if not repo.is_dir():
        pytest.skip(f"consumer checkout not found at {repo} (set CONSUMER_REPO)")

    # (1) load_context surfaces the consumer's real AGENTS.md + foundation docs.
    ctx = load_context(repo)
    assert ctx is not None, (
        f"load_context returned None for {repo}; expected the consumer's "
        "AGENTS.md + foundation docs"
    )
    # The consumer's AGENTS.md heading/body must be in the loaded context.
    agents_path = repo / "AGENTS.md"
    assert agents_path.is_file(), f"consumer has no AGENTS.md at {agents_path}"
    # Pull a distinctive line from the real AGENTS.md and confirm it survived.
    sample = agents_path.read_text(encoding="utf-8").splitlines()[0].strip()
    if sample:
        assert sample in ctx, (
            f"consumer AGENTS.md heading {sample!r} not in loaded context"
        )

    # (2) compute_diff runs without raising against the real checkout (may be ""
    # on master — that's fine). It must never crash the pipeline.
    diff = compute_diff(repo)
    assert isinstance(diff, str)
    # If there IS a real change vs base, the diff carries the git marker.
    if diff:
        assert "diff --git" in diff

    # (3) The live graph runs to completion over the consumer's diff + context.
    config = Config.from_env()
    inputs = {
        "repo_path": str(repo),
        "diff": diff,
        "context": ctx,
        "plan": None,
        "findings": [],
    }
    report = asyncio.run(arun_review(config, inputs))
    assert isinstance(report, FindingsReport)
    # Advisory exit is always 0 or 1; the run must not crash.
    assert report.exit_code in (0, 1)
