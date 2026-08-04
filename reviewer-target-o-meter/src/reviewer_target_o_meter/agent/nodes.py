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

from dataclasses import dataclass
from typing import Any, cast

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    Runtime,
    ToolCallLimitMiddleware,
)
from langchain.agents.structured_output import ProviderStrategy
from langchain.messages import HumanMessage
from pydantic import ValidationError

from .._util import get_logger
from ..config import Config
from ..findings import Finding, FindingsReport, Severity
from ..provider import _MAX_TOKENS, build_llm
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

## BUDGET — the #1 rule (read first)

You have a STRICTLY BOUNDED number of model calls. **If you spend them all on
tool calls you will emit NOTHING — a total failure worse than any missed
finding.** Obey these hard limits:

1. **At most 5 tool-call turns, total.** Count them. After your 5th tool-call
   turn, you MUST stop calling tools and use your next turn to emit the
   FindingsReport, no matter how much more you could investigate. Partial
   findings from 5 turns of investigation beat zero findings from endless
   searching.
2. **Batch tool calls** — issue 2-4 independent searches in ONE turn (parallel),
   never one-per-turn.
3. **Never re-search a symbol you have already read.** Track what you've seen.
4. **Emit directly.** When you decide to emit, your next turn MUST BE the
   FindingsReport itself (the structured JSON response). Do NOT spend a turn
   narrating "I will now emit" or summarizing what you found — that wastes a
   turn you need for the actual structured response. Go straight to it.

The two most common failure modes that produce a 0-finding report are (1)
re-searching the same symbol and (2) over-investigating past turn 5. Both leave
no budget for the emit.

## Hard rules

### (a) Diff-scoping as an ACTIVE investigation, not a passive filter

This is the core differentiator. The product fails two ways: (1) you become a
repo-wide linter emitting generic noise on untouched files, or (2) you stay
shallow — findings that name the diff surface but miss the real risk because you
never traced the flow. Drive BOTH halves:

1. **Read the changed files first.** Before any tool call, read each diff hunk
   and form the change's core flow (what's wired to what, what's new, what
   shifted). Every finding anchors on a file/line the diff touches. A diff hunk
   shows only the changed lines — when a hunk MODIFIES a function, use
   `text_search` to read the WHOLE function (not just the hunk) before judging
   it: the hunk's new branch may duplicate or contradict a sequence elsewhere
   in the same function that the hunk doesn't show. Reviewing only the hunk is
   the #1 cause of missed cross-branch duplication and contradicting-comment
   defects.

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
  performance (N+1, unbounded iteration, missing pagination, unbounded state
  accumulation — a collection, especially module-level or process-global, that
  grows without bound over the process lifetime with no eviction), reliability
  (missing error handling at external boundaries, AND present-but-hostile
  handling: a bare or broad except that swallows the error and returns a
  default, hiding failures from the caller/operator; races; leaks),
  maintainability (duplicated control flow — when two or more branches in the
  SAME changed function repeat the same cleanup/degrade/exit sequence
  verbatim, that duplication will drift; flag it so it gets factored into one
  helper. To spot this you MUST read the WHOLE changed function with
  text_search, not just the diff hunk — a new branch often duplicates a
  sequence that sits elsewhere in the same function, outside the hunk), data-safety (destructive ops without rollback, migrations without a
  path), and substantive pattern mismatches vs 1-2 sibling files (use a tool to
  read a sibling). Scale pattern depth to change size (≤3 files → minimal
  pattern effort). Flag the reliability/performance/maintainability patterns
  above even when minor — emit them at OBSERVATION severity when they don't
  cause a real correctness/security defect; reserve CRITICAL/WARNING for
  genuine defects. Still suppress trivial style/formatting noise (naming,
  whitespace, import order) — this is a critical-point reviewer, not a linter.

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

## Cross-branch duplication (scan EVERY changed function for this)

A frequent, high-value maintainability defect: two or more branches in the SAME
changed function repeat the same multi-line sequence verbatim (a degrade path
like `_warn(...) + _emit_stdout(report) + sys.exit(...)`, or a cleanup/rollback
sequence, or the same validation block). Such duplication WILL drift the next
time one branch is edited. The diff you receive uses function-context, so BOTH
branches are visible even when only one was changed — actively compare the
branches of each changed function and flag any repeated multi-line sequence as
a maintainability finding (OBSERVATION unless it already caused a bug), with a
fix direction to factor the shared sequence into one helper. If you see the
same 2+ line sequence appear more than once in a changed function, that is the
signal — do not skip it.

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

