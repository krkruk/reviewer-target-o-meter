# fine-tune-reviewer-system-prompts Implementation Plan

## Overview

Raise the reviewer's recall on subtle reliability/maintainability smells by
editing the single safety lens in `_SYSTEM_PROMPT` (`agent/nodes.py`). A live
validation run caught 4 of 6 planted defects but missed a bare
`except Exception` (swallowed error) and an unbounded module-level dict — both
sit in code the prompt's "Report only substantive issues" gate likely
suppressed. The fix softens that gate for a specific enumerated class of
patterns (error-suppression, unbounded growth, silent failure) without
touching diff-scoping, severity calibration, or the per-dimension cap.

## Current State Analysis

The reviewer's system prompt (`nodes.py:48-143`) is a single f-string with a
load-bearing section order: role → hard rules → three lenses → emit mapping →
severity/impact/verdict → grammar + caps. The **Safety, quality & pattern
compliance** lens (`nodes.py:103-110`) reads:

> over the changed source files, look for security (...), performance (N+1,
> unbounded iteration, missing pagination), reliability (missing error handling
> at external boundaries, races, leaks), data-safety (...), and substantive
> pattern mismatches vs 1-2 sibling files (...). Scale pattern depth to change
> size (≤3 files → minimal pattern effort). **Report only substantive issues.**

Two problems surfaced in the validation run (log: `/tmp/mock_review_run2.log`,
4/6 caught):

1. **"Report only substantive issues" is a recall suppressor.** The model read
   a swallowed `except Exception: return {}` in `stats()` and an unbounded
   `defaultdict(list)` global as *not substantive enough* — both are real
   reliability smells but below the bar that phrase sets. The phrase gives the
   model permission to self-suppress anything that "feels minor."
2. **The reliability list is incomplete.** "missing error handling at external
   boundaries" names *absent* handling, but not *present-but-hostile* handling
   — bare `except Exception` that swallows and returns a default, hiding the
   failure. Likewise "unbounded iteration" is framed as a performance loop
   issue, not as unbounded *state accumulation* (a collection that grows
   forever in a long-lived process).

### Key Discoveries:

- **The prompt is f-string-spliced at import time** (`nodes.py:48`). The
  `MAX_FINDINGS_PER_DIMENSION` constant is interpolated via `{...}`. Any edit
  must preserve valid f-string syntax (escape literal `{`/`}` as `{{`/`}}`).
- **Six prompt-invariant tests lock specific phrases** (`test_nodes.py:29-86`):
  diff-scoping anchor rule, active-investigation protocol, plan-tolerance
  conditional, no-execution rule, per-dimension cap reference, three-lens
  names. These must stay green; the safety-lens edit touches none of them
  directly, but the "three lenses named" test asserts `"safety" in prompt` —
  the lens header must retain that word.
- **The "Report only substantive issues" phrase is NOT asserted on by any
  test.** It's safe to remove/replace without touching invariants.
- **Severity calibration is prompt-resident, not schema-enforced** (AGENTS.md
  §c/h). Adding "flag at OBSERVATION when not critical/warning" keeps the
  model from inflating severity on the newly-enumerated patterns.
- **Diff-scoping stays hard.** The edit is *within* the safety lens — it does
  not relax the "never flag a file the PR did not change" rule. The two missed
  defects were on changed files; recall failed on the *pattern recognition*,
  not the scoping.

## Desired End State

- The reviewer flags error-suppression (bare/swallowing `except`), unbounded
  state growth, and silent-failure (return-a-default-on-error) patterns when
  they appear in changed files — at OBSERVATION when not CRITICAL/WARNING.
- The "Report only substantive issues" gate is replaced with recall-positive
  guidance for these specific pattern classes; trivial/style noise is still
  suppressed (we are NOT turning this into a linter).
- Diff-scoping, severity calibration, and the per-dimension cap (5) are
  unchanged. The six prompt-invariant tests stay green.
- A re-run against the `rate_limiter` mock change catches the 2 previously-
  missed defects (bare `except Exception`, unbounded `_posts` dict) — ideally
  6/6, with no severity inflation on the 4 it already caught.

## What We're NOT Doing

