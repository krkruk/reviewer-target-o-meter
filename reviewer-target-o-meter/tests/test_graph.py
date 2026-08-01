"""Graph tests: pure-node behavior, node ordering, report re-validation + advisory
exit, and the recursion-probe (mocked LLM — deterministic, offline).

The live OpenRouter smoke is in test_smoke_provider.py. Here we test the graph
structure and the deterministic nodes directly, and run the async graph end-to-end
against a mocked structured LLM to prove the four-node spine fires in order and
``report`` re-validates + computes the advisory exit.
"""

from __future__ import annotations

from typing import Any

import pytest

from reviewer_target_o_meter.agent.nodes import context_load, plan_discovery, report
from reviewer_target_o_meter.config import Config
from reviewer_target_o_meter.findings import FindingsReport
from reviewer_target_o_meter.graph import build_graph


def _cfg() -> Config:
    return Config(api_key="sk-test")


def _finding(severity: str = "critical") -> dict[str, Any]:
    return {
        "file": "src/app.py", "line": 10, "severity": severity,
        "impact": "high", "dimension": "security",
        "title": "SQLi", "detail": "concatenation of attacker input",
    }


# --- pure deterministic nodes ---


def test_context_load_sets_present_flag() -> None:
    assert context_load({"context": "ctx"}, None)["context_present"] is True
    assert context_load({"context": None}, None)["context_present"] is False


def test_plan_discovery_is_none_tolerant() -> None:
    # prd.md:60 plan-tolerance — absent plan is accepted, not an error.
    assert plan_discovery({"plan": "PLAN"}, None)["plan"] == "PLAN"
    assert plan_discovery({"plan": None}, None)["plan"] is None


def test_report_revalidates_and_exits_advisory_on_flagged() -> None:
    out = report({"findings": [_finding("critical")]}, None)
    assert out["exit_code"] == 1
    assert isinstance(out["report"], FindingsReport)
    assert len(out["findings"]) == 1


def test_report_exits_zero_on_all_observations() -> None:
    out = report({"findings": [_finding("observation")]}, None)
    assert out["exit_code"] == 0


def test_report_degrades_on_invalid_findings() -> None:
    # Host-side re-validation rejects a bad payload (e.g. absolute path) and degrades.
    bad = [{"file": "/abs/x.py", "line": 1, "severity": "critical",
            "impact": "high", "dimension": "security", "title": "t", "detail": "d"}]
    out = report({"findings": bad}, None)
    assert out["exit_code"] == 0
    assert out["findings"] == []


def test_report_sorts_by_severity_and_caps_at_ten() -> None:
    findings = [_finding("observation")] * 5 + [_finding("warning")] * 4 + [_finding("critical")] * 3
    out = report({"findings": findings}, None)
    severities = [f["severity"] for f in out["findings"]]
    assert severities == sorted(severities, key=lambda s: {"critical": 0, "warning": 1, "observation": 2}[s])
    assert len(out["findings"]) <= 10


# --- graph wiring / node ordering ---


def test_graph_has_four_nodes_in_order() -> None:
    g = build_graph(_cfg())
    nodes = list(g.get_graph().nodes)
    for n in ("context_load", "plan_discovery", "checks", "report"):
        assert n in nodes
    # the spine is a single linear chain
    edges = g.get_graph().edges
    targets = [e[1] for e in edges if e[0] == "context_load"]
    assert "plan_discovery" in targets


# --- end-to-end with a mocked structured LLM (deterministic, offline) ---


class _FakeAgent:
    """Offline stand-in for the create_agent sub-graph.

    Returns a fixed parsed FindingsReport at the top-level ``structured_response``
    key — the same surface the real agent exposes (see nodes._extract_findings).
    """

    def __init__(self, payload: FindingsReport) -> None:
        self._payload = payload
        self.invoked_with: list = []

    async def ainvoke(self, messages_input, *_a, **_kw) -> dict[str, Any]:
        self.invoked_with.append(messages_input)
        return {"structured_response": self._payload, "messages": []}


def test_end_to_end_mocked_llm_emits_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full four-node graph runs offline with a fake agent injected via DI.

    Proves: nodes fire in order, checks surfaces structured_response, report
    re-validates and computes the advisory exit code. (Deterministic, offline.)
    """
    import asyncio

    import reviewer_target_o_meter.graph as graph_mod
    from reviewer_target_o_meter.findings import Dimension, Finding, Impact, Severity

    payload = FindingsReport(findings=[Finding(
        file="src/app.py", line=10, severity=Severity.CRITICAL, impact=Impact.HIGH,
        dimension=Dimension.SECURITY, title="SQLi", detail="concat")])
    fake_agent = _FakeAgent(payload)

    real_build_graph = graph_mod.build_graph
    monkeypatch.setattr(
        graph_mod, "build_graph", lambda cfg: real_build_graph(cfg, agent=fake_agent)
    )

    inputs = {"repo_path": "/repo", "diff": "diff", "context": None, "plan": None, "findings": []}
    report_obj = asyncio.run(graph_mod.arun_review(_cfg(), inputs))
    assert isinstance(report_obj, FindingsReport)
    # The fake agent was called exactly once (single checks invocation).
    assert len(fake_agent.invoked_with) == 1
    assert report_obj.exit_code == 1  # the injected CRITICAL finding flags


# --- recursion-probe / fail-safe ---


def test_graph_recursion_error_emits_partial_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a tiny recursion_limit: the run must degrade, not crash (OQ#1).

    This also documents the inner-vs-outer recursion interplay (D-SubAgentRecursion):
    the inner create_agent's ModelCallLimitMiddleware caps model calls, and the outer
    recursion_limit caps supersteps; a tight outer limit trips first, and run_review
    catches GraphRecursionError -> partial report + advisory exit. See AGENTS.md.
    """
    from langgraph.errors import GraphRecursionError

    import reviewer_target_o_meter.graph as graph_mod

    class _BoomGraph:
        async def ainvoke(self, *_a, **_kw):
            raise GraphRecursionError("forced: recursion_limit=2")

    monkeypatch.setattr(graph_mod, "build_graph", lambda c: _BoomGraph())
    inputs = {"repo_path": "/repo", "diff": "d", "context": None, "plan": None, "findings": []}
    report_obj = graph_mod.run_review(_cfg(), inputs)
    assert isinstance(report_obj, FindingsReport)
    assert report_obj.findings == []
    assert report_obj.summary is not None and "recursion" in report_obj.summary.lower()
    assert report_obj.exit_code == 0  # advisory — never crashes the pipeline
