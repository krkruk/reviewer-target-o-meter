"""Assemble the typed spine + agentic leaf into one StateGraph with bounds.

``START -> context_load -> plan_discovery -> checks -> report -> END``. Only
``checks`` is agentic (a single ``create_agent`` sub-graph). Invoke with the
cost/latency bounds from Config; catch ``GraphRecursionError`` -> partial report
+ advisory exit (OQ#1 fail-safe).
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, TimeoutPolicy
from pydantic import ValidationError

from .agent.nodes import build_checks_node, context_load, plan_discovery, report
from .config import Config
from .findings import FindingsReport
from .state import ReviewState


def build_graph(config: Config, agent: Any = None):
    """Construct the compiled four-node graph with the cost/latency bounds.

    ``agent`` (DI) is forwarded to the checks node — used by tests to run offline.
    """
    graph = StateGraph(ReviewState)
    checks = build_checks_node(config, agent=agent)

    graph.add_node("context_load", context_load)
    graph.add_node("plan_discovery", plan_discovery)
    # TimeoutPolicy(run_timeout) on the only OpenRouter-calling node; bounded retry.
    graph.add_node(
        "checks",
        checks,
        timeout=TimeoutPolicy(run_timeout=config.run_timeout),
        retry_policy=RetryPolicy(max_attempts=2),
    )
    graph.add_node("report", report)

    graph.add_edge(START, "context_load")
    graph.add_edge("context_load", "plan_discovery")
    graph.add_edge("plan_discovery", "checks")
    graph.add_edge("checks", "report")
    graph.add_edge("report", END)
    return graph.compile()


def run_review(config: Config, inputs: dict[str, Any]) -> FindingsReport:
    """Build + invoke the graph, returning the host-re-validated FindingsReport.

    Runs the async graph via asyncio. Wraps invoke: a ``GraphRecursionError``
    degrades to a partial report + advisory exit (OQ#1 fail-safe) rather than
    crashing the pipeline.
    """
    return asyncio.run(arun_review(config, inputs))


async def arun_review(config: Config, inputs: dict[str, Any]) -> FindingsReport:
    """Async entry: build + ainvoke the graph (checks node needs async for timeout)."""
    compiled = build_graph(config)
    invoke_config = {"recursion_limit": config.recursion_limit}
    try:
        result = await compiled.ainvoke(inputs, invoke_config)
    except GraphRecursionError:
        return FindingsReport(
            findings=[],
            summary="WARNING: recursion limit reached; emitted partial/empty report.",
        )

    return _report_from_result(result, inputs)


def _report_from_result(result: dict[str, Any], inputs: dict[str, Any]) -> FindingsReport:
    """Pull the validated report the ``report`` node stamped back into state."""
    stamped = result.get("report")
    if isinstance(stamped, FindingsReport):
        return stamped
    # Fall back to rebuilding from the findings list (defensive).
    try:
        return FindingsReport.model_validate({"findings": result.get("findings", [])})
    except (ValidationError, TypeError):
        return FindingsReport(findings=[], summary="WARNING: no validated report produced.")


__all__ = ["arun_review", "build_graph", "run_review"]
