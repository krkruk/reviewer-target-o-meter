# DEBUG Observability + Empty-Emit Retry Fix + CI Trigger — Implementation Plan

## Overview

`reviewer-target-o-meter` emits 0 findings on `krkruk/target-o-meter#28` in CI
while working locally on the same commit. This plan adds DEBUG-level
observability (redacted env dump, git SHAs, inbound/outbound payload traces, a
per-turn model trace), closes the valid-but-empty-emit retry gap that the CI log
implicates, then pins the consumer's `review.yml` at a tool debug branch and
commits it to trigger a diagnostic run of PR #28.

## Current State Analysis

The CI step log shows the failure clearly:

```
INFO: node checks — model usage: input=58396 output=25 total=58421 finish_reason=stop
INFO: node report — raw_findings=0 raw_optional=0
INFO: review complete — findings=0 flagged=0 exit_code=0
```

- **Smoking gun:** `output=25` with `finish_reason=stop` — the model emitted
  ~25 output tokens and stopped voluntarily. `{"findings":[],"optional_findings":[],"summary":""}`
  is ~25 tokens, i.e. a **valid-but-empty FindingsReport**. It is not a
  token-budget issue (`_MAX_TOKENS=128000`, reasoning tokens are separate).
- **No retry fired:** the log has neither `structured emit came back empty
  (attempt …)` nor `agent invoke failed`. So the empty report parsed cleanly —
  no exception, hence `_invoke_with_emit_retry` (nodes.py:382) never retried.
  That wrapper only retries on `_is_empty_emit_parse_failure`, which requires a
  `StructuredOutputValidationError` *exception*; a valid-but-empty emit raises
  nothing. This is the silent-degrade-to-0 mode logged in `lessons.md` and the
  fine-tune-context diagnosis.
- **`input=58396` ≈ the full assembled prompt size** on the final structured
  turn — suggesting the model may have made **zero tool calls** and emitted
  empty immediately. Unconfirmable today: there is no per-turn trace, no
  outbound-response preview, no assembled-prompt char count.
- **Misleading breadcrumb:** `review start — base_ref=None`. `config.base_ref`
  reads `BASE_REF`; `diff.py` separately reads `GITHUB_BASE_REF` and resolved
  `origin/master` (diff still = 171637 chars). The diff is fine; the breadcrumb
  just misleads.
- **Delivery wrinkle:** the consumer installs the tool from the tool repo's
  `master` (`git+...reviewer-target-o-meter#subdirectory=...`). New tool logging
  only reaches CI once it's on master — so we land it on a `debug-ci-logging`
  branch and pin the workflow there for the diagnostic run.

### Key Discoveries:

- `_invoke_with_emit_retry` (nodes.py:382) retry only triggers on a parse
  *failure* exception via `_is_empty_emit_parse_failure` (nodes.py:430); a
  valid-but-empty report slips through untouched.
- `_extract_findings` / `_coerce_finding_list` (nodes.py:563, 588) already
  coerce the agent result's `structured_response`/`messages` into finding lists
  — reusable to detect "empty" inside the retry loop.
- The agent result exposes the full `messages` history (each `AIMessage` carries
  `tool_calls`, `content`, `usage_metadata`) — the per-turn trace and the
  tool-call-turn counter can both be derived from it without a provider callback.
- `_util.configure_logging` + `get_logger` + the `_log_dir_tree` DEBUG probe
  (cli.py:138) are the established pattern: DEBUG-gated, best-effort, never
  raises. The new probes follow it.
- `diff.compute_diff` (diff.py:46) already holds the `git.Repo` and the resolved
  `base` and logs `diff computed — base=%s …`; head/base SHA + branch belong here.
- Existing tests: `test_logging.py` (channel contract) and `test_nodes.py`
  (`_extract_usage` best-effort probe pattern, `TestExtractUsageBestEffort`) are
  the templates for the new probes' unit tests.

## Desired End State

