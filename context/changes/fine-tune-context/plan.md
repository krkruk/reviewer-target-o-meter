# Make the Reviewer Finish on Large PRs — Implementation Plan

## Overview

The reviewer emits **0 findings** on large refactoring PRs because the `checks`
node exceeds its 120s `run_timeout`, degrades to an empty report (advisory exit
0), and posts nothing actionable. The live symptom: `krkruk/target-o-meter#28`
(a major refactoring PR) timed out and posted 0 findings, even though the
operator runs a paid 1M-context model.

Rather than blindly raising knobs, this plan is **diagnose-first**: heavily
instrument the code, measure against PR #28, identify the real bottleneck, apply
a targeted fix, confirm findings are produced, then **strip the
instrumentation**. The knob changes are the *starting hypothesis to test*, not
the prescribed answer.

## Current State Analysis

(Lifted from `frame.md` Hypothesis Investigation + `research.md` Code References
— these are settled, not re-investigated here.)

### The symptom and its mechanism

- `config.py:47` — `run_timeout: ClassVar[int] = 120` (ClassVar, not env-driven).
- `graph.py:42` — `TimeoutPolicy(run_timeout=config.run_timeout)` on `checks`.
- `graph.py:78-92` — `NodeTimeoutError` caught in `arun_review` (OUTSIDE the
  checks node body) → empty report + advisory exit 0. **This is exactly the path
  PR #28 hit** (`WARNING: graph degraded — node 'checks' exceeded run timeout`).

### Why it's diff-driven, not context-driven (the frame's core finding)

- Live log: `diff=105568 chars` vs `context=8040 chars` (ratio ~13×).
- `nodes.py:240-249` — the `HumanMessage` joins diff → context → plan, sent once
  to `agent.ainvoke`.
- Each of up to 12 agent iterations re-sends the full ~105k-char diff (no prompt
  caching configured anywhere in the repo — grep for `cach`/`prefix`/
  `cache_control` returns 0 matches).
- Context is hard-capped at 8000 (`context_loader.py:32`) and ran at 8040 — a
  rounding error vs the diff. Trimming context dirs cannot dent the timeout.

### The visibility gap (why diagnosis needs new instrumentation)

- `nodes.py:272` — on success, `_log_usage(result)` emits input/output/total
  tokens + finish_reason. This is the only model-call visibility today.
- `nodes.py:78` (graph.py) — on timeout, `NodeTimeoutError` is raised OUTSIDE
  the checks node body, so the partial result **never reaches `_log_usage`**.
  The timeout path emits only the WARNING line at `graph.py:84-88`. There is no
  visibility into what the model was doing, how many iterations it had
  completed, or what token usage looked like, when the timeout fired.

### Knobs and their current/working-tree values

| Knob | Location | Committed | Working tree | Plan's starting hypothesis |
|---|---|---|---|---|
| `run_timeout` | `config.py:47` | 120 | 120 | **300** |
| `max_iterations` | `config.py:46` | 12 | 12 | **8** |
| `MAX_DIFF_CHARS` | `diff.py:36` | 45000 | 100000 | **200000** |
| `_MAX_TOKENS` | `provider.py:28` | 60000 | 128000 | **128000** (already WT) |
| `MAX_CONTEXT_CHARS` | `context_loader.py:32` | 8000 | 8000 | 8000 (unchanged — see frame) |

### Tests that will move

- `tests/test_config.py:37` — `assert Config.run_timeout == 120` (pins literal).
- `tests/test_cli.py:242-265` — `test_cli_log_lines_are_metadata_only` (the
  metadata-only log invariant). Phase 1's DEBUG raw-dump will require a
  test-scoped gate; Phase 4 re-asserts the invariant after instrumentation
  removal.
- `tests/test_diff.py:184-192` — derive from `MAX_DIFF_CHARS` constant
  (value-agnostic; safe, but re-run after the bump).
- No test pins `max_iterations`, `_MAX_TOKENS`, or `_log_usage`.

## Desired End State

