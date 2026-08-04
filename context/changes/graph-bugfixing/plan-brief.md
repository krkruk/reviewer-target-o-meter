# graph-bugfixing — Plan Brief

> Full plan: `context/changes/graph-bugfixing/plan.md`

## What & Why

The pipeline crashes on a large diff. Despite the branch name
`fix/graph-recursion-issue`, the live stacktrace shows the crash is **not** a
`GraphRecursionError`: it is an uncaught `TypeError: 'NoneType' object is not
iterable` from the OpenAI SDK parser when the model returns `choices: None`,
escaping the `checks` node's bare `await agent.ainvoke(...)`. The codebase only
catches `GraphRecursionError`, so this `TypeError` (and any `APIError`/timeout/429)
crashes the pipeline, bypassing every downstream fail-safe — violating the OQ#1
"never crash the pipeline" contract.

## Starting Point

- `checks` node (`agent/nodes.py:191-215`) calls `await agent.ainvoke(...)` at
  line 211 with **no try/except**.
- `arun_review` (`graph.py:65-79`) catches **only** `GraphRecursionError`.
- A DI seam exists (`build_checks_node(config, agent=None)`, `nodes.py:169`),
  already used by the mocked-LLM test.
- `_MAX_TOKENS = 8192` (`provider.py:23`), set post-construction.

## Desired End State

Any exception from the agent's model call degrades `checks` to empty findings +
advisory exit (exit 0), logged as a `WARNING` that names the exception type +
response shape and carries a "switch to a more potent model" hint. `max_tokens` is
raised for the reasoning model, and a usage breadcrumb on every model call gives
the operator the runtime signal to switch models — never a pipeline crash.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Branch name | Keep `fix/graph-recursion-issue` | Operator's explicit decision not to rename. | Plan |
| Root cause | Uncaught model-call exception (not recursion) | Stacktrace bottom is a `TypeError` from the SDK parser, not `GraphRecursionError`; verified the recursion machinery is intact. | Plan (investigation) |
| Error boundary scope | Broad `except Exception` in `checks` | The point is "any model-call failure degrades" (OQ#1); only `GraphRecursionError` is caught today. | Plan |
| Response-shape probe | Read `exc.response` inside the except | langchain_openai attaches the raw HTTP body to the exception; a callback would not fire for this parse-time crash. | Plan |
| Upstream trigger mitigation | Raise `_MAX_TOKENS` 8192 → 16384 + usage telemetry | Reasoning model likely exhausts the budget before emitting JSON → `choices: None` (research.md:316-318). | Plan |
| Structured-output strategy | Keep `json_schema`+`strict` (no change) | Locked in AGENTS.md §d; if the model doesn't honor it, that's a follow-up surfaced by the new logging. | Plan |
| Test shape | Real-faithful DI-seam test (not `_BoomGraph`) | The outer-boundary fake sidesteps the real `checks` node — the gap that hid this bug. | Plan |

## Scope

**In scope:**

- `try/except Exception` boundary around `agent.ainvoke` in `checks` with
  best-effort response-shape logging + degrade to empty findings.
- Real-faithful unit test (DI seam): fake agent raising `TypeError` mirroring the
  crash + a generic-`Exception` case.
- Raise `_MAX_TOKENS` 8192 → 16384.
- Token/usage breadcrumb on the success path, escalating to `WARNING` near the
  ceiling.

**Out of scope:**

- Branch rename.
- Inner-graph recursion-limit hardening (not the failure).
- Structured-output strategy change (`json_schema`+`strict` stays).
- Model switch (logging gives the operator the signal to do that).

## Architecture / Approach

Two surgical changes inside the existing degrade philosophy:

1. **`checks` error boundary** — wrap the single `agent.ainvoke` call; on catch,
   read `getattr(exc, "response", ...)` for the response shape, log a `WARNING`
   with the "switch model" hint, return `{"findings": []}` → `report` emits the
   advisory empty report (exit 0).
2. **`max_tokens` + telemetry** — raise the budget; log usage per call on the
   success path, escalating when output tokens approach the ceiling or
   `finish_reason == "length"`.

No graph-shape, state-schema, or structured-output-strategy change.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. checks-node error boundary | Pipeline no longer crashes on any model-call exception; real-faithful test guards the boundary | Broad `except Exception` must not swallow `CancelledError`/`KeyboardInterrupt`; mypy/ruff may need a rationale comment |
| 2. max_tokens + telemetry | Reasoning model gets token headroom; operator gets the "switch model" signal | The `16384` bump is a conservative first step — the usage breadcrumb validates it; if H-C (model ignores strict) is the real cause, this alone won't fix the empty-report rate |

**Prerequisites:** reproducible large diff (`../../target-o-meter/`) that triggered
the crash; `OPENROUTER_API_KEY` for the live `make run` confirmation.
**Estimated effort:** ~1 session across 2 phases (Phase 1 is the load-bearing fix;
Phase 2 is mitigation + telemetry).

## Open Risks & Assumptions

- **H-B is an inference, not yet confirmed live.** The reasoning-token-exhaustion
  trigger is the most likely cause of `choices: None` but is not yet reproducible
  at will; the new telemetry confirms or rejects it at runtime. If H-C (model
  doesn't honor `json_schema`+`strict`) is the real cause, the pipeline stops
  crashing but may still produce empty reports on large diffs — that becomes a
  follow-up.
- **`exc.response` shape is best-effort.** langchain_openai attaches the raw HTTP
  body, but accessing it (possibly async / `.json()`) may fail on some exception
  types; the probe is wrapped so it never re-raises.
- **`16384` max_tokens** is a conservative doubling; it slightly raises free-tier
  latency, bounded by the existing `TimeoutPolicy(run_timeout=120)`.

## Success Criteria (Summary)

- The original crashing diff no longer raises; it logs a `WARNING` and exits 0
  with an empty/partial report.
- A real-faithful unit test reproduces the crash mode and asserts the degrade
  (fails red if the boundary is removed).
- A usage breadcrumb is visible on success, with a `WARNING` escalation near the
  token ceiling — the operator's signal to switch models.