- A CI run of `krkruk/target-o-meter#28` whose step log shows, at DEBUG: a
  redacted env-var dump; head + base git SHA and branch names; the assembled
  inbound prompt char count (system prompt + HumanMessage); and a per-turn trace
  of every model turn (role, tool calls, token counts, truncated content) plus
  the final `structured_response` preview.
- A `checks` node that retries a valid-but-empty emit (0 findings AND 0
  optional_findings AND zero tool-call turns) with the emit-nudge, recovering
  the flake instead of silently emitting 0 findings.
- The consumer's `review.yml` pinned at `@debug-ci-logging` and committed on the
  feature branch so the push triggers the diagnostic review run on PR #28.
- Verification: `make check` + `make test` green on `debug-ci-logging`; the
  triggered PR #28 review run is observable with the new breadcrumbs.

## What We're NOT Doing

- **Not switching the default model** off `deepseek/deepseek-v4-flash-0731` for
  the diagnostic run — we keep it to *reproduce* the failure (switching would
  mask whether the retry fix or the model fixed it). A permanent model decision
  is deferred to Phase 4 after reading the run.
- **Not merging `debug-ci-logging` to tool master or reverting the workflow pin
  in this session** — that is Phase 4 (post-diagnosis cleanup).
- **Not adding a raw-HTTP-provider callback** — the per-turn message trace gives
  the needed visibility without wire-level instrumentation (and without auth-
  header leak risk).
- **Not changing the structured-output contract** (`ProviderStrategy(FindingsReport,
  strict=True)`) or the prompt — the fix is host-side retry + observability.
- **Not executing the reviewed project's commands** (PRD Non-Goal, unchanged).

## Implementation Approach

Two tool-side code phases on a `debug-ci-logging` branch, one consumer-side
trigger phase, one deferred cleanup phase. Observability first (Phase 1) so the
diagnostic run is rich even before the behavior fix; the retry fix (Phase 2)
rides the same branch. Phase 3 pins the consumer workflow at that branch and
commits it to trip PR #28's review. All new probes mirror the existing
`_log_dir_tree` / `_extract_usage` conventions: DEBUG-gated, best-effort
(wrapped so they never raise out of the pipeline), and unit-tested against the
same result shapes the real agent returns.

## Critical Implementation Details

