"""Subprocess-backed search @tools (ripgrep + ast-grep-with-degrade).

Both tools NEVER raise: a missing binary or a timeout returns an error string, so
the agent loop never crashes out of a tool call. Output is capped for the context
budget. Reserved param names ``config``/``runtime`` are deliberately avoided.
"""

from .structural_search import structural_search
from .text_search import text_search

__all__ = ["structural_search", "text_search"]
