"""``text_search`` — ripgrep-backed literal/regex code search.

Wraps the ``rg`` binary. Degrades to an error string when ripgrep is missing or
times out — never raises (FR-010 degrade philosophy). Output is capped at
``_MAX_OUTPUT`` chars for the context budget. The docstring is the LM-visible
description; the type hints define the input JSON schema.
"""

from __future__ import annotations

import shutil
import subprocess

from langchain.tools import tool

_MAX_OUTPUT = 20000
_TRUNCATED = "\n...[truncated]"


@tool
def text_search(query: str, repo_path: str, max_count: int = 50) -> str:
    """Search the repository for a literal or regex pattern using ripgrep (rg).

    Use this to find where a symbol, string, or pattern appears in the code.
    Returns matching lines (path:line:content), capped to a bounded number of
    matches. Prefer this when structural search (ast-grep) is unavailable.

    Args:
        query: Literal substring or regular expression to search for.
        repo_path: Absolute or repo-relative path to search within.
        max_count: Maximum number of matches to return (default 50).
    """
    if shutil.which("rg") is None:
        return "ripgrep (rg) unavailable on PATH; install it or ask the caller."

    try:
        proc = subprocess.run(
            ["rg", "--no-heading", "-n", "--max-count", str(max_count), query, repo_path],
            capture_output=True,
            text=False,
            timeout=30,
            check=False,
        )
        out = proc.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return f"text_search timed out after 30s (query={query!r})."
    except FileNotFoundError:
        return "ripgrep (rg) unavailable on PATH; install it or ask the caller."

    if len(out) > _MAX_OUTPUT:
        out = out[: _MAX_OUTPUT - len(_TRUNCATED)] + _TRUNCATED
    return out
