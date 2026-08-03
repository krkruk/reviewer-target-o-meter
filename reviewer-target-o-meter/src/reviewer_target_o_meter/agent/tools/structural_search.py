"""``structural_search`` — ast-grep-backed structural (AST) code search.

Wraps the ``ast-grep`` binary. Degrades to an error string when ast-grep is
missing or times out — never raises (FR-010 degrade philosophy), and explicitly
points the model at ``text_search`` as the fallback. Output is capped at
``_MAX_OUTPUT`` chars for the context budget.
"""

from __future__ import annotations

import shutil
import subprocess

from langchain.tools import tool

_MAX_OUTPUT = 20000
_TRUNCATED = "\n...[truncated]"


@tool
def structural_search(pattern: str, repo_path: str, lang: str | None = None) -> str:
    """Search the repository structurally using ast-grep.

    Use this for AST-aware pattern matching (e.g. ``$X + $Y`` for all binary
    additions), which is more precise than text search for code constructs.
    Returns matching locations, capped for the context budget. If ast-grep is
    unavailable, fall back to ``text_search`` instead.

    Args:
        pattern: An ast-grep pattern (e.g. ``$X + $Y``, ``console.log($$$ARGS)``).
        repo_path: Absolute or repo-relative path to search within.
        lang: Optional language hint (e.g. ``python``, ``javascript``) to scope parsing.
    """
    if shutil.which("ast-grep") is None:
        return "ast-grep unavailable on PATH; use text_search instead."

    cmd = ["ast-grep", "run", "--json=compact", "-p", pattern]
    if lang:
        cmd += ["-l", lang]
    cmd.append(repo_path)

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=False, timeout=30, check=False
        )
        out = proc.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return f"structural_search timed out after 30s (pattern={pattern!r})."
    except (FileNotFoundError, OSError):
        return "ast-grep unavailable on PATH; use text_search instead."

    if len(out) > _MAX_OUTPUT:
        out = out[: _MAX_OUTPUT - len(_TRUNCATED)] + _TRUNCATED
    return out
