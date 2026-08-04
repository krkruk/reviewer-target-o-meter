# graph-bugfixing Implementation Plan

## Overview

Fix the pipeline crash observed on a large diff. Despite the branch name
`fix/graph-recursion-issue`, the live stacktrace shows the crash is **not** a
`GraphRecursionError` — it is an uncaught `TypeError: 'NoneType' object is not
iterable` from the OpenAI SDK parser (`openai/lib/_parsing/_completions.py:98`,
`for choice in chat_completion.choices`) when the model returns `choices: None`,
escaping the `checks` node's bare `await agent.ainvoke(...)`. Add an error
boundary in `checks` (any exception → empty findings + advisory exit), raise
`max_tokens` for the reasoning model, and add usage telemetry so the operator
gets the actionable signal to switch to a more potent model.

## Current State Analysis

The crash chain, traced from the stacktrace:

1. `checks` node → `await agent.ainvoke({"messages": messages})`
   (`agent/nodes.py:211`, **no try/except**).
2. Inner `create_agent` model node → `langchain_openai._agenerate`. Because
   `response_format=ProviderStrategy(FindingsReport, strict=True)` puts
   `response_format` (json_schema) in the payload, it routes through the SDK's
   `chat.completions.parse()` path (`langchain_openai/chat_models/base.py:1983`).
3. `parse()` → `parse_chat_completion` (`openai/lib/_parsing/_completions.py:98`)
   → `for choice in chat_completion.choices` → **`chat_completion.choices is None`**
   → `TypeError: 'NoneType' object is not iterable`.
4. The `TypeError` propagates out of the inner agent, out of the `checks` node,
   out of `compiled.ainvoke`. `graph.py:72` catches **only** `GraphRecursionError`,
   so it crashes the pipeline (exit 1). The downstream fail-safes
   (`to_report`'s `except (ValidationError, TypeError, ...)`, `report`'s
   `except ValidationError`) **never run** — they sit below an `ainvoke` that already
   blew up.

The two `[NOTE] During task with name 'model'/'checks'` lines are LangGraph
**nested-task annotations** (the inner agent runs as a task inside the outer node),
combined with the `recursion_limit=40` log line — which made "recursion" a
reasonable-but-wrong read of the symptom.

Verified by direct investigation (bash; signatures + source read):

- `ModelCallLimitMiddleware.__init__(*, thread_limit=None, run_limit=None, exit_behavior='end')`
  — the `run_limit=config.max_iterations` call at `nodes.py:188` is **correct**;
  not a silent-ignore bug.
- The outer graph is a straight line `START → context_load → plan_discovery → checks
  → report → END` with no self-loops — it cannot itself recurse.
- No `astream` anywhere; the whole pipeline is `ainvoke`-based.
- `langchain_openai._agenerate` attaches the raw HTTP body to the raised exception
  (`e.response = raw_response.http_response`, stacktrace lines 297–299) — so the
  real response shape (`choices`/`finish_reason`/`usage`) is recoverable from the
  exception itself, for free, on the failure path.

### Key Discoveries:

- **Response-shape probe lives on the exception.** A `BaseCallbackHandler` would
  NOT fire for the `choices=None` crash (parsing fails before `_agenerate`
  returns). The probe MUST read `getattr(exc, "response", ...)` inside the `except`
  block — not a callback.
- **`report()` reads only `state["findings"]`** (`nodes.py:256`), so `checks`
  returning `{"findings": []}` flows cleanly into an empty report; the actionable
  "switch model" signal rides the `WARNING` log (the existing degrade convention).
- **Reasoning-token budget.** `research.md:316-318` explicitly warned reasoning
  tokens count against `max_completion_tokens` and to "set max_tokens high enough
  that reasoning + JSON both fit". `_MAX_TOKENS = 8192` (`provider.py:23`) is too
  tight for a reasoning model on a large diff (this run: 83,883 raw → 36,528 capped
  chars).
- **DI seam already exists.** `build_checks_node(config, agent=None)`
  (`nodes.py:169`) lets tests inject a fake agent — used by
  `test_end_to_end_mocked_llm_emits_report` (`test_graph.py:126-168`).