- **Not raising `MAX_FINDINGS_PER_DIMENSION`** (stays 5). The suppressor was
  the "substantive" gate + incomplete pattern list, not the cap. Revisit only
  if recall is still low after this change.
- **Not relaxing diff-scoping.** Untouched files stay off-limits; the edit is
  purely within the safety lens's pattern enumeration.
- **Not changing severity calibration rules.** CRITICAL/WARNING stay reserved
  for real correctness/security defects; the new patterns default to
  OBSERVATION unless they cause a real defect.
- **Not switching the structured-output strategy or model.** DeepSeek + strict
  json_schema stays (locked in AGENTS.md §d).
- **Not adding new tools or dimensions.** The 7-dimension enum is unchanged.

## Implementation Approach

One surgical edit to the Safety lens block in `_SYSTEM_PROMPT`:

1. **Replace "Report only substantive issues"** with recall-positive guidance:
   explicitly enumerate the pattern classes the validation missed
   (error-suppression, unbounded growth, silent-failure), and direct the model
   to flag them at OBSERVATION when they don't rise to CRITICAL/WARNING —
   while keeping a "still suppress trivial style/formatting noise" clause so
   we don't become a linter.

2. **Extend the reliability sub-list** to name *present-but-hostile* error
   handling (bare/swallowing `except` that hides failures) alongside the
   existing "missing error handling," and add "unbounded state accumulation"
   (a collection that grows without bound in a long-lived process) to the
   performance/reliability list.

3. **Add a prompt-invariant test** asserting the new recall-positive phrasing
   is present and the old "report only substantive issues" gate is gone — so a
   future edit can't silently re-suppress recall.

## Critical Implementation Details

- **F-string syntax.** `_SYSTEM_PROMPT` is an f-string evaluated at import.
  The new text must not introduce unescaped `{`/`}`; any literal braces must
  be `{{`/`}}`. The existing prompt has no literal braces today, so this is
  only a risk if the new wording uses them (avoid).
- **Keep the lens header word "safety".** `test_three_review_lenses_named`
  asserts `"safety" in PROMPT_LOWER`. The lens bullet starts
  "Safety, quality & pattern compliance" — leave that phrase intact.

---

## Phase 1: softening the safety lens + recall-positive pattern enumeration

### Overview

Edit the single Safety lens block in `_SYSTEM_PROMPT` to enumerate the
error-suppression / unbounded-growth / silent-failure patterns and replace the
"Report only substantive issues" recall gate with recall-positive guidance
(OBSERVATION for non-critical smells, still suppress style noise).

### Changes Required:

#### 1. Extend the safety lens's reliability + recall guidance

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: The validation missed a swallowed `except Exception` and an
unbounded global dict because (a) the reliability list named only *missing*
error handling, not *present-but-hostile* handling, and (b) the "Report only
substantive issues" gate let the model self-suppress them. Extend the list and
replace the gate so these patterns are flagged.

**Contract**: In the "Safety, quality & pattern compliance" lens bullet
(`nodes.py:103-110`):

- In the reliability parenthetical, after "missing error handling at external
  boundaries, races, leaks", add **present-but-hostile error handling**: a
  bare or broad `except` that swallows the error and returns a default
  (hiding failures from the caller/operator). Keep it distinct from "missing"
  handling.
- In the performance parenthetical, after "unbounded iteration, missing
  pagination", add **unbounded state accumulation**: a collection (especially
  module-level / process-global) that grows without bound over the process
  lifetime with no eviction.
- Replace the sentence "Report only substantive issues." with recall-positive
  guidance: "Flag the patterns above even when minor — emit them at
  OBSERVATION severity when they don't cause a real correctness/security
  defect; reserve CRITICAL/WARNING for genuine defects. Still suppress
  trivial style/formatting noise (naming, whitespace, import order) — this is
  a critical-point reviewer, not a linter."

The lens bullet keeps its header "Safety, quality & pattern compliance" (the
word "safety" is asserted on by `test_three_review_lenses_named`).

#### 2. Prompt-invariant test: recall-positive phrasing present, suppressor gone

**File**: `reviewer-target-o-meter/tests/test_nodes.py`

**Intent**: Lock the recall-positive change so a future edit can't silently
re-introduce the "substantive" gate or drop the new pattern enumeration.

**Contract**: Add tests in `TestSystemPromptInvariants`:

