# DEBUG Observability + Empty-Emit Retry Fix + CI Trigger — Plan Brief

> Full plan: `context/changes/debug-logging-and-infra-correction/plan.md`

## What & Why

The reviewer emits 0 findings on `krkruk/target-o-meter#28` in CI but works
locally on the same commit. The CI log implicates a silent-degrade: the model
emitted ~25 output tokens (`output=25 finish_reason=stop`) — a valid-but-empty
FindingsReport that parses cleanly, so the existing retry (which only catches
*parse-failure* exceptions) never fires. We're adding DEBUG observability so the
next run is diagnosable, closing the empty-emit retry gap, then triggering a
diagnostic run of PR #28.

## Starting Point

The tool already has a logging channel (`_util.configure_logging`), DEBUG-gated
best-effort probes (`_log_dir_tree`), and a usage breadcrumb (`_log_usage`). The
retry wrapper `_invoke_with_emit_retry` recovers the model's empty-content
*parse failure* but not a *valid-but-empty* emit. The consumer installs the tool
from the tool repo's `master` via git URL — so new tool logging only reaches CI
once published to a ref the workflow can pin.

## Desired End State

A PR #28 CI run whose step log is fully diagnosable (redacted env dump, head/base
git SHA + branch, inbound prompt char count, per-turn model trace + final emit
preview), and a `checks` node that retries the valid-but-empty flake instead of
silently emitting 0 findings. The consumer's `review.yml` is pinned at the tool's
`debug-ci-logging` branch and committed to trigger that run.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Delivery to CI | Tool `debug-ci-logging` branch + pin workflow `@debug-ci-logging` | Iterate on logging without repeatedly merging to tool master; reproduce with full traces. | Plan |
| Env redaction | Pattern denylist `/TOKEN\|KEY\|SECRET\|PASSWORD\|CREDENTIAL/i` | Future-proof; honors AGENTS.md §d without a brittle allowlist. | Plan |
| Retry scope | Observability + close the empty-emit gap | Strongly evidenced failure mode; low-risk fix behind the existing retry wrapper. | Plan |
| Trace depth | Per-turn message trace | Reveals the core unknown: did the model call tools, how many turns, what the empty emit looked like. | Plan |
| Retry guard | Retry iff empty AND zero tool-call turns | Precise — won't retry a diff the model genuinely investigated and found clean. | Plan |
| Execution | Plan, then execute + commit + push + trigger now | Honors the "trigger by committing" intent end-to-end in one session. | Plan |

## Scope

**In scope:**
- Redacted env-var dump, head/base git SHA + branch breadcrumb, inbound prompt
  char count, outbound per-turn message trace + final emit preview (DEBUG).
- Empty-emit retry fix (empty both lists + zero tool-call turns → retry).
- Consumer `review.yml` pinned at `@debug-ci-logging` + `MODEL` passthrough,
  committed to trigger PR #28.

**Out of scope:**
- Switching the default model for the diagnostic run (keep deepseek to reproduce).
- Merging `debug-ci-logging` to master / reverting the pin (Phase 4 follow-up).
- Raw-HTTP provider callbacks; prompt/structured-output contract changes.

## Architecture / Approach

Tool-side changes on `debug-ci-logging`: probes follow the existing
`_log_dir_tree`/`_extract_usage` pattern (DEBUG-gated, best-effort, never raise).
`diff.py` logs the SHA/branch breadcrumb (it holds the `git.Repo`); `nodes.py`
logs the inbound char count before invoke and the per-turn trace + final emit
after. The retry predicate reuses `_extract_findings` to detect emptiness and
counts `AIMessage.tool_calls` to detect "no investigation." Consumer-side: one
workflow pin + one `MODEL` env line, committed on the feature branch to trip the
`pull_request` review workflow.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. DEBUG observability | Env dump, SHAs, inbound/outbound traces | Detached-HEAD branch-name fallback in CI must not raise |
| 2. Empty-emit retry fix | Retry valid-but-empty + zero-tool-call emits | Defining "suspicious" precisely so clean diffs aren't retried |
| 3. Workflow pin + trigger | `@debug-ci-logging` pin, commit, trip PR #28 | Branch ref must resolve in the runner's install step |
| 4. Stabilization (follow-up) | Merge to master, revert pin | Conditional on the run's output |

**Prerequisites:** write access to both repos; `OPENROUTER_API_KEY` set in the
consumer repo secrets; PR #28 open on `feature/add-user-score-dashboard-implementation`.
**Estimated effort:** ~1 session (Phases 1–3 executed now; Phase 4 after reading the run).

## Open Risks & Assumptions

- The empty-emit may be OpenRouter free-tier routing flakiness rather than a
  deterministic CI difference — the per-turn trace will distinguish "model
  investigated then emptied" from "model emitted empty immediately."
- If the model calls ≥1 tool then empties, the new retry won't fire by design;
  the trace surfaces that pattern for a Phase-4 tuning decision.
- `vars.MODEL` on the consumer repo is assumed unset (→ default model); if set,
  it changes the diagnostic model unexpectedly.

## Success Criteria (Summary)

- The triggered PR #28 run's step log shows the new DEBUG breadcrumbs and tokens
  are `<redacted,set>`.
- The empty-emit retry recovers findings on a reproducible 0-finding run (or the
  trace explains why it stayed empty).
- `make check` + `make test` green on `debug-ci-logging`.