- **Secret redaction is load-bearing.** AGENTS.md §d (key never echoed) and §e
  checklist item 5 (no secrets leaked) are hard constraints. The env dump uses a
  pattern denylist `/TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL/i` — matches show
  `<redacted,set>`/`<redacted,unset>`, never the value. The per-turn content
  preview truncates to ~300 chars and must not log tool results containing file
  contents beyond that cap (the diff/context already flow through the model; the
  trace previews only the model's own messages, truncated).
- **Head branch name in CI is detached.** `actions/checkout` leaves HEAD
  detached, so `repo.active_branch` raises `TypeError`. The SHA breadcrumb must
  fall back: `GITHUB_HEAD_REF` → parse `GITHUB_REF` (`refs/pull/28/merge` →
  `pull/28/merge`) → `"detached HEAD"`. Never raise.
- **Retry ordering.** The new empty-emit check runs in the SAME `_invoke_with_
  emit_retry` loop and shares the `max_retries=2` budget with the existing
  parse-failure retry. It triggers only on a *successful* ainvoke whose parsed
  result is empty (both lists) AND whose message history has zero tool-call
  turns — the precise evidenced signature. The nudge message is appended and the
  agent is re-invoked (the agent already returned; appending a HumanMessage +
  re-ainvoking is the same mechanism the parse-failure path already uses).

## Phase 1: DEBUG Observability (env dump, git SHAs, inbound/outbound traces)

### Overview

Make the next CI run fully diagnosable: a redacted runtime-env dump, a head/base
git SHA + branch breadcrumb (fixing the misleading `base_ref=None`), the
assembled inbound prompt char count, and an outbound per-turn message trace with
the final `structured_response` preview.

### Changes Required:

#### 1. Redacted env-var dump helper

**File**: `src/reviewer_target_o_meter/_util.py`

**Intent**: Add a reusable helper that renders the process environment with
secret-named vars redacted by pattern, so the CLI can dump it once at startup for
diagnosis without ever echoing a token.

**Contract**: A function `redacted_env() -> dict[str, str]` (or
`dump_env(log) -> None`) that walks `os.environ` and returns/redacts:
- Names matching `re.compile(r"TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL", re.I)` →
  value replaced by `"<redacted,set>"` (or `"<redacted,unset>"` semantics handled
  by presence). Non-matching names keep their value. Returns a stable-sorted
  dict so the dump is diffable across runs.

#### 2. Env dump + corrected base-ref breadcrumb at startup

**File**: `src/reviewer_target_o_meter/cli.py`

**Intent**: After `configure_logging`, log the redacted env at DEBUG so every
CI run shows exactly which inputs the tool saw (clearing up "is X set?"), and
stop the `review start` line from misleadingly reporting `base_ref=None`.

**Contract**: Call the new env-dump helper at DEBUG inside `review()` after
`configure_logging(config.log_level)`. Rename the `base_ref=` field in the
`review start` INFO line to `base_ref_override=` (it is the `BASE_REF` override,
often None) — the *resolved* base is already logged by `diff.py`'s
`diff computed — base=%s` line, so the rename removes the confusion without
duplicating the resolved value at the CLI layer.

#### 3. Head/base git SHA + branch breadcrumb

**File**: `src/reviewer_target_o_meter/diff.py`

**Intent**: Surface the exact commits the review is diffing between (head SHA +
branch, base ref + SHA) so a CI run is anchored to precise commits, not just a
branch name.

**Contract**: Inside `compute_diff`, after `base = _resolve_base(...)` succeeds
(and before/alongside the existing `diff computed — base=%s` INFO log), emit one
INFO breadcrumb with: `head_sha` (`repo.head.commit.hexsha`), `head_branch`
(`repo.active_branch.name` wrapped in try/except → fall back to
`GITHUB_HEAD_REF` env → parse `GITHUB_REF` → `"detached HEAD"`), `base_ref`
(the resolved `base`), `base_sha` (`repo.commit(base).hexsha`). Best-effort: wrap
in try/except and degrade to logging `<unknown>` for any field — a diagnosis
probe must never break the diff.

#### 4. Inbound prompt char count

**File**: `src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Log the size of what we send the model (system prompt + assembled
HumanMessage) so a 0-finding run can be correlated with prompt size / truncation.

**Contract**: In `checks()`, after assembling `messages` and before
`_invoke_with_emit_retry`, emit a DEBUG line: `inbound prompt — system_chars=%d
human_chars=%d total_chars=%d` using `len(_SYSTEM_PROMPT)` and the joined
`parts` length. DEBUG-gated via `_log.isEnabledFor(logging.DEBUG)`.

#### 5. Outbound per-turn message trace + final structured_response preview

**File**: `src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Reveal what the model actually did — how many turns, whether it
called tools, and what the final (possibly empty) emit looked like — which is the
single biggest unknown in the current CI log.

**Contract**: Add `_log_message_trace(result: Any) -> None` (best-effort,
never raises) called at DEBUG after a successful invoke (alongside `_log_usage`).
It walks `result["messages"]` and for each `AIMessage` logs: turn index, a
truncated (~300-char) content preview, `tool_calls` names if any, and
`usage_metadata` tokens if present. Then logs a truncated (~500-char) preview of
`result["structured_response"]` (the parsed emit) when present. Reuse the
tolerant extraction shape `_extract_findings` already handles
(`structured_response`/`messages`). DEBUG-gated.

### Success Criteria:

#### Automated Verification:

- Lint + types pass: `make check` (ruff + mypy src)
- Unit tests pass: `make test` (incl. new asserts in `test_logging.py`/
  `test_nodes.py` for the redaction helper and the trace probe's best-effort
  contract)

#### Manual Verification:

- `make run DIR=../../target-o-meter/` with `LOG_LEVEL=DEBUG` locally shows the
  redacted env dump (tokens `<redacted,set>`, non-secrets visible), head + base
  SHA/branch breadcrumb, inbound prompt char count, and the per-turn trace.
- The `review start` line reads `base_ref_override=…` (no misleading
  `base_ref=None`), and the resolved base appears in the `diff computed` line.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Phase 2: Close the Valid-But-Empty-Emit Retry Gap

### Overview

Extend `_invoke_with_emit_retry` to also retry (with the same emit-nudge) when
the agent returns a *successful but empty* report (0 findings AND 0
optional_findings) and made **zero tool-call turns** — the evidenced
`output=25, finish_reason=stop, no investigation` signature. This is the
behavior fix the CI log implicates; observability (Phase 1) reveals whether it
fires on the diagnostic run.

### Changes Required:

#### 1. Detect the suspicious empty emit

**File**: `src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Add a predicate that identifies the recoverable flake — a parsed
report with nothing in either list AND no tool investigation — distinct from a
diff the model genuinely examined and found clean.

**Contract**: `_is_suspicious_empty_emit(result: Any) -> bool`:
- Use `_extract_findings(result)` (existing) to get `findings` +
  `optional_findings`; True only if BOTH lists are empty.
- Count tool-call turns: `_count_tool_call_turns(result)` walks
  `result["messages"]` and counts `AIMessage`s with a non-empty `tool_calls`
  list; True only if that count is `0`.
- Returns True iff (both lists empty) AND (zero tool-call turns). Never raises
  (mirror `_extract_usage`'s defensive shape handling).

#### 2. Retry the suspicious empty emit

**File**: `src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Wire the new predicate into the existing retry loop so a
valid-but-empty emit gets the same emit-nudge recovery as a parse failure.

**Contract**: In `_invoke_with_emit_retry`, after a successful
`return await agent.ainvoke(...)`, instead inspect the result: if
`_is_suspicious_empty_emit(result)` and attempts remain, log a WARNING
(`structured emit came back valid-but-empty with no tool investigation
(attempt …); retrying with an emit nudge`) and re-invoke with the nudge appended
(reuse the exact nudge `HumanMessage` the parse-failure path uses). On the final
attempt or when not suspicious, return the result as-is. The two retry triggers
(parse-failure exception; valid-but-empty) share the `max_retries` budget. Keep
`_is_empty_emit_parse_failure` and its exception-path retry unchanged.

#### 3. Unit tests

**File**: `tests/test_nodes.py`

**Intent**: Lock the new predicate's contract the way `TestExtractUsageBestEffort`
locks `_extract_usage` — best-effort, never raises, precise about the empty +
zero-tool-call condition.

**Contract**: Add cases for `_is_suspicious_empty_emit`: empty findings +
optional_findings + zero tool-call turns → True; same but one tool-call turn →
False (genuinely investigated); non-empty findings → False; non-empty
optional_findings → False; missing/malformed `messages`/`structured_response` →
False (never raises). Optionally a `_count_tool_call_turns` case counting
`AIMessage(tool_calls=[…])`.

### Success Criteria:

#### Automated Verification:

- Lint + types pass: `make check`
- Unit tests pass: `make test` (new `test_nodes.py` cases green)

#### Manual Verification:

- On the triggered PR #28 run (Phase 3), if the model emits empty again, the log
  shows the `valid-but-empty … retrying` WARNING and the retry produces
  findings (or, if it stays empty after retries, the per-turn trace explains why).

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Phase 3: Consumer Workflow Pin + Commit + Trigger PR #28

### Overview

Land Phases 1–2 on the tool's `debug-ci-logging` branch, point the consumer's
`review.yml` at it, add a `MODEL` passthrough, and commit on the feature branch
so the push triggers PR #28's review with the new DEBUG breadcrumbs.

### Changes Required:

#### 1. Tool branch + push

**File**: tool repo (`reviewer-target-o-meter`) git state

**Intent**: Get the instrumented code into a ref the consumer can install.

**Contract**: Create `debug-ci-logging` off the tool repo's current `master`,
commit Phases 1–2 there, push to `origin/debug-ci-logging`.

#### 2. Pin workflow install + add MODEL passthrough

**File**: `target-o-meter/.github/workflows/review.yml`

**Intent**: Make the consumer install the instrumented tool branch for this
diagnostic run and allow a one-off model override without code changes.

**Contract**: Change the `uv tool install` line to pin the branch:
`git+https://github.com/krkruk/reviewer-target-o-meter@debug-ci-logging#subdirectory=reviewer-target-o-meter`.
Add `MODEL: ${{ vars.MODEL }}` to the `Run reviewer-target-o-meter` step's env
(unset → empty → `Config.from_env` falls back to `DEFAULT_MODEL`, so behavior is
unchanged unless a repo variable is set). Keep `LOG_LEVEL: DEBUG` and
`continue-on-error: true`.

#### 3. Commit on feature branch + push to trigger

**File**: consumer repo (`target-o-meter`) git state

**Intent**: Trip PR #28's `on: pull_request` review workflow with the
instrumented tool.

**Contract**: Commit the `review.yml` change on the consumer's current branch
`feature/add-user-score-dashboard-implementation`, push to origin. The push
triggers the `review` workflow on PR #28. Capture the run URL (`gh run list` /
`gh run watch`) for the summary.