- `test_substantive_gate_removed`: assert `"report only substantive issues"`
  is NOT in `PROMPT_LOWER` (the suppressor is gone).
- `test_error_suppression_pattern_named`: assert the prompt names
  swallowing/bare-`except` error handling (e.g. `"swallow"` or
  `"bare"` + `"except"` present) — covers the `stats()` defect class.
- `test_unbounded_growth_pattern_named`: assert the prompt names unbounded
  state accumulation (e.g. `"unbounded"` present) — covers the `_posts`
  defect class.
- `test_observation_severity_recall_guidance_present`: assert the prompt
  directs OBSERVATION severity for non-critical smells (e.g.
  `"observation severity"` present).

### Success Criteria:

#### Automated Verification:

- `make test` passes (133 existing + 4 new prompt-invariant tests = 137).
- `make check` (ruff + mypy) passes.
- The six existing prompt-invariant tests stay green (diff-scoping,
  plan-tolerance, no-execution, cap reference, three lenses).

#### Manual Verification:

- Re-run the reviewer against the `rate_limiter` mock change (the 6 planted
  defects) and confirm it now catches the bare `except Exception` in `stats()`
  and the unbounded `_posts` dict — ideally 6/6, no severity inflation on the
  4 it already caught (F1 CRITICAL, F2/F3 WARNING, F4 OBSERVATION).
- No false-positive explosion: the count stays reasonable (the mock change
  should not suddenly produce 15+ findings).

**Implementation Note**: This is a prompt-only edit with no behavior change
to the graph/nodes/tools — the only "code" is the f-string and its tests. The
manual re-run is the real proof; pause for it before archiving.

---

## Testing Strategy

### Unit Tests:

- 4 new prompt-invariant tests (the suppressor is gone; the three pattern
  classes are named; OBSERVATION-recall guidance is present). These are
  offline string assertions on `_SYSTEM_PROMPT`.

### Manual Testing Steps:

1. Re-create the `rate_limiter` mock change on a throwaway branch off master
   (the 6 planted defects: hardcoded token, off-by-one, untested branches,
   duplicated logic, bare `except Exception`, unbounded global dict).
2. Run `PR_NUMBER=26 GITHUB_TOKEN=$(gh auth token)
   GITHUB_REPOSITORY=krkruk/target-o-meter make run DIR=../` from the
   `reviewer-target-o-meter/` package dir, logging to `/tmp/`.
3. Compare the finding count + anchors vs the pre-fine-tune run
   (`/tmp/mock_review_run2.log`: 4 findings, missed the `except` + the dict).
4. Confirm 6/6 (or at minimum the 2 previously-missed), no severity inflation,
   no false-positive explosion.

## Performance Considerations

- The prompt grows by ~3-4 lines (~150-200 chars). Negligible vs the existing
  ~6k-char prompt; the cached-prompt discount amortizes it. No latency impact.

## References

- Prompt source: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py:48-143`
  (the safety lens is `:103-110`).
- Prompt-invariant tests:
  `reviewer-target-o-meter/tests/test_nodes.py:29-86`.
- Pre-fine-tune validation log: `/tmp/mock_review_run2.log` (4/6 findings).
- Mock change (planted defects): the discarded `feat(rate-limit)` commit on
  `fix/graph-recursion-issue` (recreate for the A/B).
- Severity calibration is prompt-resident: AGENTS.md §c, §h.

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands.

### Phase 1: softening the safety lens + recall-positive pattern enumeration

#### Automated

- [x] 1.1 Extend the safety lens: add bare/swallowing-`except` + unbounded-state-accumulation to the pattern list; replace "Report only substantive issues" with recall-positive OBSERVATION guidance (suppress style noise only)
- [x] 1.2 Add 4 prompt-invariant tests: substantive-gate removed, error-suppression named, unbounded-growth named, OBSERVATION-recall guidance present
- [x] 1.3 `make test` passes (137); `make check` passes; the 6 existing prompt-invariant tests stay green

#### Manual

- [ ] 1.4 Re-run vs the `rate_limiter` mock change (6 planted defects); confirm the 2 previously-missed defects (bare `except Exception`, unbounded `_posts`) are now caught, no severity inflation, no false-positive explosion