When this plan is complete:

1. Running the reviewer against `krkruk/target-o-meter#28` (or any large
   refactoring PR) **produces real findings** (not 0) within the wall-clock
   budget — because the actual bottleneck was identified and fixed, not papered
   over with a timeout raise.
2. The final knob values are whatever the measurement justified, recorded in
   `diagnosis.md` with the evidence.
3. The temporary DEBUG instrumentation is **gone** — the metadata-only log
   invariant (`test_cli.py:242-265`) is green again.
4. `make check` + `make test` are green; a live smoke run confirms findings.

### Key Discoveries (from frame + research — authoritative)

- The timeout is **diff-driven** (live log ratio 13×; no prompt caching). Frame
  Confidence: HIGH.
- The timeout path has **no visibility** — `_log_usage` is never reached on
  `NodeTimeoutError`. This is the real blocker to diagnosis.
- `max_iterations=12` re-sends the full diff every turn with up to +20k/turn
  tool output (`tools/text_search.py:16`) — a second-order amplifier.
- Problem B (blind `load_context`) is a **relevance** problem, not a latency
  one — deferred (see What We're NOT Doing).

## What We're NOT Doing

- **Problem B — change-aware `load_context`.** The frame proved it's a relevance
  problem (reads every active change's docs unconditionally, `context_loader.py:66`;
  blind to the current PR, `cli.py:65`), NOT the timeout driver. Trimming it
  wouldn't have saved PR #28. Deferred to a follow-up change — open with
  `/10x-new context-loader-change-aware` after this lands.
- **"Modified-python-files tier" in the context loader.** The literal request #3
  text was the opposite of the operator's real intent (frame pre-dispatch
  answer: "dismiss/trim", not "add"). It would also re-open the closed
  "no source preload" decision (`change-input-pipeline/plan.md:86-88`). Dropped.
- **Prompt caching.** No caching is configured, and adding it is a provider-side
  concern outside this repo's control. Not in scope; noted as a future lever.
- **Changing the model.** The operator runs a paid 1M model; the model is not
  the constraint being fixed.
- **Permanent DEBUG raw-dump logging.** The instrumentation is temporary by
  design (Phase 1 adds, Phase 4 removes). It is not a durable feature.

## Implementation Approach

Diagnose-first, four phases. The knob changes (Phase 1) are the *starting
hypothesis*; Phases 2–3 measure and fix; Phase 4 cleans up. The instrumentation
is a means to diagnosis, not an end.

**Phases 2–3 require a live OpenRouter run** against `krkruk/target-o-meter#28`
(needs `OPENROUTER_API_KEY` + `GITHUB_TOKEN`). They are manual-verification
phases and cannot be validated by `make test` alone. `make check`/`make test`
green is necessary but not sufficient for those phases.

## Critical Implementation Details

- **Debug logging gate.** The Phase-1 instrumentation must be DEBUG-gated via
  the existing `LOG_LEVEL` knob (`_util.py:31-57`, default INFO), so it is off
  in normal/CI runs and only enabled for the diagnosis run. Set
  `LOG_LEVEL=DEBUG` in the diagnosis environment. The full raw dump lives only
  during the diagnosis window.
- **Timeout-path instrumentation placement.** `NodeTimeoutError` is raised in
  `graph.py:78` *outside* the checks node body, so the partial agent state is
  not reachable from the node's own return. The instrumentation for the timeout
  path must hook into `arun_review`'s except block (`graph.py:78-92`) — capture
  whatever is reachable from the exception (the `node` attribute, elapsed time
  from the exception) and, if the agent left any partial state, log it there.
- **`max_iterations` is a ClassVar.** `config.py:46` — changing it is a code
  edit, not env-driven. The `ModelCallLimitMiddleware(run_limit=...)` at
  `nodes.py:233` reads it.
- **`MAX_DIFF_CHARS` boundary overshoot.** `_cap` (`diff.py:125-133`) cuts at the
  next `diff --git` boundary AFTER the budget, so the actual capped size can
  exceed 200000 by up to one file's worth. This is documented behavior, not a
  bug — leave it.
