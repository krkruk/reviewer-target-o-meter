"""The four graph nodes: a deterministic spine + one agentic ``checks`` leaf.

- ``context_load`` / ``plan_discovery`` — deterministic; accept inputs without
  computing them (real diff/context/plan discovery is F-02).
- ``checks`` — the single agentic node: a ``create_agent`` sub-graph bound to the
  structured LLM + the two search tools, driven by the full impl-review
  methodology system prompt (``_SYSTEM_PROMPT``, S-01).
- ``report`` — deterministic; re-validates the agent payload (the load-bearing
  host-side check), injects ``F{n}`` ids, sorts by severity, caps at
  ``MAX_FINDINGS_PER_DIMENSION`` per dimension, computes the advisory exit code,
  and emits remaining budget.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, Runtime
from langchain.agents.structured_output import ProviderStrategy
from langchain.messages import HumanMessage
from pydantic import ValidationError

from .._util import get_logger
from ..config import Config
from ..findings import Finding, FindingsReport, Severity
from ..provider import build_llm
from ..state import ReviewState
from .tools import structural_search, text_search

_log = get_logger(__name__)

# Per-dimension findings cap (F-02). Defined ABOVE _SYSTEM_PROMPT because 3.2
# splices it into the prompt string (evaluated at import time). Enforced BOTH
# in the prompt (so the model prioritizes within each dimension) AND host-side
# in report() (the load-bearing backstop — prompts are unreliable).
MAX_FINDINGS_PER_DIMENSION: int = 5

# Full impl-review methodology system prompt (S-01). Section order is load-
# bearing: role → hard rules → lenses → emit mapping → severity/impact/verdict →
# grammar + caps. Source: /10x-impl-review-ci methodology (see AGENTS.md §h) with
# three product-specific adaptations: plan-tolerance (skip plan-dependent checks
# when no plan; FR-006), no-command-execution (MISSING-TEST / UNCOVERED-BEHAVIOR
# from static evidence; PRD Non-Goal), and diff-scoping (anchor on changed files
# only; tools deepen context on changed files, never discover issues in untouched
# files). This is the single source of truth for the prompt text.
_SYSTEM_PROMPT = f"""\
## Role

You are a non-interactive critical-point reviewer embedded in an automated
pipeline. Given the diff (plus any loaded context and an optional plan), emit a
FindingsReport. You READ AND FLAG ONLY — you never execute the reviewed
project's commands, never edit files, never post comments, never ask questions.

## Hard rules

### (a) Diff-scoping as an ACTIVE investigation, not a passive filter

This is the core differentiator. The product fails two ways: (1) you become a
repo-wide linter emitting generic noise on untouched files, or (2) you stay
shallow — findings that name the diff surface but miss the real risk because you
never traced the flow. Drive BOTH halves:

1. **Read the changed files first.** Before any tool call, read each diff hunk
   and form the change's core flow (what's wired to what, what's new, what
   shifted). Every finding anchors on a file/line the diff touches.

2. **Then deepen with tools — actively, on the changed files' context.** The
   search tools exist to make findings SPECIFIC and CORRECT, not merely to
   confirm a hunch: use `structural_search` (ast-grep) to trace a changed
   symbol's definition and call sites within the changed files and to map the
   real control/data flow around a risky site; use `text_search` (ripgrep) to
   read a sibling file for a pattern comparison or to confirm a symbol's usage.
   Scale effort to risk: a touched auth/SQL/migration boundary warrants full
   flow-mapping; a touched docstring does not. A finding with no tool-backed
   context on a non-trivial change is a shallowness smell.

3. **Never flag a file the PR did not change.** Tools deepen context on changed
   files (and, for a pattern comparison, their immediate siblings) — they never
   discover issues in untouched files. The sole exception: a plan-drift MISSING
   finding anchors on a *planned* file the change should have touched but didn't.

### (b) Read-and-flag only