## Optional style observations (optional_findings)

ALSO emit 1-3 `optional_findings` — style, readability, naming, idiom, and
consistency observations that reflect the code's quality but are NOT defects.
Be extra picky: every review should produce something meaningful here. Anchor
each on a representative changed line (same file/line grammar as a finding),
set severity to OBSERVATION, and keep the detail to one sentence. These never
block the PR (they never affect the exit code) — they are advisory style notes
for the author. Do NOT duplicate a real defect from `findings` here; if a
concern is a real defect, it belongs in `findings`, not `optional_findings`.

## Worked example (exact output shape — emit this, with your own content)

Below is the exact shape your FindingsReport MUST take. Use your own real
content from the diff; mirror this structure, these fields, these value styles.
`severity`/`impact`/`dimension` are enums — use exactly those lowercase tokens.
Anchors are repo-relative paths with 1-based lines. Fix options are one-sentence
DIRECTIONS, never applied patches; with two, mark exactly one `recommended`.

```
{{
  "findings": [
    {{
      "file": "src/bff/routers/scoring_routes.py",
      "line": 300,
      "end_line": 306,
      "severity": "observation",
      "impact": "medium",
      "dimension": "maintainability",
      "title": "Ownership resolution block repeated verbatim in all four new routes",
      "detail": "list_scores, get_score, patch_score and delete_score each repeat the identical get_user_context(...) + DoesNotExist -> 404 sequence; the next edit to one will drift the other three. Factor the shared resolution into one decorator or helper.",
      "fixes": [
        {{"approach": "Extract the user-resolution + 404 sequence into a shared decorator applied to all four routes.", "recommended": true}}
      ]
    }}
  ],
  "optional_findings": [
    {{
      "file": "src/frontend/src/components/ScoreList.tsx",
      "line": 49,
      "severity": "observation",
      "impact": "low",
      "dimension": "maintainability",
      "title": "List rows keyed by result_id only — duplicate ids could collapse rows",
      "detail": "The .map key is result_id with no fallback; if two rows share an id React would warn and mis-reconcile.",
      "fixes": []
    }}
  ],
  "summary": "2 findings (1 maintainability duplication, 1 frontend keying); no blocking defects.",
  "overall_verdict": "The biggest risk is the four duplicated ownership blocks in scoring_routes.py drifting on the next edit; centralizing them would remove the maintenance hazard."
}}
```

Note: `exit_code`, `flagged`, and finding `id` ("F1") are host-side and ABSENT
from your emit — the host injects them. Emit only `findings`, `optional_findings`,
`summary`, `overall_verdict`. An empty `findings` list is valid ONLY when the
diff genuinely has no flaggable concerns; never emit empty just because you ran
out of investigation budget — emit what you found, even if partial.
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
        # Tool-call budget (fine-tune-context): forces convergence. The model
        # never self-limits its investigation; without this cap it spends every
        # iteration on tool calls and never emits (0 findings, runs 4/7/8).
        # Over-budget tool calls return an error message and execution continues,
        # so the model converges and emits. Separate from the model-call cap.
        middleware = cast(
            "list[AgentMiddleware]",
            [
                ToolCallLimitMiddleware(run_limit=config.max_tool_calls, exit_behavior="continue"),
                ModelCallLimitMiddleware(run_limit=config.max_iterations, exit_behavior="end"),
            ],
        )
        agent = create_agent(
            model=model,
            tools=[text_search, structural_search],
            system_prompt=_SYSTEM_PROMPT,
            response_format=ProviderStrategy(FindingsReport, strict=True),
            middleware=middleware,
        )

    async def checks(state: ReviewState, runtime: Runtime) -> dict[str, Any]:
        diff = state.get("diff", "")
        plan = state.get("plan")
        context = state.get("context")
        repo_path = state.get("repo_path") or ""
        # Surface the absolute checkout path FIRST so the agent passes the
        # correct repo_path to text_search/structural_search. Without this the
        # tools run rg/ast-grep against the reviewer's own CWD (a different
        # tree) and every search returns empty — the 0-findings root cause on
        # large PRs (see context/changes/fine-tune-context/diagnosis.md).
        parts: list[str] = []
        if repo_path:
            parts.append(
                f"Repository path (absolute — pass this verbatim as the "
                f"`repo_path` argument to EVERY text_search/structural_search "
                f"call): {repo_path}"
            )
        parts.append(f"Diff:\n{diff}")
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
            result = await _invoke_with_emit_retry(agent, messages)
        except Exception as exc:  # noqa: BLE001 — OQ#1: ANY model-call failure degrades (AGENTS.md §d).
            # The live crash was an uncaught TypeError from the OpenAI SDK parser
            # (choices=None) escaping here and crashing the pipeline — bypassing
            # every downstream fail-safe. Broad on purpose: only BaseException
            # (KeyboardInterrupt/CancelledError) keeps propagating. (The
            # recoverable empty-emit parse failure is retried inside
            # _invoke_with_emit_retry before reaching here; only genuine failures
            # or a failed retry land in this except.)
            shape = _extract_response_shape(exc)
            _log.warning(
                "node checks — agent invoke failed: %s: %s | response_shape=%s — "
                "degraded to empty report; if this repeats, switch to a more potent "
                "model with a larger token budget",
                type(exc).__name__, exc, shape,
            )
            return {"findings": []}
        _log.info("node checks — agent invoke end")
        # TEMPORARY — Phase 4 removes this: full raw dump of the agent result for
        # the diagnosis window (operator request: "log the object you receive from
        # the LLM so we can debug the issue"). DEBUG-gated, so off at default INFO.
        _log.debug("checks raw result: %s", _redact_for_debug(result))
        _log_usage(result)
        return _extract_findings(result)

    return checks