### Success Criteria:

#### Automated Verification:

- The pushed workflow YAML is valid (no syntax errors; the `review` run starts).

#### Manual Verification:

- The triggered PR #28 review run's step log shows the new DEBUG breadcrumbs
  (redacted env dump, head/base SHA, inbound char count, per-turn trace) and,
  if the model empties again, the `valid-but-empty … retrying` WARNING.
- The run URL is captured and reported.

**Implementation Note**: This phase executes (commit + push + trigger) as the
final action of the session per the agreed plan.

---

## Phase 4: Post-Diagnosis Stabilization (follow-up, not executed this session)

### Overview

After reading the triggered run, land the validated tool changes on master and
return the consumer workflow to a clean state. Conditional on the run's output.

### Changes Required:

#### 1. Merge tool branch to master

**File**: tool repo git state

**Intent**: Promote the instrumented + retry-fixed code to the ref the consumer
installs by default.

**Contract**: Merge `debug-ci-logging` into the tool repo's `master` (fast-forward
or PR per the user's preference) once Phase 1–2 are validated by the diagnostic
run.

#### 2. Revert the workflow pin

**File**: `target-o-meter/.github/workflows/review.yml`

**Intent**: Return the consumer to installing the tool from master.

**Contract**: Change the install line back to
`git+https://github.com/krkruk/reviewer-target-o-meter#subdirectory=reviewer-target-o-meter`
(drop the `@debug-ci-logging` pin). Decide whether to keep the `MODEL` passthrough
(recommended — harmless, useful for future diagnosis).