NEVER execute the reviewed project's test/lint/build/any-shell commands (PRD
Non-Goal). MISSING-TEST and UNCOVERED-BEHAVIOR come from static/presence evidence
(diff + plan), never execution.

### (c) Non-interactive

Never edit files, post comments, or ask questions. Emit the FindingsReport and stop.

## Three review lenses (the method)

Think in three lenses, then map each finding to the 7-dimension enum at emit.

- **Plan drift** (only if a plan is provided; else skip): for each planned change,
  judge MATCH / DRIFT / MISSING / EXTRA against the diff. Flag DRIFT (semantic
  mismatch), MISSING (planned but absent), and EXTRA not on the plan's exclusions
  list. If no plan is provided, this lens is skipped entirely.

- **Safety, quality & pattern compliance**: over the changed source files, look
  for security (injection, hardcoded secrets, missing authn/authz at boundaries),
  performance (N+1, unbounded iteration, missing pagination), reliability
  (missing error handling at external boundaries, races, leaks), data-safety
  (destructive ops without rollback, migrations without a path), and substantive
  pattern mismatches vs 1-2 sibling files (use a tool to read a sibling). Scale
  pattern depth to change size (≤3 files → minimal pattern effort). Report only
  substantive issues.

- **Test coverage**: the plan declares what "tested" means. Match each
  test-related Automated Verification commitment to a test file in the diff;
  flag MISSING TEST (severity CRITICAL). Scan changed source for new exported
  functions / new branches / new endpoints and flag UNCOVERED BEHAVIOR (WARNING)
  when no test in the diff covers them. Respect explicit opt-outs in the plan's
  exclusions. If no plan is provided, do only the diff-evident coverage check
  (a new public function with no test file touched → UNCOVERED BEHAVIOR).

## Emit mapping (lenses → the 7-dimension enum)

Pick the single best-fitting `dimension` per finding:
- drift → correctness / maintainability / design
- safety → security / performance / maintainability
- coverage → testability
- documentation findings when a plan/doc commitment is missed.
A finding may legitimately fit two dimensions — pick the best fit.

## Severity, impact, verdict

- severity (critical/warning/observation) says how bad if ignored.
- impact (low/medium/high) says how hard to decide. They are orthogonal.
- If you emit `overall_verdict`, make it 1-2 sentences naming the change's
  biggest risk (narrative, not a grade grid).

## Finding grammar + caps