- **`tests/test_cli.py:242-265` interaction.** During Phase 1, this test will
  need to either (a) run at INFO (default) so the DEBUG dump doesn't fire and
  the invariant holds, or (b) be marked xfail/skipped pending Phase 4. Option
  (a) is cleaner — the DEBUG dump only fires at DEBUG level, and the test runs
  at default INFO, so the invariant stays green throughout. **Prefer (a).**

## Phase 1: Instrument + set baseline knobs

### Overview

Add the temporary DEBUG-gated raw-dump logging (success path AND timeout path —
the real visibility gap), and apply the starting-hypothesis knob values. After
this phase, `make check`/`make test` is green and the code is ready for the
diagnosis run. No diagnosis yet — that's Phase 2.

### Changes Required:

#### 1.1 Timeout-path instrumentation (the visibility gap)

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/graph.py`

**Intent**: Add DEBUG logging inside the `NodeTimeoutError` except block
(`graph.py:78-92`) so the timeout path leaves diagnostic breadcrumbs — currently
it emits only the WARNING line at `:84-88`. Capture whatever is reachable from
the exception: the node name (`getattr(exc, "node", ...)`), the elapsed time and
configured run_timeout (from the exception attributes), and any partial agent
state if present. This is temporary instrumentation; Phase 4 removes it.

**Contract**: Uses `_log.debug(...)` (the package logger, `_util.get_logger`),
so it only emits when `LOG_LEVEL=DEBUG`. Gated by level, not by a flag. Never
touches `exc` headers/bodies beyond structural attributes already exposed.

#### 1.2 Success-path raw-dump instrumentation

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Add a DEBUG-gated full raw dump of the `agent.ainvoke` result in the
`checks` node, immediately after the successful call (`nodes.py:257`) and before
`_log_usage`. This is the operator's explicit request: "log into stderr the
object you receive from the LLM so we can debug the issue." Temporary; Phase 4
removes it.

**Contract**: `_log.debug("checks raw result: %s", _redact_for_debug(result))`
where `_redact_for_debug` is a new best-effort helper that renders the result
for debug inspection. Per the operator's decision (full raw dump at DEBUG), this
includes message content for the diagnosis window — the leakage concern
(`prd.md:44`) is bounded by (a) DEBUG-gating (off in CI at default INFO) and (b)
the explicit ephemerality (removed in Phase 4). A docstring on the helper states
both bounds. Mark the helper and call site with a `# TEMPORARY — Phase 4 removes
this` comment so the cleanup is mechanical.

#### 1.3 Knob: `run_timeout` 120 → 300

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/config.py:47`

**Intent**: Raise the starting hypothesis. This is the value to *test* in
Phase 2; Phase 4 lands the final value the measurement justifies.

**Contract**: `run_timeout: ClassVar[int] = 300`. Update the inline comment to
note "starting hypothesis; see diagnosis.md for the measured final value".

#### 1.4 Knob: `max_iterations` 12 → 8

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/config.py:46`

**Intent**: Lower the iteration cap as the second half of the starting
hypothesis (Option 3). Bounds the worst-case wall-clock by reducing the number
of full-diff re-sends. Testable in Phase 2.

**Contract**: `max_iterations: ClassVar[int] = 8`. Note in comment this is a
hypothesis to validate — fewer iterations may reduce finding depth.

#### 1.5 Knob: `MAX_DIFF_CHARS` 100000 → 200000

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/diff.py:36`

**Intent**: Fit PR #28's 166670 raw chars untruncated (200000 > 166670). The
boundary-cap overshoot (`_cap`, `diff.py:125-133`) stays as-is.

**Contract**: `MAX_DIFF_CHARS = 200000`. Update the comment to cite the
proportional-to-1M-window rationale and the PR #28 raw size.

#### 1.6 Update affected tests

**File**: `reviewer-target-o-meter/tests/test_config.py`

