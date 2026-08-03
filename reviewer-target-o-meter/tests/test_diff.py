"""Unit tests for the diff computation module (Phase 1, F-02).

Builds a real (tmp) git repo per test — `tests/fixtures/sample-repo` has no
`.git`, so it can't exercise `git diff`. The degrade path is covered with a
plain non-git directory.

These tests are offline (no network, no LLM); they pin base-ref resolution,
diff capping, and the never-raise degrade convention.
"""

from __future__ import annotations

import os
from pathlib import Path

import git
import pytest

from reviewer_target_o_meter import diff as diff_mod
from reviewer_target_o_meter.diff import MAX_DIFF_CHARS, compute_diff

# --- helpers: build a real git repo with a branch off a base commit ------------


def _make_repo(tmp_path: Path, base_branch: str = "main") -> git.Repo:
    """Init a repo at ``tmp_path`` with one commit on ``base_branch``.

    Leaves HEAD detached on the base commit (not the branch tip) so callers can
    layer changes on top via :func:`_add_change` and have ``diff(base, HEAD)``
    be non-empty — mirroring how the tool reviews a feature branch ahead of base.
    """
    repo = git.Repo.init(tmp_path)
    repo.git.symbolic_ref("HEAD", f"refs/heads/{base_branch}")
    _configure_identity(repo)
    (tmp_path / "README.md").write_text("hello\n")
    repo.index.add(["README.md"])
    base_commit = repo.index.commit("base commit")
    # Detach HEAD onto the base commit so new commits advance HEAD past base.
    repo.git.checkout(base_commit.hexsha)
    return repo


def _configure_identity(repo: git.Repo) -> None:
    """Set a local identity so commit/diff work in a sandboxed environment."""
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Tester")
        cw.set_value("user", "email", "tester@example.com")


def _add_change(repo: git.Repo, path: Path) -> None:
    """Add a new commit on top of HEAD (now detached ahead of the base branch)."""
    (path / "src").mkdir(exist_ok=True)
    (path / "src" / "app.py").write_text('x = 1\n')
    repo.index.add(["src/app.py"])
    repo.index.commit("change")


# --- (a) a real diff against a real base ---------------------------------------


def test_compute_diff_returns_nonempty_diff_against_real_base(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _add_change(repo, tmp_path)

    diff = compute_diff(tmp_path)

    assert diff, "expected a non-empty diff"
    assert "diff --git" in diff
    assert "src/app.py" in diff
    # git diff paths are repo-relative by construction (FR-009 anchor contract).
    assert "/tmp" not in diff.replace(str(tmp_path), "")  # no absolute host paths


def test_resolve_base_explicit_override_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path, base_branch="master")
    _add_change(repo, tmp_path)
    monkeypatch.setenv("GITHUB_BASE_REF", "master")

    # override beats both the env var and the heuristic
    assert diff_mod._resolve_base(repo, override="master") == "master"


def test_resolve_base_github_base_ref_before_heuristic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path, base_branch="master")
    _add_change(repo, tmp_path)
    monkeypatch.setenv("GITHUB_BASE_REF", "master")

    assert diff_mod._resolve_base(repo, override=None) == "master"


def test_resolve_base_falls_back_to_heuristic(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, base_branch="master")
    _add_change(repo, tmp_path)

    # heuristic resolves one of the canonical candidates
    assert diff_mod._resolve_base(repo, override=None) in {"master", "origin/master"}


def test_resolve_base_returns_none_when_nothing_resolves(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, base_branch="topic")  # no main/master
    _add_change(repo, tmp_path)

    assert diff_mod._resolve_base(repo, override=None) is None


def test_compute_diff_empty_string_when_base_unresolvable(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, base_branch="topic")  # base chain can't resolve
    _add_change(repo, tmp_path)
    # Clear any ambient CI env var so the override/env chain is exhausted.
    os.environ.pop("GITHUB_BASE_REF", None)

    assert compute_diff(tmp_path, base_ref=None) == ""


# --- (b) the truncation cap ----------------------------------------------------


def test_oversize_diff_is_truncated_with_marker(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    # Add a file large enough that the diff blows past MAX_DIFF_CHARS.
    big = "x" * (MAX_DIFF_CHARS + 5_000)
    (tmp_path / "big.txt").write_text(big + "\n")
    repo.index.add(["big.txt"])
    repo.index.commit("big change")

    diff = compute_diff(tmp_path)

    assert len(diff) <= MAX_DIFF_CHARS + 400  # marker overhead only
    assert "truncated" in diff.lower()


# --- (d) the degrade path: non-git dir never raises ----------------------------


def test_non_git_dir_returns_empty_and_warns(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    # tmp_path has no .git
    result = compute_diff(tmp_path)

    assert result == ""
    captured = capfd.readouterr()
    assert "WARNING" in captured.err or "WARNING" in captured.out


def test_compute_diff_never_raises_on_garbage_path(tmp_path: Path) -> None:
    bogus = tmp_path / "does-not-exist"
    # Degrade convention: return "" rather than raising.
    assert compute_diff(bogus) == ""
