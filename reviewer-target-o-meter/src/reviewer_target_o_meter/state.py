"""Typed graph state passed edge-to-edge (the deterministic typed spine).

Recall the load-bearing gotcha (research.md:114-118): LangGraph validates a
Pydantic state only on graph *input* — node outputs come back as plain dicts.
So ``findings`` is re-validated at the ``report`` node, not per-edge. The
``findings`` list uses the LangGraph ``add`` reducer so the agentic node's
output accumulates cleanly.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

from langchain.agents.middleware import AgentState

from .findings import Finding, FindingsReport


class ReviewState(TypedDict, total=False):
    """The reviewer graph state.

    F-01 *accepts* ``diff``/``context``/``plan`` as inputs — it does not compute
    them (real diff/context loading is F-02). ``findings`` accumulates via the
    ``add`` reducer (the agentic node appends); ``messages`` feeds the agentic
    loop. ``report`` holds the validated ``FindingsReport`` the ``report`` node
    stamps — last-wins (no reducer), so it replaces rather than accumulates.
    """

    repo_path: str
    diff: str  # accepted input — NOT computed here (F-02)
    context: str | None
    context_present: bool
    plan: str | None  # None-tolerant: plan-dependent checks are skipped when absent
    findings: Annotated[list[Finding], add]  # accumulates across nodes
    messages: Annotated[list, add]
    report: FindingsReport  # last-wins — the report node's validated output


__all__ = ["AgentState", "ReviewState"]