**Intent**: The literal-pin test at `:37` must move to the new value.

**Contract**: `assert Config.run_timeout == 300` (and if `max_iterations` is
asserted nearby, update it too — check `:35-37`). The DEBUG-gated
instrumentation (1.1, 1.2) must NOT break `tests/test_cli.py:242-265` because
that test runs at default INFO; verify by running it.

**File**: `reviewer-target-o-meter/tests/test_diff.py`

**Intent**: Re-confirm the truncation test (`:184-192`) still passes with the
new constant — it derives size from `MAX_DIFF_CHARS`, so it should be
value-agnostic, but re-run to confirm.

### Success Criteria:

#### Automated Verification:

- `make check` (ruff + mypy) is green
- `make test` (unit tests, excluding smoke) is green — including
  `test_config.py` (new timeout value) and `test_cli.py:242-265` (metadata-only
  invariant holds at default INFO)
- `make run DIR=tests/fixtures/sample-repo` runs end-to-end without crashing
  (does NOT require OPENROUTER_API_KEY to exercise the non-LLM path; if it does
  require the key, skip this and rely on the smoke in Phase 2)

#### Manual Verification:

- `LOG_LEVEL=DEBUG make run DIR=tests/fixtures/sample-repo` (with
  OPENROUTER_API_KEY) shows the new DEBUG raw-dump lines on stderr
- At default LOG_LEVEL (INFO), the DEBUG lines are absent — the metadata-only
  invariant holds

**Implementation Note**: After Phase 1's automated verification passes, pause
for the human to confirm the manual logging check before proceeding to Phase 2
(the live diagnosis run).

---

## Phase 2: Measure against PR #28 + diagnose

### Overview

Run the operator's exact command against `krkruk/target-o-meter#28` with
`LOG_LEVEL=DEBUG`, read the instrumentation output, and identify the real
bottleneck. This phase produces a **diagnosis document**, not code. The
diagnosis drives Phase 3's fix.

### Changes Required:

#### 2.1 Run the diagnosis

**Command** (operator-only; intentionally not committed to any artifact):
```
PR_NUMBER=28 GITHUB_TOKEN=$(gh auth token) GITHUB_REPOSITORY=krkruk/target-o-meter \
  LOG_LEVEL=DEBUG make run DIR=../../target-o-meter/
```

Run from `reviewer-target-o-meter/` (where `pyproject.toml` lives). The
`../../target-o-meter/` path is the operator's local checkout of the reviewed
repo; adjust if it lives elsewhere. Repeat 2–3 times — LLM runs are noisy and a
single timeout tells you less than the pattern across runs.

#### 2.2 Read the DEBUG output and form the diagnosis