async def _invoke_with_emit_retry(agent: Any, messages: list, max_retries: int = 2) -> Any:
    """Invoke the agent, retrying on the recoverable empty-content structured emit.

    The deepseek reasoning model intermittently emits EMPTY content on the final
    structured-output turn (a `StructuredOutputValidationError` with "Expecting
    value: line 1 column 1 (char 0)") — the model has reasoned over the diff
    (its tool calls returned real results) but its final emit turn comes back
    empty. This is model flakiness, NOT a token-budget issue (observed output is
    ~3-4k tokens vs the 128k ceiling — see diagnosis.md). Retrying with a focused
    "emit valid JSON now" nudge recovers it: the model produces the findings on a
    later attempt. Up to ``max_retries`` retries (3 total attempts) bring
    observed reliability from ~60% (one shot) to ~95%+ (three attempts).

    Any OTHER failure (genuine upstream error, choices=None, etc.) degrades via
    the original broad-except path — this wrapper only special-cases the
    recoverable empty-emit. Consistent with OQ#1 (degrade-never-crash): the
    retry is best-effort; if all attempts fail, the outer except degrades cleanly.
    """
    attempt_messages = list(messages)
    for attempt in range(max_retries + 1):
        try:
            return await agent.ainvoke({"messages": attempt_messages})
        except Exception as exc:
            if not _is_empty_emit_parse_failure(exc) or attempt == max_retries:
                # Genuine failure, or we've exhausted retries — degrade via the
                # caller's broad except (re-raise).
                raise
            _log.warning(
                "node checks — structured emit came back empty (attempt %d/%d, "
                "model flakiness); retrying with an explicit emit nudge",
                attempt + 1, max_retries + 1,
            )
            # Append a focused nudge and retry. The model already did its
            # investigation; it just needs to produce the JSON it has ready.
            attempt_messages = attempt_messages + [
                HumanMessage(
                    content=(
                        "Your previous response was empty. Emit the FindingsReport "
                        "NOW as valid JSON. Do not call any tools and do not "
                        "investigate further — use everything you already found and "
                        "produce the structured FindingsReport this turn."
                    ),
                )
            ]
    # Unreachable — the loop returns or raises.
    raise RuntimeError("unreachable")


def _is_empty_emit_parse_failure(exc: BaseException) -> bool:
    """True iff ``exc`` is the recoverable empty-content structured-output parse failure.

    Matches the deepseek flakiness signature: a `StructuredOutputValidationError`
    (or any exception whose message mentions the structured-output parse failure
    with the "line 1 column 1 (char 0)" empty-content marker). Narrow on purpose
    — genuine upstream errors (choices=None, auth, network) must NOT trigger the
    retry (they degrade via the original broad except).
    """
    name = type(exc).__name__
    msg = str(exc)
    if "StructuredOutputValidation" not in name and "structured output" not in msg.lower():
        return False
    # "line 1 column 1 (char 0)" is the json parser's empty-input marker.
    return "char 0" in msg or "line 1 column 1" in msg