#### 3. Permanent model/retry posture

Decide from the run whether the default `deepseek` slug stays or a paid/reliable
slug is warranted, and whether the empty-emit retry thresholds need tuning. Out
of scope to execute now; recorded here as the post-diagnosis decision.

### Success Criteria:

#### Automated Verification:

- `make check` + `make test` still green on tool `master` after merge.

#### Manual Verification:

- A subsequent PR on the consumer installs the tool from master and runs with
  the new logging/retry in place; the `@debug-ci-logging` pin is gone.

---

## Testing Strategy

### Unit Tests:

- `test_logging.py`: the `redacted_env`/dump helper redacts secret-named vars
  by pattern and leaves non-secrets intact.
- `test_nodes.py`: `_is_suspicious_empty_emit` (empty both lists + zero
  tool-call turns → True; one tool-call turn → False; non-empty → False;
  malformed shapes → False, never raises) and `_count_tool_call_turns`; the
  `_log_message_trace`/`_log_usage` best-effort contract (never raises on
  missing `messages`/metadata).

### Integration Tests:

- The triggered PR #28 CI run is the integration signal — the new breadcrumbs
  appear and the empty-emit retry (if triggered) recovers findings.

### Manual Testing Steps:

1. `make run DIR=../../target-o-meter/` with `LOG_LEVEL=DEBUG` locally — confirm
   env dump, SHA breadcrumb, inbound char count, per-turn trace all render and
   tokens are `<redacted,set>`.