Read the DEBUG logs from the run(s) and answer these questions (they map to the
frame's dimension map):

- **Iteration count:** how many of the 8 allowed iterations did the agent
  actually use? Did it hit the `max_iterations` cap (the
  `ModelCallLimitMiddleware` end-behavior) or the timeout first?
- **Per-iteration token usage:** what was `input_tokens` / `output_tokens` /
  `total_tokens` on each model call? Was `output_tokens` approaching the
  `_MAX_TOKENS=128000` ceiling (the `_log_usage` WARNING condition)? Was
  `finish_reason == "length"` (truncated)?
- **Tool-call pattern:** how many `text_search` / `structural_search` calls, and
  how much output did each add (up to 20k/turn)? Was the message history
  ballooning?
- **Diff re-send cost:** the full ~200k-char diff is re-sent every iteration —
  did input_tokens grow roughly linearly with iterations × diff-size + tool
  output?
- **Where did time go:** was the wall-clock dominated by a few long reasoning
  calls (high output_tokens, long per-call latency) or by many calls (high
  iteration count)? Did the timeout fire mid-call (a single long reasoning step)
  or between calls (cumulative)?

#### 2.3 Write the diagnosis

**File**: `context/changes/fine-tune-context/diagnosis.md` (new)

**Intent**: Record the measured bottleneck with evidence (token counts,
iteration counts, finish_reason, timing). This is the artifact that justifies
Phase 3's fix and Phase 4's final knob values. Without it, the knob changes are
unjustified tweaks.

**Contract**: A short doc (target ~50–100 lines) with: (a) the run(s) summary,
(b) the dimension-map question answers above with the observed numbers, (c) the
verdict — which dimension dominated, (d) the prescribed fix (knob tune?
iteration cap? prompt change? code fix?), (e) the final knob values the fix
implies. This doc is the input to Phase 3.

### Success Criteria:

#### Automated Verification:

- (none — this phase is pure measurement)

#### Manual Verification:

- The diagnosis command ran to completion (or to a documented timeout) at least
  twice with DEBUG output captured
- `diagnosis.md` exists and answers all five dimension-map questions with
  observed numbers
- The diagnosis names a single leading bottleneck with evidence, and prescribes
  a concrete Phase-3 fix

**Implementation Note**: Pause here for the human to review the diagnosis before
Phase 3 applies the fix. The diagnosis is the load-bearing artifact of this
plan — if it's inconclusive, re-run or add instrumentation rather than guessing.

---

## Phase 3: Apply the targeted fix + confirm findings

### Overview

Implement the fix `diagnosis.md` prescribes, then re-run PR #28 and confirm the
reviewer now produces **real findings** (not 0). Iterate until the symptom is
gone. The fix is diagnosis-driven — it could be a knob tune, an iteration-cap
change, a prompt change, or a code fix. Do not pre-decide it here.

### Changes Required:

#### 3.1 Apply the diagnosis-prescribed fix

**File**: (whichever `diagnosis.md` points at — likely among `config.py`,
`nodes.py`, `provider.py`, or the prompt in `nodes.py`)

**Intent**: Implement exactly what the diagnosis prescribes, nothing more. If
the diagnosis says "the bottleneck is reasoning-token exhaustion; raise
`_MAX_TOKENS` further or cap reasoning effort," do that. If it says "the
bottleneck is iteration count re-sending the diff; lower `max_iterations`
further or add tool-output trimming," do that. If it says "a single reasoning
call ran 280s; the timeout is still too low at 300s," raise it. The diagnosis
owns this decision.

**Contract**: The fix must be consistent with the fail-safe conventions
(`prd.md:44` no-leak; AGENTS.md §d degrade-never-crash). If it touches the
prompt (`_SYSTEM_PROMPT`, `nodes.py:48-187`), preserve the three
product-specific adaptations (plan-tolerance, no-command-execution,
diff-scoping — AGENTS.md §h).

#### 3.2 Re-run PR #28 and confirm findings

**Command**: same as Phase 2.1, with `LOG_LEVEL=DEBUG` initially (to confirm
the fix's effect on the instrumentation), then at default INFO (to confirm the
production path).

**Intent**: The success condition is **not** "no timeout" — it's "the reviewer
produces real findings on PR #28." A run that finishes in 290s with 0 findings
is still a failure. Confirm the findings are substantive (real anchors, real
severities — apply the AGENTS.md §e review-output checklist). If the PR
genuinely has no findings worth flagging, document that in `diagnosis.md` and
pick a different large PR to validate against.

#### 3.3 Iterate if needed

If the first fix doesn't produce findings, loop: re-read the DEBUG output,
refine the fix, re-run. Cap the iteration at ~3 fix-and-rerun cycles — if it's
still not producing findings, the diagnosis was wrong and Phase 2 needs a
redo (add more instrumentation, re-measure).

### Success Criteria:

#### Automated Verification:

- `make check` is green after the fix
- `make test` is green (update any tests the fix touches)

#### Manual Verification:

- PR #28 (or a substitute large PR) run produces **>0 real findings** with valid
  anchors and severities (AGENTS.md §e checklist)
- The run completes within the wall-clock budget (the raised timeout, or lower)
- Run at default INFO (no DEBUG) confirms the production path works without
  instrumentation noise

**Implementation Note**: Pause here for the human to confirm the findings are
real and substantive before Phase 4 strips the instrumentation. Do NOT remove
the DEBUG logging until at least one clean production-path run succeeds.

---

## Phase 4: Remove instrumentation + finalize

### Overview

Strip the temporary DEBUG raw-dump logging (1.1, 1.2), land the final knob
values the measurement justified (which may differ from the Phase-1
hypothesis), update docs, and confirm the metadata-only log invariant is green
again.

### Changes Required:

#### 4.1 Remove the temporary instrumentation

**Files**: `reviewer-target-o-meter/src/reviewer_target_o_meter/graph.py`,
`reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Remove the `# TEMPORARY — Phase 4 removes this` blocks added in 1.1
and 1.2 (the DEBUG raw-dump helper and its call sites, the timeout-path DEBUG
probe). The durable logging stays: `_log_usage` on success (`nodes.py:272`), the
existing `_extract_response_shape` failure probe (`nodes.py:309-343`), and the
existing WARNING at `graph.py:84-88`.

**Contract**: After removal, `grep -rn "TEMPORARY" src/` returns nothing. The
metadata-only log invariant (`test_cli.py:242-265`) must pass cleanly without
any test-scoped gating.

#### 4.2 Land the final knob values

**Files**: `config.py`, `diff.py`, (and `provider.py` if `_MAX_TOKENS` moved)

**Intent**: Set the knobs to whatever `diagnosis.md` justified. If the Phase-1
hypothesis (300/8/200000/128000) was correct, they stay; if the measurement
showed a different value is better, land that. Update the inline comments to
cite `diagnosis.md` as the evidence source (not "starting hypothesis").

**Contract**: Final values recorded in `diagnosis.md`. Each knob's comment names
the measured rationale.

#### 4.3 Update docs

**File**: `README.md`

**Intent**: The README at `:114-117` cites the old knob values
(`recursion_limit=40`, `run_timeout=120s`, `MAX_DIFF_CHARS=45000`,
`_MAX_TOKENS=60000`). Update to the final landed values.

**Contract**: README values match the code exactly.

#### 4.4 Final test sweep

**Intent**: Confirm the whole change is green and the instrumentation is gone.

**Contract**: `make check` + `make test` green; `grep -rn "TEMPORARY" src/
tests/` empty; `test_cli.py:242-265` passes without gating.

### Success Criteria:

#### Automated Verification:

- `make check` is green
- `make test` is green
- `grep -rn "TEMPORARY" src/ tests/` returns nothing
- `tests/test_cli.py:242-265` passes (metadata-only invariant restored)

#### Manual Verification:

- One final run of PR #28 at default INFO confirms real findings, no DEBUG noise,
  clean production path
- README knob values match the code

**Implementation Note**: This is the final phase. After it, the change is ready
for `/10x-impl-review-ci` or merge.

---

## Testing Strategy

### Unit Tests:

- `tests/test_config.py` — update the `run_timeout` (and `max_iterations` if
  pinned) literal assertions to the final values.
- `tests/test_diff.py` — re-confirm value-agnostic truncation tests pass at the
  new `MAX_DIFF_CHARS`.
- `tests/test_cli.py:242-265` — metadata-only log invariant. During Phase 1 it
  stays green because the DEBUG dump is level-gated off at default INFO; after
  Phase 4 it's green because the dump is removed entirely.

### Integration Tests:

- The existing `tests/test_graph.py` timeout-degrade test (`:343-368`) — its
  `120.001`/`120.0` are throwaway constructor args, not the config value, so it
  stays green; update the narrative comment if it mentions "120s".

### Manual Testing Steps (the load-bearing verification):

1. Phase 2: run PR #28 with `LOG_LEVEL=DEBUG`, capture stderr, form diagnosis.
2. Phase 3: run PR #28 after the fix, confirm >0 real findings (AGENTS.md §e
   checklist). Repeat on a substitute large PR if PR #28 genuinely has no
   findings.
