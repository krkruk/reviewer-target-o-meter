"""The four graph nodes: a deterministic spine + one agentic ``checks`` leaf.

- ``context_load`` / ``plan_discovery`` — deterministic; accept inputs without
  computing them (real diff/context/plan discovery is F-02).
- ``checks`` — the single agentic node: a ``create_agent`` sub-graph bound to the
  structured LLM + the two search tools. F-01 gives it a MINIMAL analysis prompt;
  the full impl-review methodology is S-01.
- ``report`` — deterministic; re-validates the agent payload (the load-bearing
  host-side check), injects ``F{n}`` ids, sorts by severity, caps at 10, computes
  the advisory exit code, and emits remaining budget.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, Runtime
from langchain.agents.structured_output import ProviderStrategy
from langchain.messages import HumanMessage
from pydantic import ValidationError

from ..config import Config
from ..findings import FindingsReport, Severity
from ..provider import build_llm
from ..state import ReviewState
from .tools import structural_search, text_search

# Minimal system prompt — sufficient only to exercise F-01's smoke. The full
# impl-review methodology (3 dimensions, grading, finding grammar) lands in S-01.
_SYSTEM_PROMPT = """\
You are a non-interactive code reviewer embedded in an automated pipeline.

Your job: read the provided diff (plus any context and plan) and emit a
FindingsReport. For each problem: set severity (critical/warning/observation),
impact (low/medium/high), one of the seven impl-review dimensions (correctness,
security, maintainability, testability, performance, design, documentation), a
repo-relative file path and 1-based line anchor, a <=120-char title, a rationale
in `detail`, and up to 2 FixOptions (a one-sentence fix DIRECTION, never an
applied patch; mark exactly one `recommended` if there are two).

Rules:
- Read and flag only. NEVER execute the reviewed project's test/lint/build commands.
- NEVER edit files, post comments, or ask questions.
- Use the search tools only to confirm a concern; do not explore aimlessly.
- If `plan` is provided, prefer plan-relevant checks; if absent, skip plan-dependent checks.
"""

_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.WARNING: 1,
    Severity.OBSERVATION: 2,
}
_MAX_REPORTED = 10


def context_load(state: ReviewState, runtime: Runtime) -> dict[str, Any]:
    """Deterministic: accept repo_path/context from input, set context_present.

    Does NOT walk the checkout to load AGENTS.md/skills/source (that is F-02).
    """
    return {"context_present": state.get("context") is not None}


def plan_discovery(state: ReviewState, runtime: Runtime) -> dict[str, Any]:
    """Deterministic: accept `plan` from input; tolerate its absence (prd.md:60).

    No diff-relative discovery (that is F-02).
    """
    return {"plan": state.get("plan")}  # may be None — agent skips plan-dependent checks


def build_checks_node(config: Config, agent: Any = None):
    """Construct the agentic ``checks`` node bound to the base model + tools.

    Uses ``create_agent`` with ``response_format=ProviderStrategy(FindingsReport,
    strict=True)`` — the json_schema+strict structured-output contract — applied by
    the agent on top of the base chat model (which must keep ``bind_tools``).
    ModelCallLimitMiddleware caps iterations (max_iterations). The node is built
    per-invoke so it carries the user's Config.

    ``agent`` is an optional injection (DI): when provided, skips ``create_agent``
    construction entirely — used by tests to run the node offline against a fake.
    """
    if agent is None:
        model = build_llm(config)
        agent = create_agent(
            model=model,
            tools=[text_search, structural_search],
            system_prompt=_SYSTEM_PROMPT,
            response_format=ProviderStrategy(FindingsReport, strict=True),
            middleware=[ModelCallLimitMiddleware(run_limit=config.max_iterations, exit_behavior="end")],
        )

    async def checks(state: ReviewState, runtime: Runtime) -> dict[str, Any]:
        diff = state.get("diff", "")
        plan = state.get("plan")
        context = state.get("context")
        parts = [f"Diff:\n{diff}"]
        if context:
            parts.append(f"Context:\n{context}")
        if plan:
            parts.append(f"Plan:\n{plan}")
        else:
            parts.append("Plan: (none provided — skip plan-dependent checks)")
        messages = [
            HumanMessage(content="\n\n".join(parts)),
        ]
        # ainvoke (async) so the node's TimeoutPolicy(run_timeout) can be enforced —
        # sync Python execution cannot be safely cancelled in-process.
        result = await agent.ainvoke({"messages": messages})
        return _extract_findings(result)

    return checks


def _extract_findings(result: Any) -> dict[str, Any]:
    """Pull the FindingsReport payload out of the agent result.

    ``create_agent(..., response_format=ProviderStrategy(...))`` surfaces the parsed
    object at the top-level ``structured_response`` key. We accept that, a bare
    FindingsReport/dict, or a messages payload, and defer strict validation to
    ``report`` (the load-bearing host-side re-check).
    """
    parsed: Any = result
    if isinstance(result, dict):
        if "structured_response" in result and result["structured_response"] is not None:
            parsed = result["structured_response"]
        elif "parsed" in result:  # include_raw wrapper
            parsed = result["parsed"]
        elif "messages" in result:
            msgs = result["messages"]
            last = msgs[-1] if msgs else None
            parsed = getattr(last, "parsed", None) or getattr(last, "content", None)
    return {"findings": _coerce_finding_list(parsed)}


def _coerce_finding_list(parsed: Any) -> list[dict[str, Any]]:
    """Return the list of finding dicts from a parsed payload, or []."""
    if parsed is None:
        return []
    if isinstance(parsed, FindingsReport):
        return [f.model_dump() for f in parsed.findings]
    if isinstance(parsed, dict) and isinstance(parsed.get("findings"), list):
        return list(parsed["findings"])
    return []


def report(state: ReviewState, runtime: Runtime) -> dict[str, Any]:
    """Deterministic: re-validate, inject F{n} ids, sort, cap, compute exit code.

    This is the load-bearing host-side re-check: node outputs come back as plain
    dicts (research.md:114-118), so we MUST model_validate here before emit.
    """
    raw_findings = state.get("findings", [])
    try:
        report_obj = FindingsReport.model_validate({"findings": raw_findings})
    except ValidationError:
        report_obj = FindingsReport(findings=[], summary="WARNING: report re-validation failed.")

    ordered = sorted(report_obj.findings, key=lambda f: (_SEVERITY_ORDER[f.severity], f.file, f.line))
    findings_out = [f.model_dump() for f in ordered[:_MAX_REPORTED]]

    return {
        "findings": findings_out,
        "summary": report_obj.summary,
        "overall_verdict": report_obj.overall_verdict,
        "exit_code": report_obj.exit_code,
        "report": report_obj.model_copy(update={"findings": ordered[:_MAX_REPORTED]}),
    }


__all__ = ["build_checks_node", "context_load", "plan_discovery", "report"]