- **Logger convention.** Single `reviewer_target_o_meter` logger, `%(levelname)s:
  %(message)s` on stderr (`_util.py`); `warn()`/`_log.warning` is the degrade
  convention. The literal `WARNING:` substring is asserted on by `test_cli.py`.

## Desired End State

- A `TypeError`/`APIError`/any exception from the agent's model call **degrades**
  the `checks` node to empty findings + advisory exit (exit 0), logged as a
  `WARNING` — never a pipeline crash.
- The failure `WARNING` names the exception type + message **and** the raw response
  shape (`choices`/`finish_reason`/`usage` when present on the exception), so the
  upstream cause is visible without a live re-run.
- `_MAX_TOKENS` is raised to give the reasoning model headroom.
- A token/usage breadcrumb is emitted on every successful model call, escalating to
  `WARNING` when output tokens approach the ceiling or `finish_reason == "length"` —
  the actionable signal to **switch to a more potent model with a larger token
  budget** (the operator's stated requirement).
- A real-faithful unit test (via the DI seam) reproduces the crash mode and asserts
  the degrade, closing the gap that the `_BoomGraph` outer-boundary test left open.

## What We're NOT Doing

- **Not** renaming the branch (operator's decision).
- **Not** hardening the inner-graph recursion limit. The recursion machinery is
  intact; recursion is not the failure.
- **Not** switching the structured-output strategy (`json_schema`+`strict` stays —
  locked in AGENTS.md §d). If H-C (model doesn't honor strict) turns out to be the
  live cause, that's a follow-up, surfaced by the new logging — out of scope here.
- **Not** switching models — the new logging gives the operator the signal to do
  that.

## Implementation Approach

Two surgical changes, both inside the existing degrade philosophy:

1. **Error boundary in `checks`** (H-A): wrap the single `await agent.ainvoke(...)`
   in a broad `try/except Exception`. On catch: build a diagnostic string
   (exception type + message + the raw response shape extracted from
   `getattr(exc, "response", None)` when langchain_openai attached it), log it as a
   `WARNING` with an explicit "switch to a more potent model with a larger token
   budget" hint, and `return {"findings": []}`. The `report` node then emits the
   advisory empty report (exit 0).
2. **Max-tokens headroom + telemetry** (H-B): raise `_MAX_TOKENS`; emit a
   token/usage breadcrumb on the success path from the agent result's last message
   (`usage_metadata` / `response_metadata`), escalating to `WARNING` near the
   ceiling.

## Critical Implementation Details

- **Response-shape probe lives on the exception, not a callback.**
  `langchain_openai._agenerate` attaches `raw_response.http_response` to the
  exception before re-raising. A `BaseCallbackHandler` would NOT fire for the
  `choices=None` crash (parsing fails before `_agenerate` returns), so the probe
  MUST read `getattr(exc, "response", ...)` inside the `except` block. The raw
  response body may need `.json()`/async-aware access; read it defensively
  (best-effort, never re-raise from the probe itself).
- **Token breadcrumb reads from the result, on success only.**
  `result["messages"][-1]` carries `usage_metadata` (`input_tokens`/
  `output_tokens`/`total_tokens`) and `response_metadata` (`finish_reason`) on a
  normal completion. The failure path never reaches this; the exception-side probe
  covers failure diagnostics, this breadcrumb covers success-side
  "approaching the ceiling" warnings.
- **Keep the `WARNING:` substring intact.** The degrade convention is asserted on
  by `tests/test_cli.py`; log via the module `_log` at WARNING.

---

## Phase 1: checks-node error boundary (H-A) — stop the crash

### Overview

Wrap `agent.ainvoke` in `checks` so any model/agent exception degrades to empty
findings + advisory exit instead of crashing the pipeline. Add a real-faithful
unit test via the DI seam.

### Changes Required:

#### 1. Error boundary + exception/response-shape logging in `checks`

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: The single load-bearing robustness fix. Today `await agent.ainvoke(...)`
at line 211 has no try/except, so a `TypeError` from the SDK parser (or any
`APIError`) escapes the node and crashes the pipeline (only `GraphRecursionError`
is caught upstream). Wrap it: on any exception, log a `WARNING` with the exception
type, message, the extracted raw response shape (when langchain_openai attached
`.response`), and an explicit "switch to a more potent model" hint, then
`return {"findings": []}` so `report` emits the advisory empty report (exit 0).

**Contract**:

- `checks` becomes: build messages → log INFO "agent invoke start" (existing) →
  `try: result = await agent.ainvoke(...)` → `except Exception as exc:` →
  (a) best-effort extract response shape via a small helper that reads
  `getattr(exc, "response", None)` and, if present, pulls `choices`/
  `finish_reason`/`usage` defensively (wrap that extraction in its own try/except
  so the probe never re-raises);
  (b) `_log.warning("node checks — agent invoke failed: %s: %s | response_shape=%s — "
  "degraded to empty report; if this repeats, switch to a more potent model with a "
  "larger token budget", type(exc).__name__, exc, shape)`;
  (c) `return {"findings": []}`.
  On success: keep the existing INFO "agent invoke end" +
  `return _extract_findings(result)`.
- The except must be broad (`Exception`) — the point is "any model-call failure
  degrades". Do NOT catch `BaseException` (keep KeyboardInterrupt/CancelledError
  propagating).
- No change to `_extract_findings` / `_coerce_finding_list` / the `report` node —
  they already handle empty findings.

#### 2. Real-faithful unit test reproducing the crash mode

**File**: `reviewer-target-o-meter/tests/test_graph.py` (and/or a focused
`tests/test_nodes.py` addition)

**Intent**: The existing `test_graph_recursion_error_emits_partial_report` fakes
the error at the outer boundary via `_BoomGraph` and never exercises the real
`checks` node — the gap that hid this bug. Add a test that drives the **real**
`checks` node through the DI seam with a fake agent whose `ainvoke` raises
`TypeError("'NoneType' object is not iterable")` (mirroring the actual stacktrace),
and asserts the node returns `{"findings": []}` (not a raise) and that the run
produces an empty `FindingsReport` with `exit_code == 0`. Add a second case raising
a generic `Exception` to prove the boundary is broad.

**Contract**:

- Build `checks = build_checks_node(_cfg(), agent=_RaisingAgent(TypeError(...)))`
  (the DI seam at `nodes.py:181` already accepts `agent=`), invoke it directly
  (`asyncio.run(checks(state))`) and assert the returned dict is
  `{"findings": []}`. Then run the full graph (`arun_review`) with the raising
  agent injected (mirroring `test_end_to_end_mocked_llm_emits_report`'s monkeypatch
  of `build_graph`) and assert `report_obj.findings == []` and
  `report_obj.exit_code == 0`.
- The fake agent mirrors `_FakeAgent` (`test_graph.py:126`) but its `ainvoke`
  raises.

### Success Criteria:

#### Automated Verification:

- `make test` (unit tests, excludes smoke) passes, including the new
  real-faithful degrade test.
- `make check` (ruff + mypy) passes — note: the broad `except Exception` may need
  a `# noqa` or a specific rationale comment matching the repo's existing degrade
  style; the `report` node's `except ValidationError` shows the tolerated pattern,
  so broaden intentionally with a comment citing OQ#1.
- The new test fails (red) if the try/except is removed — proving it guards the
  real boundary.

#### Manual Verification:

- `make run DIR=../../target-o-meter/` against the same large diff that crashed no
  longer raises; instead it logs a `WARNING: node checks — agent invoke failed: ...`
  line and exits 0 with an empty/partial report.
- Confirm no `OPENROUTER_API_KEY` or absolute host path leaks into the logged
  response_shape (best-effort extraction must redact or omit headers).

**Implementation Note**: Pause after Phase 1 automated verification passes — the
live `make run` repro is the real proof the crash is gone before adding telemetry
in Phase 2.

---

## Phase 2: max_tokens headroom (H-B) + token/usage telemetry

### Overview

Mitigate the most likely upstream trigger (reasoning model exhausting the token
budget → empty JSON → `choices: None`) and give the operator the runtime signal to
decide when to switch models.

### Changes Required:

#### 1. Raise `_MAX_TOKENS` for the reasoning model

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/provider.py`

**Intent**: `research.md:316-318` warned reasoning tokens count against the budget
and to size `max_tokens` so "reasoning + JSON both fit". 8192 is too tight for a
reasoning model on a large diff. Raise the default so the model has room to reason
AND emit the JSON.

**Contract**: Bump `_MAX_TOKENS` from `8192` to `16384` (doubling, a conservative
first step that the new usage breadcrumb will validate). Keep it as the single
post-construction assignment at `provider.py:39`. Update the adjacent comment to
reference the reasoning-token rationale.

#### 2. Token/usage breadcrumb on the success path

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Emit a usage breadcrumb per model call so the operator can see when
completion tokens approach the `max_tokens` ceiling — the actionable "switch to a
more potent model" signal. On the success path only (the failure path is covered
by the Phase-1 exception probe), read `usage_metadata`/`response_metadata` from
the agent result's last message and log it.

**Contract**: After a successful `await agent.ainvoke(...)`, before
`return _extract_findings(result)`, extract the last AI message from `result`
(handle both `result["messages"][-1]` and the `structured_response` shapes
`_extract_findings` already tolerates) and log an INFO breadcrumb:
`"node checks — model usage: input=%s output=%s total=%s finish_reason=%s"` from
`usage_metadata` (`input_tokens`/`output_tokens`/`total_tokens`) and
`response_metadata` (`finish_reason`). Best-effort: missing metadata → skip the
line (never raise). If `output_tokens` is within ~10% of `_MAX_TOKENS` or
`finish_reason == "length"`, escalate that line to `WARNING` with the "switch to a
more potent model with a larger token budget" hint — this is the direct trigger
for the model-switch decision.

### Success Criteria:

#### Automated Verification:

- `make test` passes; add a unit assertion that the usage-extraction helper is
  best-effort (does not raise when `usage_metadata`/messages are absent) — covers
  the `result` shapes the fake agent returns.
- `make check` passes (ruff + mypy).

#### Manual Verification:

- `make run DIR=../../target-o-meter/` on the large diff: confirm the usage
  breadcrumb appears on success (or, on degrade, the Phase-1 WARNING with
  response_shape). If `finish_reason=length` or output tokens near the ceiling
  appear, that's the confirmation of H-B and the signal to switch models / raise
  the budget further.

---

## Testing Strategy

### Unit Tests:

- **Phase 1 (load-bearing)**: real-faithful degrade test via the DI seam — fake
  agent raising `TypeError` (mirrors the actual crash) → `checks` returns
  `{"findings": []}`; full-graph run yields empty `FindingsReport`,
  `exit_code == 0`. Plus a generic-`Exception` case proving the boundary is broad.
  Proves the pipeline can no longer crash on this failure mode.
- **Phase 2**: best-effort usage-extraction helper does not raise on missing
  metadata / empty messages.

### Integration Tests:

- The existing `test_end_to_end_mocked_llm_emits_report` and the `_BoomGraph`
  recursion test stay green (no regression to the outer-boundary fail-safe or the
  happy path).

### Manual Testing Steps:

1. `make run DIR=../../target-o-meter/` against the original crashing diff — must
   NOT raise; expect a `WARNING: node checks — agent invoke failed: ...` (degrade)
   or a normal report with a usage breadcrumb.
2. Confirm the `WARNING` line names the exception type and (when available) the
   response shape, and carries the "switch to a more potent model" hint.
3. Confirm no secrets / absolute paths leak in the logged response shape.

## Performance Considerations

- Raising `_MAX_TOKENS` 8192 → 16384 gives the reasoning model room at the cost of
  slightly higher latency/wall-clock on the free tier (already bounded by the
  existing `TimeoutPolicy(run_timeout=120)` on `checks`, `graph.py:42`). No new
  latency surface; the timeout is the binding NFR guard.

## References

- Crash site: `openai/lib/_parsing/_completions.py:98`
  (`for choice in chat_completion.choices`).
- Bare `ainvoke`: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py:211`.
- Only-`GraphRecursionError` catch:
  `reviewer-target-o-meter/src/reviewer_target_o_meter/graph.py:72`.
- `_MAX_TOKENS`: `reviewer-target-o-meter/src/reviewer_target_o_meter/provider.py:23,39`.
- Reasoning-token warning:
  `context/archive/2026-08-01-agent-runtime-finding-schema/research.md:316-318`.
- DI seam: `agent/nodes.py:169-189`; existing fake-agent test:
  `tests/test_graph.py:126-168`.
- Fail-safe contract: AGENTS.md §d (OQ#1), §e.

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands.

### Phase 1: checks-node error boundary (H-A)

#### Automated

- [x] 1.1 Add try/except Exception around `agent.ainvoke` in `checks` + best-effort response-shape probe from `exc.response`; degrade to `{"findings": []}` with a WARNING carrying the "switch model" hint — ca21258
- [x] 1.2 Add real-faithful degrade test via DI seam (fake agent raising `TypeError` mirroring the crash) + a generic-`Exception` case; assert empty findings + exit_code 0 — ca21258
- [x] 1.3 `make test` passes; `make check` (ruff + mypy) passes — ca21258

#### Manual

- [x] 1.4 `make run DIR=../../target-o-meter/` on the crashing diff no longer raises; logs `WARNING: node checks — agent invoke failed: ...`; exits 0 with empty/partial report — VERIFIED live vs PR #26 (krkruk/target-o-meter): the exact TypeError reproduced and degraded (`response_shape=choices=None finish_reason=None usage=None`, exit_code=0, comment posted) — ca21258

### Phase 2: max_tokens headroom (H-B) + token/usage telemetry

#### Automated

- [x] 2.1 Raise `_MAX_TOKENS` (final: 60000) in `provider.py` with updated reasoning-token comment — tuned live (8192 → 16384 → 48000 → 60000) until the model stopped exhausting the budget
- [x] 2.2 Add best-effort token/usage breadcrumb on the success path; escalate to WARNING (with switch-model hint) when output tokens near the ceiling or `finish_reason == "length"`
- [x] 2.3 Unit-assert the usage-extraction helper is best-effort (no raise on missing metadata)
- [x] 2.4 `make test` passes; `make check` passes
- [x] 2.6 Catch `NodeTimeoutError` in `arun_review` (degrades to empty report + advisory exit) — surfaced live in 2.5: raising `_MAX_TOKENS` let the reasoning model reason past the 120s `run_timeout`, and the TimeoutPolicy raises outside the in-node Phase-1 boundary so `arun_review` (GraphRecursionError-only) crashed; TDD'd RED→GREEN + manual verify

#### Manual

- [x] 2.5 `make run DIR=../../target-o-meter/` shows the usage breadcrumb (success) or the Phase-1 WARNING (degrade); confirm H-B signal visibility — VERIFIED live vs PR #26 multiple times (nemotron degrade on oversized diff → DeepSeek success)

### Phase 3: model switch + diff cap + duplicate-findings fix (post-validation)

> Added after live validation surfaced three issues the original plan didn't
> cover: (a) the free nemotron slug can't handle the raised diff size; (b) the
> diff input itself needed its own cap distinct from the token budget; (c) a
> long-standing duplicate-findings bug (1 model finding → F1/F2 identical).

#### Automated

- [x] 3.1 Switch `DEFAULT_MODEL` to paid `deepseek/deepseek-v4-flash-0731` (config.py + .env.example + test_config.py) — the free nemotron exhausted its budget / timed out on large diffs; DeepSeek honors strict structured output and runs clean
- [x] 3.2 Raise `MAX_DIFF_CHARS` to 45000 (diff.py) — distinct from the token budget; sizes the `checks` prompt input
- [x] 3.3 Fix duplicate-findings bug: `ReviewState.findings` uses the `add` reducer, and `report` re-emitted `findings` → every finding doubled; added `report: FindingsReport` (last-wins) to the schema + `report` node emits only `{"report": ...}`. TDD'd RED (1→2) → GREEN (1→1); updated 4 report-node tests to the new return shape
- [x] 3.4 `make test` passes (133); `make check` passes

#### Manual

- [x] 3.5 `make run` vs PR #26 with DeepSeek + 60k/45k caps: clean run, `finish_reason=stop`, usage `input=24521 output=258`, 0 findings (no duplicates), comment posted, exit 0