def _redact_for_debug(result: Any) -> str:
    """Render the agent result for DEBUG-level inspection (TEMPORARY — Phase 4 removes this).

    Best-effort, never raises. The diagnosis window (operator request: "log the
    object you receive from the LLM so we can debug the issue") needs the message
    sequence + per-message usage/finish metadata to answer the dimension-map
    questions (iteration count, per-iteration tokens, tool-call pattern). Two
    leakage bounds (prd.md:44): (a) DEBUG-gated — off at the default INFO level
    used in CI/production; (b) ephemeral — removed entirely in Phase 4. Within
    those bounds the operator's explicit request is the full raw dump, so this
    renders message content; it only strips values whose dict keys look like
    secrets (``api_key``/``authorization``/``token`` with a string value).
    """
    try:
        import json

        def _scrub(obj: Any) -> Any:
            if isinstance(obj, dict):
                out = {}
                for k, v in obj.items():
                    kl = str(k).lower()
                    if (kl in {"api_key", "apikey", "authorization", "x-api-key", "token"}) and isinstance(v, str):
                        out[k] = "<redacted>"
                    else:
                        out[k] = _scrub(v)
                return out
            if isinstance(obj, list):
                return [_scrub(x) for x in obj]
            return obj

        def _msg_summary(m: Any) -> dict[str, Any]:
            # Render a compact per-message view: role/type, content length + head,
            # tool calls, and the usage/finish metadata that drives the diagnosis.
            content = getattr(m, "content", None)
            content_str = content if isinstance(content, str) else repr(content)
            entry: dict[str, Any] = {
                "type": type(m).__name__,
                "content_len": len(content_str),
                "content_head": content_str[:500],
            }
            tc = getattr(m, "tool_calls", None)
            if tc:
                entry["tool_calls"] = [
                    {"name": getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else None),
                     "args": _scrub(getattr(c, "args", None) or (c.get("args") if isinstance(c, dict) else None))}
                    for c in tc
                ]
            um = getattr(m, "usage_metadata", None)
            if isinstance(um, dict):
                entry["usage_metadata"] = _scrub(um)
            rm = getattr(m, "response_metadata", None)
            if isinstance(rm, dict):
                entry["response_metadata"] = _scrub(rm)
            return entry

        if isinstance(result, dict):
            view: dict[str, Any] = {"keys": list(result.keys())}
            msgs = result.get("messages")
            if isinstance(msgs, list):
                view["message_count"] = len(msgs)
                view["messages"] = [_msg_summary(m) for m in msgs]
            sr = result.get("structured_response")
            if sr is not None:
                view["structured_response"] = _scrub(sr.model_dump() if hasattr(sr, "model_dump") else sr)
            return json.dumps(view, default=str, ensure_ascii=False)
        return repr(result)[:2000]
    except Exception as exc:  # noqa: BLE001 — debug dump must never break the success path
        return f"<redact_for_debug failed: {type(exc).__name__}: {exc}>"


def _log_usage(result: Any) -> None:
    """Emit a token/usage breadcrumb on the success path (Phase 2, H-B).

    INFO per call so the operator sees completion-token volume; escalates to
    WARNING when ``output_tokens`` approaches the ``_MAX_TOKENS`` ceiling or
    ``finish_reason == "length"`` — the actionable "switch to a more potent model
    with a larger token budget" signal. The failure path is covered by the Phase-1
    exception probe; this runs on success only. Best-effort via
    :func:`_extract_usage` (never raises).
    """
    usage = _extract_usage(result)
    if usage is None:
        return  # missing metadata → skip the breadcrumb, never crash
    near_ceiling = usage.output_tokens >= int(_MAX_TOKENS * 0.9)
    truncated = usage.finish_reason == "length"
    if near_ceiling or truncated:
        _log.warning(
            "node checks — model usage near ceiling: input=%d output=%d total=%d "
            "finish_reason=%s (max_tokens=%d) — output is %s; switch to a more "
            "potent model with a larger token budget",
            usage.input_tokens, usage.output_tokens, usage.total_tokens,
            usage.finish_reason, _MAX_TOKENS,
            "truncated" if truncated else "near the ceiling",
        )
    else:
        _log.info(
            "node checks — model usage: input=%d output=%d total=%d finish_reason=%s",
            usage.input_tokens, usage.output_tokens, usage.total_tokens, usage.finish_reason,
        )


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