3. Phase 4: run PR #28 at default INFO, confirm clean production path.

## Performance Considerations

- The whole point of this change is performance on large PRs. The diagnosis
  (Phase 2) is what tells us whether the bottleneck is input size, iteration
  count, reasoning depth, or tool-call explosion — each has a different fix.
- **No prompt caching** is configured, and adding it is out of scope (provider-
  side). If the diagnosis shows the diff re-send cost dominates, note prompt
  caching as a future lever in `diagnosis.md` but do not implement it here.
- The raised `MAX_DIFF_CHARS=200000` doubles the per-iteration prompt vs the
  working tree's 100000; the raised timeout covers the per-call latency increase.
- Lowering `max_iterations` 12→8 trades finding depth for wall-clock — the
  diagnosis validates whether 8 is enough.

## Migration Notes

None — this is knob tuning + temporary instrumentation. No data migration, no
schema change, no breaking interface change. The `FindingsReport` contract is
untouched.

## References

- Frame brief: `context/changes/fine-tune-context/frame.md` (the two-problem
  split; Problem A is this plan, Problem B deferred)
- Research: `context/changes/fine-tune-context/research.md` (full code refs,
  test surface, prior decisions)
- Prior decisions:
  - `context/foundation/prd.md:44,96-98` (no-leakage guardrail; ~5-min NFR)
  - `context/archive/2026-08-04-graph-bugfixing/plan.md:326-329,369` (timeout is
    the binding latency guard; raised `_MAX_TOKENS` made the model reason past
    120s)
  - `context/archive/2026-08-04-prod-logging-markdown-preview/plan.md:83-87`
    (logging is metadata-only; `LOG_LEVEL` is the verbosity knob — the gate for
    the temporary instrumentation)
