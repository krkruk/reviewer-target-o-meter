"""Search @tool tests — mocked subprocess, missing-binary degrade, output capping.

These pin the FR-010 degrade philosophy: a tool must NEVER raise. If its binary is
missing it returns an error string; timeouts/missing-binary are caught. Output is
capped for the context budget. Reserved param names (`config`/`runtime`) are avoided.
"""

from __future__ import annotations

import shutil
import subprocess
from collections import deque

import pytest

from reviewer_target_o_meter.agent.tools.structural_search import structural_search
from reviewer_target_o_meter.agent.tools.text_search import text_search


def _patch_subprocess(monkeypatch: pytest.MonkeyPatch, stdout: bytes = b"", binaries_present: bool = True):
    """Patch the stdlib subprocess.run + shutil.which the tools call into.

    Returns a list recording each (cmd, kwargs) subprocess.run was called with.
    Patching the shared stdlib modules is correct here because the tools call
    ``subprocess.run`` / ``shutil.which`` on those module objects directly.
    """
    calls: list[tuple] = []

    class FakeProc:
        def __init__(self, out: bytes) -> None:
            self.stdout = out
            self.returncode = 0

    queue: deque[bytes] = deque([stdout])

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return FakeProc(queue.popleft() if queue else b"")

    def fake_which(binary: str) -> str | None:
        return f"/usr/bin/{binary}" if binaries_present else None

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", fake_which)
    return calls


# --- text_search ---


def test_text_search_returns_matched_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_subprocess(monkeypatch, stdout=b"src/app.py:10:x = 1\nsrc/app.py:20:y = 2\n")
    out = text_search.invoke({"query": "x", "repo_path": "/repo"})
    assert "src/app.py:10" in out
    assert len(calls) == 1


def test_text_search_caps_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, stdout=b"x" * 30000)
    out = text_search.invoke({"query": "q", "repo_path": "/repo"})
    assert len(out) <= 20000


def test_text_search_degrades_when_rg_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, binaries_present=False)
    out = text_search.invoke({"query": "q", "repo_path": "/repo"})
    assert "ripgrep" in out.lower() and "unavailable" in out.lower()


def test_text_search_catches_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd="rg", timeout=30)
    monkeypatch.setattr(subprocess, "run", boom)
    out = text_search.invoke({"query": "q", "repo_path": "/repo"})
    assert "timeout" in out.lower() or "timed out" in out.lower()


def test_text_search_max_count_flows_into_rg(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_subprocess(monkeypatch, stdout=b"hit\n")
    text_search.invoke({"query": "x", "repo_path": "/repo", "max_count": 7})
    cmd = calls[0][0]
    assert "--max-count" in cmd and "7" in cmd


# --- structural_search (ast-grep) ---


def test_structural_search_returns_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_subprocess(monkeypatch, stdout=b"src/app.py:10:match\n")
    out = structural_search.invoke({"pattern": "$X + $Y", "repo_path": "/repo"})
    assert "src/app.py:10" in out
    # Pin the binary name: the cmd list must invoke ast-grep, not its deprecated alias.
    assert calls[0][0][0] == "ast-grep"


def test_structural_search_degrades_when_ast_grep_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, binaries_present=False)
    out = structural_search.invoke({"pattern": "$X", "repo_path": "/repo"})
    assert "ast-grep" in out.lower() and "text_search" in out.lower()


def test_structural_search_catches_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd="ast-grep", timeout=30)
    monkeypatch.setattr(subprocess, "run", boom)
    out = structural_search.invoke({"pattern": "$X", "repo_path": "/repo"})
    assert "timeout" in out.lower() or "timed out" in out.lower()


def test_structural_search_caps_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, stdout=b"x" * 30000)
    out = structural_search.invoke({"pattern": "$X", "repo_path": "/repo"})
    assert len(out) <= 20000