@dataclass(frozen=True, slots=True)
class Usage:
    """Token/usage snapshot read from a successful model call's last message.

    Used by the success-path breadcrumb (Phase 2, H-B): emitted as INFO, and
    escalated to WARNING when ``output_tokens`` approaches the ``_MAX_TOKENS``
    ceiling or ``finish_reason == "length"`` — the actionable "switch to a more
    potent model" signal.
    """

    input_tokens: int
    output_tokens: int
    total_tokens: int
    finish_reason: str | None


def _extract_usage(result: Any) -> Usage | None:
    """Best-effort probe of token usage from the agent result's last message.

    Reads ``usage_metadata`` (``input_tokens``/``output_tokens``/``total_tokens``)
    and ``response_metadata`` (``finish_reason``) from the last message — the same
    result shapes :func:`_extract_findings` tolerates (``structured_response`` +
    ``messages``, bare ``messages``). Best-effort: missing metadata or messages →
    ``None`` (the caller skips the breadcrumb). NEVER raises — the free-tier model
    may return a malformed usage block, and a telemetry probe must not break the
    success path.
    """
    msg: Any = None
    if isinstance(result, dict):
        msgs = result.get("messages")
        if isinstance(msgs, list) and msgs:
            msg = msgs[-1]
    if msg is None:
        return None
    usage_meta = getattr(msg, "usage_metadata", None)
    if not isinstance(usage_meta, dict):
        return None
    try:
        return Usage(
            input_tokens=int(usage_meta["input_tokens"]),
            output_tokens=int(usage_meta["output_tokens"]),
            total_tokens=int(usage_meta["total_tokens"]),
            finish_reason=str(getattr(msg, "response_metadata", {}).get("finish_reason")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _extract_findings(result: Any) -> dict[str, Any]:
    """Pull the FindingsReport payload out of the agent result.

    ``create_agent(..., response_format=ProviderStrategy(...))`` surfaces the parsed
    object at the top-level ``structured_response`` key. We accept that, a bare
    FindingsReport/dict, or a messages payload, and defer strict validation to
    ``report`` (the load-bearing host-side re-check). Carries both ``findings``
    and ``optional_findings`` (the style-pickiness bucket).
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
    return {
        "findings": _coerce_finding_list(parsed),
        "optional_findings": _coerce_finding_list(parsed, key="optional_findings"),
    }


def _coerce_finding_list(parsed: Any, key: str = "findings") -> list[dict[str, Any]]:
    """Return the list of finding dicts from a parsed payload, or [].

    ``key`` selects which list to pull — ``findings`` (main) or
    ``optional_findings`` (style bucket). Both hold Finding-shaped dicts.
    """
    if parsed is None:
        return []
    if isinstance(parsed, FindingsReport):
        src = parsed.optional_findings if key == "optional_findings" else parsed.findings
        return [f.model_dump() for f in src]
    if isinstance(parsed, dict) and isinstance(parsed.get(key), list):
        return list(parsed[key])
    return []


def report(state: ReviewState, runtime: Runtime) -> dict[str, Any]:
    """Deterministic: re-validate, inject F{n} ids, sort, cap, compute exit code.

    This is the load-bearing host-side re-check: node outputs come back as plain
    dicts (research.md:114-118), so we MUST model_validate here before emit.
    """
    raw_findings = state.get("findings", [])
    raw_optional = state.get("optional_findings", [])
    _log.info("node report — raw_findings=%d raw_optional=%d", len(raw_findings), len(raw_optional))
    try:
        report_obj = FindingsReport.model_validate(
            {"findings": raw_findings, "optional_findings": raw_optional}
        )
    except ValidationError:
        report_obj = FindingsReport(findings=[], summary="WARNING: report re-validation failed.")

    ordered = sorted(report_obj.findings, key=lambda f: (_SEVERITY_ORDER[f.severity], f.file, f.line))
    capped = _cap_per_dimension(ordered)
    final_report = report_obj.model_copy(update={"findings": capped})

    # Emit ONLY the validated report object. Do NOT re-emit ``findings`` — it uses
    # the ``add`` reducer (state.py), so re-emitting would append the validated
    # finding onto the one ``checks`` already added, doubling every finding (the
    # duplicate-findings bug). The validated findings live inside ``report``; the
    # ``report`` key is last-wins (no reducer) so it replaces cleanly.
    return {"report": final_report}


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