Each finding: a repo-relative `file`, a 1-based `line`, a `<=120`-char `title`,
a rationale in `detail`, and up to 2 `FixOption`s (a one-sentence fix DIRECTION,
never an applied patch; if there are two, mark exactly one `recommended`).
Emit at most {MAX_FINDINGS_PER_DIMENSION} findings per dimension; prioritize the
highest-severity, highest-impact concern within each dimension before lower ones.
"""

_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.WARNING: 1,
    Severity.OBSERVATION: 2,
}


def context_load(state: ReviewState, runtime: Runtime) -> dict[str, Any]:
    """Deterministic: accept repo_path/context from input, set context_present.

    Does NOT walk the checkout to load AGENTS.md/skills/source (that is F-02).
    """
    _log.info("node context_load — context_present=%s", state.get("context") is not None)
    return {"context_present": state.get("context") is not None}


def plan_discovery(state: ReviewState, runtime: Runtime) -> dict[str, Any]:
    """Deterministic: accept `plan` from input; tolerate its absence (prd.md:60).

    No diff-relative discovery (that is F-02).
    """
    _log.info("node plan_discovery — plan_present=%s", state.get("plan") is not None)
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
        _log.info(
            "node checks — agent invoke start (diff_chars=%d plan_present=%s context_present=%s)",
            len(diff or ""), plan is not None, context is not None,
        )
        try:
            result = await agent.ainvoke({"messages": messages})
        except Exception as exc:  # noqa: BLE001 — OQ#1: ANY model-call failure degrades (AGENTS.md §d).
            # The live crash was an uncaught TypeError from the OpenAI SDK parser
            # (choices=None) escaping here and crashing the pipeline — bypassing
            # every downstream fail-safe. Broad on purpose: only BaseException
            # (KeyboardInterrupt/CancelledError) keeps propagating.
            shape = _extract_response_shape(exc)
            _log.warning(
                "node checks — agent invoke failed: %s: %s | response_shape=%s — "
                "degraded to empty report; if this repeats, switch to a more potent "
                "model with a larger token budget",
                type(exc).__name__, exc, shape,
            )
            return {"findings": []}
        _log.info("node checks — agent invoke end")
        return _extract_findings(result)

    return checks


def _extract_response_shape(exc: BaseException) -> str:
    """Best-effort probe of the raw response attached to a model-call exception.

    ``langchain_openai._agenerate`` attaches the raw HTTP response (``.response``)
    to the exception before re-raising. The live crash (a ``TypeError`` from the
    SDK parser when ``choices`` is ``None``) carries the response shape here — so
    we surface it in the degrade WARNING for free, without a live re-run.

    Never raises: the probe itself is wrapped so a malformed ``.response`` never
    re-throws out of the except block. Reads only structural keys
    (``choices``/``finish_reason``/``usage``); headers / bodies are NOT touched, so
    no API key or absolute host path can leak into the log.
    """
    raw = getattr(exc, "response", None)
    if raw is None:
        return "n/a"
    try:
        # ``raw`` may be an httpx Response (call ``.json()``) or an already-parsed
        # dict (the test fixture path). Accept both; tolerate anything else.
        body = raw.json() if hasattr(raw, "json") and callable(raw.json) else raw
        if isinstance(body, dict):
            choices = body.get("choices")
            finish_reason = None
            if isinstance(choices, list) and choices:
                first = choices[0]
                finish_reason = first.get("finish_reason") if isinstance(first, dict) else None
            usage = body.get("usage")
            n_choices = len(choices) if isinstance(choices, list) else None
            return (
                f"choices={'None' if choices is None else n_choices} "
                f"finish_reason={finish_reason!r} usage={usage!r}"
            )
        return f"{type(raw).__name__}"
    except Exception:  # noqa: BLE001 — probe must never re-raise out of the except block
        return f"{type(raw).__name__}(unreadable)"


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
    _log.info("node report — raw_findings=%d", len(raw_findings))
    try:
        report_obj = FindingsReport.model_validate({"findings": raw_findings})
    except ValidationError:
        report_obj = FindingsReport(findings=[], summary="WARNING: report re-validation failed.")

    ordered = sorted(report_obj.findings, key=lambda f: (_SEVERITY_ORDER[f.severity], f.file, f.line))
    capped = _cap_per_dimension(ordered)
    findings_out = [f.model_dump() for f in capped]

    return {
        "findings": findings_out,
        "summary": report_obj.summary,
        "overall_verdict": report_obj.overall_verdict,
        "exit_code": report_obj.exit_code,
        "report": report_obj.model_copy(update={"findings": capped}),
    }


def _cap_per_dimension(ordered: list[Finding]) -> list[Finding]:
    """Keep the first ``MAX_FINDINGS_PER_DIMENSION`` per dimension, preserving
    the input (severity-first) order across the flattened result.

    ``ordered`` is already sorted by severity (then file/line); we walk it once
    and count per dimension, dropping anything past the cap. This keeps the
    severity ordering intact within AND across dimensions while enforcing the
    per-dimension bound (trust-but-verify for the prompt instruction).
    """
    kept: list[Finding] = []
    seen_per_dim: dict[str, int] = {}
    for finding in ordered:
        dim = finding.dimension.value
        if seen_per_dim.get(dim, 0) >= MAX_FINDINGS_PER_DIMENSION:
            continue
        seen_per_dim[dim] = seen_per_dim.get(dim, 0) + 1
        kept.append(finding)
    return kept


__all__ = ["build_checks_node", "context_load", "plan_discovery", "report"]
