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


def test_report_caps_per_dimension() -> None:
    """Per-dimension cap: each dimension is capped independently at
    ``MAX_FINDINGS_PER_DIMENSION`` (5), severity sort is preserved within each
    dimension, and the total CAN exceed the old flat 10 when spread across
    dimensions.
    """
    from reviewer_target_o_meter.agent.nodes import MAX_FINDINGS_PER_DIMENSION

    # 7 security (over the cap) + 3 correctness (under the cap); all critical so
    # severity ordering within a dimension is determined by file/line tiebreak.
    def _dim_finding(dim: str, line: int) -> dict[str, Any]:
        return {
            "file": f"src/{dim}.py", "line": line, "severity": "critical",
            "impact": "high", "dimension": dim,
            "title": f"{dim} issue {line}", "detail": "d",
        }

    findings = [_dim_finding("security", i) for i in range(1, 8)]      # 7 → capped to 5
    findings += [_dim_finding("correctness", i) for i in range(1, 4)]  # 3 → unchanged

    out = report({"findings": findings}, None)
    result = out["findings"]

    dims = [f["dimension"] for f in result]
    assert dims.count("security") == MAX_FINDINGS_PER_DIMENSION  # 7 capped to 5
    assert dims.count("correctness") == 3                         # under cap, unchanged

    # Total exceeds the old flat 10: 5 + 3 = 8 across two dimensions. (With
    # more dimensions it can grow further; here two suffice to prove the flat
    # cap is gone for the spread case.)
    assert len(result) == MAX_FINDINGS_PER_DIMENSION + 3

    # Severity sort is preserved within each dimension (all critical here → the
    # line tiebreak must be ascending within the dimension's kept slice).
    sec_lines = [f["line"] for f in result if f["dimension"] == "security"]
    assert sec_lines == sorted(sec_lines)
    # The cap keeps the FIRST 5 by severity order (lines 1..5); 6,7 are dropped.
    assert sec_lines == [1, 2, 3, 4, 5]


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


# --- checks-node error boundary (H-A): any model-call failure degrades ---


class _RaisingAgent:
    """Offline stand-in whose ``ainvoke`` raises — mirrors the live crash.

    The real stacktrace is a ``TypeError: 'NoneType' object is not iterable`` from
    the OpenAI SDK parser when the model returns ``choices: None`` (see plan.md).
    ``langchain_openai._agenerate`` attaches the raw HTTP response to the exception
    as ``.response`` before re-raising, so we model that too: the response-shape
    probe in the ``checks`` boundary must read ``getattr(exc, "response", ...)``.
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.invoked_with: list = []

    async def ainvoke(self, messages_input, *_a, **_kw) -> dict[str, Any]:
        self.invoked_with.append(messages_input)
        raise self._exc


def test_checks_node_degrades_on_model_typeerror() -> None:
    """The load-bearing crash repro: a ``TypeError`` out of ``agent.ainvoke`` must
    degrade ``checks`` to ``{"findings": []}`` — not escape the node.

    This is the real-faithful test the ``_BoomGraph`` outer-boundary fake left open:
    it drives the REAL ``checks`` node (not a stub graph) through the DI seam with a
    fake agent that raises the exact exception from the live stacktrace. Removing
    the try/except makes this test red.
    """
    import asyncio

    from reviewer_target_o_meter.agent.nodes import build_checks_node

    exc = TypeError("'NoneType' object is not iterable")
    # Model the langchain_openai behavior: raw HTTP response attached to the exc.
    exc.response = {"choices": None, "usage": None}  # type: ignore[attr-defined]
    checks = build_checks_node(_cfg(), agent=_RaisingAgent(exc))

    state = {"diff": "diff", "plan": None, "context": None, "findings": []}
    out = asyncio.run(checks(state, None))
    assert out == {"findings": []}


def test_checks_node_degrades_on_generic_exception() -> None:
    """The boundary is broad: any ``Exception`` degrades, not just ``TypeError``.

    OQ#1: "any model-call failure degrades" (AGENTS.md §d). A non-TypeError
    exception (e.g. an ``APIError``) must also yield empty findings.
    """
    import asyncio

    from reviewer_target_o_meter.agent.nodes import build_checks_node

    checks = build_checks_node(_cfg(), agent=_RaisingAgent(RuntimeError("upstream 5xx")))
    state = {"diff": "diff", "plan": None, "context": None, "findings": []}
    out = asyncio.run(checks(state, None))
    assert out == {"findings": []}


def test_full_graph_degrades_to_empty_report_on_model_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: a raising agent must yield an empty ``FindingsReport`` with
    ``exit_code == 0`` — never a pipeline crash.

    Mirrors ``test_end_to_end_mocked_llm_emits_report``'s monkeypatch of
    ``build_graph``, but the agent raises instead of returning a payload. Proves the
    failure mode that crashed the pipeline now degrades through to the advisory
    empty report.
    """
    import asyncio

    import reviewer_target_o_meter.graph as graph_mod

    fake_agent = _RaisingAgent(TypeError("'NoneType' object is not iterable"))
    real_build_graph = graph_mod.build_graph
    monkeypatch.setattr(
        graph_mod, "build_graph", lambda cfg: real_build_graph(cfg, agent=fake_agent)
    )

    inputs = {"repo_path": "/repo", "diff": "diff", "context": None, "plan": None, "findings": []}
    report_obj = asyncio.run(graph_mod.arun_review(_cfg(), inputs))
    assert isinstance(report_obj, FindingsReport)
    assert report_obj.findings == []
    assert report_obj.exit_code == 0


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