- Source: `reviewer-target-o-meter/src/reviewer_target_o_meter/{config,graph,
  diff,provider,context_loader}.py`, `agent/nodes.py`, `_util.py`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Instrument + set baseline knobs

#### Automated

- [x] 1.1 `make check` (ruff + mypy) green after instrumentation + knob changes — 065385b
- [x] 1.2 `make test` green — including `test_config.py` (new timeout) and `test_cli.py:242-265` (invariant at default INFO) — 065385b

#### Manual

- [x] 1.3 `LOG_LEVEL=DEBUG make run DIR=tests/fixtures/sample-repo` shows the new DEBUG raw-dump lines on stderr — 065385b
- [x] 1.4 At default LOG_LEVEL (INFO), the DEBUG lines are absent — metadata-only invariant holds — 065385b

### Phase 2: Measure against PR #28 + diagnose

#### Automated

- [x] 2.1 (none — pure measurement)

#### Manual

- [x] 2.2 PR #28 diagnosis command run ≥2× with DEBUG output captured — 424a307
- [x] 2.3 `diagnosis.md` written — answers all five dimension-map questions with observed numbers, names the bottleneck, prescribes the Phase-3 fix — 424a307

### Phase 3: Apply the targeted fix + confirm findings

#### Automated

- [x] 3.1 `make check` green after the diagnosis-prescribed fix — 424a307
- [x] 3.2 `make test` green (update any tests the fix touches) — 424a307

#### Manual

- [x] 3.3 PR #28 (or substitute large PR) produces >0 real findings with valid anchors/severities (AGENTS.md §e checklist) — 424a307
- [x] 3.4 Run completes within wall-clock budget; default-INFO production path works without instrumentation noise — 424a307

### Phase 4: Remove instrumentation + finalize

#### Automated

- [ ] 4.1 `make check` green
- [ ] 4.2 `make test` green
- [ ] 4.3 `grep -rn "TEMPORARY" src/ tests/` returns nothing
- [ ] 4.4 `tests/test_cli.py:242-265` passes (metadata-only invariant restored)

#### Manual

- [ ] 4.5 Final PR #28 run at default INFO — real findings, no DEBUG noise, clean production path
- [ ] 4.6 README knob values match the code
