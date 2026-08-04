"""Compute a capped diff from local git history against a discovered base ref.

A plain function library (not a ``@tool``, not a graph node) called by the CLI.
Follows the existing degrade convention: on any git failure, write a one-line
``WARNING: ...`` to stderr and return an empty string — a diff-based review can
still run on context alone (FR-010 graceful-degradation spirit).

The diff cap (~20k chars) matches the tool-output cap in ``AGENTS.md`` §b; it
bounds the ``checks`` node's prompt size. Truncation is always at a clean
``\\ndiff --git`` boundary with a visible marker, so the model is never silently
fed a truncation.
"""

from __future__ import annotations

import os
from pathlib import Path

from git import Repo
from git.exc import (
    GitCommandError,
    GitError,
    InvalidGitRepositoryError,
    NoSuchPathError,
)
from gitdb.exc import BadName, BadObject

from ._util import get_logger
from ._util import warn as _warn

_log = get_logger(__name__)

# Module constant (NOT env-driven in v1). Matches the tool-output cap in AGENTS.md §b.
MAX_DIFF_CHARS = 20_000

# Heuristic base candidates tried in order when no override/CI var is set.
_BASE_CANDIDATES = ("origin/main", "main", "origin/master", "master")

_TRUNCATION_MARKER = "\n\n… [diff truncated: {remaining} more chars]\n"


def compute_diff(repo_path: str | Path, base_ref: str | None = None) -> str:
    """Return the capped diff text of ``HEAD`` against a discovered base ref.

    Base-ref discovery (the ordering is load-bearing — override wins, the CI
    var is next, heuristics last) lives in :func:`_resolve_base`. On any git
    failure (non-git dir, missing base, broken repo), writes a ``WARNING:`` to
    stderr and returns ``""`` — never raises.
    """
    try:
        repo = Repo(str(repo_path), search_parent_directories=False)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        _warn(f"diff skipped — not a git repo ({exc})")
        return ""

    base = _resolve_base(repo, base_ref)
    if base is None:
        _warn("diff skipped — no base ref resolved (set BASE_REF / GITHUB_BASE_REF)")
        return ""

    try:
        raw = repo.git.diff(base, "HEAD", "--patch", "--no-color")
    except (GitCommandError, BadName, BadObject) as exc:
        _warn(f"diff skipped — git diff failed ({exc})")
        return ""

    capped = _cap(raw)
    _log.info(
        "diff computed — base=%s raw_chars=%d capped_chars=%d truncated=%s",
        base, len(raw), len(capped), len(raw) != len(capped),
    )
    return capped


def _resolve_base(repo: Repo, override: str | None) -> str | None:
    """Resolve the base ref: override → ``GITHUB_BASE_REF`` → heuristic.

    Returns ``None`` if nothing resolves (the caller degrades). The ordering is
    load-bearing: an explicit override always wins; the CI var (set on GHA
    ``pull_request`` events) wins over heuristics when it resolves; the heuristic
    chain walks the conventional default-branch names.

    The CI var is VERIFIED before use: ``GITHUB_BASE_REF`` is a branch NAME
    (e.g. ``master``), but ``actions/checkout`` leaves HEAD detached with only
    ``origin/<base>`` present, so the bare name often doesn't resolve locally.
    Returning it verbatim makes ``git diff <base> HEAD`` fail (exit 128); when it
    doesn't resolve we fall through to the heuristic, which finds ``origin/<base>``.
    The override is returned as-is when set (an explicit user choice is not
    silently overridden; git diff's own try/except degrades if it fails).
    """
    if override:  # 1. explicit arg / BASE_REF env (passed in by the CLI)
        return override
    ci_base = os.environ.get("GITHUB_BASE_REF")  # 2. GHA pull_request events
    if ci_base:
        # The bare name may not resolve locally (GHA detached checkout), but the
        # remote-tracking ref origin/<base> usually does. Try both before falling
        # through to the heuristic.
        for cand in (ci_base, f"origin/{ci_base}"):
            if _resolves(repo, cand):
                return cand
    for cand in _BASE_CANDIDATES:  # 3. heuristic
        if _resolves(repo, cand):
            return cand
    return None  # caller degrades


def _resolves(repo: Repo, ref: str) -> bool:
    """True if ``ref`` resolves to a commit in ``repo`` (degrades on bad names)."""
    try:
        repo.commit(ref)
    except (BadName, BadObject, GitError, ValueError):
        return False
    return True


def _cap(raw: str) -> str:
    """Truncate ``raw`` to ``MAX_DIFF_CHARS`` at the next ``diff --git`` boundary."""
    if len(raw) <= MAX_DIFF_CHARS:
        return raw
    # Cut at the next file boundary AFTER the budget so we never split a hunk.
    boundary = raw.find("\ndiff --git", MAX_DIFF_CHARS)
    cut = boundary if boundary != -1 else MAX_DIFF_CHARS
    remaining = len(raw) - cut
    return raw[:cut] + _TRUNCATION_MARKER.format(remaining=remaining)


__all__ = ["MAX_DIFF_CHARS", "compute_diff"]