2. Confirm `make check` + `make test` are green on `debug-ci-logging`.
3. Push the consumer `review.yml` change and open the triggered PR #28 run —
   verify the DEBUG breadcrumbs are present in the step log.

## Performance Considerations

The new probes are DEBUG-gated and best-effort; the only always-on addition is
the head/base SHA INFO breadcrumb (two `git` object reads, negligible). The
empty-emit retry adds at most `max_retries` extra model invocations — only on
the already-broken 0-finding path, so it costs nothing on healthy runs and is
the cheapest way to recover the flake.

## Migration Notes

None — pure additions plus one workflow pin (reverted in Phase 4). No schema,
state, or interface changes.

## References

- Failure mode + retry rule: `context/foundation/lessons.md`
- Existing retry wrapper + usage probe: `src/reviewer_target_o_meter/agent/nodes.py:382`, `:447`, `:531`
- DEBUG-probe + logging channel conventions: `src/reviewer_target_o_meter/cli.py:138`, `src/reviewer_target_o_meter/_util.py:31`
- Diff/base resolution (holds the `Repo`): `src/reviewer_target_o_meter/diff.py:46`, `:86`
- Consumer workflow (the trigger target): `target-o-meter/.github/workflows/review.yml`
- Prior diagnosis: `context/changes/fine-tune-context/` (change.md, diagnosis.md)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: DEBUG Observability (env dump, git SHAs, inbound/outbound traces)

#### Automated

- [x] 1.1 Lint + types pass (`make check`) — ec61259
- [x] 1.2 Unit tests pass (`make test`, incl. redaction helper + trace probe asserts) — ec61259

#### Manual

- [x] 1.3 Local `make run DIR=../../target-o-meter/` with `LOG_LEVEL=DEBUG` shows env dump, SHA breadcrumb, inbound char count, per-turn trace — ec61259 (confirmed on CI run 31002167288)
- [x] 1.4 `review start` line reads `base_ref_override=…` (no misleading `base_ref=None`) — ec61259 (confirmed: `base_ref_override=None` in run 31002167288)

### Phase 2: Close the Valid-But-Empty-Emit Retry Gap

#### Automated

- [x] 2.1 Lint + types pass (`make check`) — c12c0fd
- [x] 2.2 Unit tests pass (`make test`, incl. `_is_suspicious_empty_emit` + `_count_tool_call_turns` cases) — c12c0fd

#### Manual

- [x] 2.3 Triggered PR #28 run: empty-emit retry WARNING fires and recovers findings (or trace explains the persistent empty) — c12c0fd (confirmed on run 31002167288: `valid-but-empty … retrying` → output=1235, 4 findings, exit 1)

### Phase 3: Consumer Workflow Pin + Commit + Trigger PR #28

#### Automated

- [x] 3.1 Pushed `review.yml` YAML is valid; the `review` run starts — consumer 391361e (run 31002167288)

#### Manual

- [x] 3.2 PR #28 run step log shows the new DEBUG breadcrumbs — consumer 391361e (env dump, git refs, inbound prompt, per-turn trace all present)
- [x] 3.3 Run URL captured and reported — consumer 391361e (https://github.com/krkruk/target-o-meter/actions/runs/31002167288)

### Phase 4: Post-Diagnosis Stabilization (follow-up)

#### Manual

- [x] 4.1 Merge `debug-ci-logging` to tool `master` after validation — merged via reviewer-target-o-meter#9 (master c1bc0ce)
- [x] 4.2 Revert `review.yml` install pin to master (keep `MODEL` passthrough) — consumer 31d9103 (LOG_LEVEL=DEBUG + MODEL retained; verified on master run 31002996084)
- [x] 4.3 Decide permanent model/retry posture from the run — retry stays as-is; the LLM choosing not to call tools is accepted (no prompt-tuning this cycle)
