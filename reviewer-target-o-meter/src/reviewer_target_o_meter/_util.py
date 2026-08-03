"""Shared internal helpers.

Currently holds the single ``_warn`` used by every module that follows the
degrade-to-stderr convention (AGENTS.md §b): recoverable failures write a
one-line ``WARNING: ...`` to stderr and return a safe fallback, rather than
raising out of the pipeline. Centralizing it keeps the convention wording
fixed in one place instead of drifting across four copies.
"""

from __future__ import annotations

import sys


def warn(message: str) -> None:
    """Write a one-line ``WARNING: ...`` to stderr (degrade convention)."""
    print(f"WARNING: {message}", file=sys.stderr)


__all__ = ["warn"]
