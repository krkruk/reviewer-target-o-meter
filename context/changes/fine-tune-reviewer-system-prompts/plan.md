# fine-tune-reviewer-system-prompts Implementation Plan

## Overview

Two coupled goals, both driven by the mock-defect validation:
1. **Raise recall** so all 6 planted defects in the mock change are caught,
   stable across runs (the pre-fine-tune A/B caught 4/6; a first softening
   attempt then hit 0 on variance, proving a single run can't certify recall).
2. **Add an `optional_findings` section** — a second, style-pickiness bucket
   (cap 3) that always emits something meaningful reflecting the code but
   never blocks the PR (never affects exit code). Reuses the `Finding` schema.

The two are coupled because the style bucket lives in the same prompt and
report schema as the main findings, and both surface in the same renderers.

## Current State Analysis

- **Phase 1 shipped** (`5652b50`): the safety lens was softened — bare/swallowing
  `except` + unbounded-state-accumulation added to the pattern list; "Report
  only substantive issues" replaced with recall-positive OBSERVATION guidance.
  137 tests green. The live A/B then returned **0 findings** (LLM variance at
  temperature=0 across a changed prompt — a single run is not signal).
- **The mock change** (6 planted defects) lives at git commit `aefe369` and was
  checked out to a worktree at `/tmp/mock-defect-review` for the A/B. The 6
  defects: hardcoded token, off-by-one, untested branches, duplicated logic,
  bare `except Exception`, unbounded global dict.
- **Schema today** (`findings.py`): `FindingsReport{findings, summary,
  overall_verdict}`. `exit_code` derives from `findings.flagged` (CRITICAL/
  WARNING). `Finding` requires a file:line anchor (FR-009), severity, impact,
  dimension, ≤2 fixes.
- **Render surfaces**: GitHub Markdown (`github.py` — table + collapsible
  details, `F{n}` ids injected at render) and stdout JSON (`cli.py:_emit_stdout`
  — `F{n}` ids injected into `model_dump` payload).
- **The `report` node** (`nodes.py`) re-validates `findings`, sorts, caps per
  dimension (5), injects ids, computes exit code. It emits ONLY `{"report": ...}`
  (the dedup fix from the prior change).

### Key Discoveries:

- **`optional_findings` reuses `Finding`** — confirmed. The model emits
  style/pickiness observations as `Finding` objects (severity=OBSERVATION) into
  a separate capped list. No new schema type; all validators reuse.
- **Exit code is untouched** by optional — confirmed. `exit_code` derives only
  from `findings.flagged`; optional is purely informational.
- **The renderers must learn a second section** — a clearly-labeled "Optional
  style observations" block (Markdown) / `optional_findings` key (JSON), with
  `O{n}` ids to distinguish from `F{n}`.
- **LLM variance is real.** temperature=0 does NOT guarantee identical output
  across prompt edits (the whole token sequence shifts). The acceptance bar is
  "all 6 caught, stable across 2 consecutive runs" — not a single run.
- **The prompt must direct style pickiness into `optional_findings`** so the
  main `findings` list stays focused on real defects and doesn't get diluted
  by style noise.

## Desired End State

- `FindingsReport` carries an `optional_findings: list[Finding]` (cap 3),
  emitted by the model (style/pickiness), rendered in both surfaces (Markdown
  "Optional style observations" section + JSON key), with `O{n}` ids, and
  **never** affecting `exit_code`.
- The reviewer catches **all 6** planted mock defects in the main `findings`,
  stable across 2 consecutive runs, AND emits 1-3 meaningful optional style
  findings on every review.
- No severity inflation; diff-scoping unchanged; cap (5) on main findings
  unchanged.

## What We're NOT Doing

- **Not adding a new schema type** — `optional_findings` reuses `Finding`.
- **Not letting optional affect exit code** — advisory-on-advisory only.
- **Not relaxing diff-scoping** or raising the main per-dimension cap (5).
- **Not changing the model or structured-output strategy** (DeepSeek + strict
  json_schema stays).
- **Not raising temperature** to chase determinism — variance is handled by the
  "stable across 2 runs" bar, not by changing the determinism knob.

## Implementation Approach

- **Phase 2 — `optional_findings` schema + render + prompt wiring** (TDD):
  add the field to `FindingsReport` (cap 3, reuses Finding, excluded from
  exit_code); thread it through the `report` node, both renderers, the stdout
  JSON emit; add the prompt section directing style pickiness into it. Unit
  tests for the cap, the exit-code isolation, and the render.
- **Phase 3 — recall tuning + stable validation** (iterative): run the A/B
  against the mock change, iterate on the prompt until all 6 defects are caught
  across 2 consecutive runs AND optional findings render. This is prompt-only
  iteration gated on the live signal — no schema change.

## Critical Implementation Details

- **`optional_findings` must be EXCLUDED from `exit_code`/`flagged`.** Those
  properties iterate `self.findings` only; adding a sibling list must not leak
  into them. Keep the isolation explicit (don't refactor `flagged` to scan both).
- **Strict structured output.** `create_agent(..., response_format=
  ProviderStrategy(FindingsReport, strict=True))` generates the JSON schema
  from the pydantic model — adding the field automatically exposes it to the
  model. The `max_length=3` constraint is emitted to the schema.
- **F{n} vs O{n} ids.** Main findings keep `F{n}`; optional uses `O{n}` so the
  two lists are distinguishable in both render surfaces. Inject at render (the
  existing convention — models are unreliable at sequential ids).

---

## Phase 1: softening the safety lens (DONE — 5652b50)

> Already shipped: the safety lens now enumerates swallowing-`except` +
> unbounded-state-accumulation and replaced the "substantive" gate with
> recall-positive OBSERVATION guidance. 4 prompt-invariant tests added. Kept
> here for continuity; no further work.

---

## Phase 2: `optional_findings` schema + render + prompt wiring

### Overview

Add the style-pickiness bucket end-to-end: schema field (cap 3, reuses
Finding, exit-code-isolated), `report`-node threading, both render surfaces
(Markdown section + JSON key with `O{n}` ids), and the prompt section directing
the model to emit 1-3 style observations there on every review.

### Changes Required:

#### 1. Add `optional_findings` to `FindingsReport`

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/findings.py`

**Intent**: The model needs a second, capped bucket for style/pickiness that
never affects the advisory exit code.

**Contract**: Add `optional_findings: list[Finding] = Field(default_factory=list,
max_length=3)` to `FindingsReport`. Do NOT change `flagged` or `exit_code` —
they iterate `self.findings` only, so the new list is automatically isolated.
The field is a normal pydantic field (visible in the JSON schema the model
sees via `ProviderStrategy(..., strict=True)`).

#### 2. Thread `optional_findings` through the `report` node

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: The `report` node must pass the optional findings through to the
emitted report object (after the existing re-validate/sort/cap on main
findings). Optional findings are NOT sorted/capped per-dimension — they have
their own `max_length=3` cap at the schema level; just pass them through.

**Contract**: In `report()`, after building `final_report`, carry
`optional_findings` from the raw state into the report object. The
`_extract_findings` path returns only main findings today; extend it (or read
`state.get("optional_findings", [])`) so the report object's
`optional_findings` is populated. Keep the cap enforcement in the schema.

#### 3. Render `optional_findings` in both surfaces

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/github.py`
and `reviewer-target-o-meter/src/reviewer_target_o_meter/cli.py`

**Intent**: Surface the style observations distinctly so they're never confused
with blocking findings.

**Contract**:
- `github.py:render_comment` — after the main findings details block, add a
  second clearly-labeled section (e.g. a separate `<details>` "Optional style
  observations") with `O{n}` ids (separate enumerate counter from `F{n}`).
- `cli.py:_emit_stdout` — inject `O{n}` ids into the `optional_findings` list
  in the JSON payload (parallel to the `F{n}` injection on main findings).

#### 4. Prompt: direct style pickiness into `optional_findings`

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`
(`_SYSTEM_PROMPT`)

**Intent**: The model must emit 1-3 meaningful style/pickiness observations
into `optional_findings` on EVERY review — naming what reflects the code's
style quality without being a real defect.

**Contract**: Add a short section to `_SYSTEM_PROMPT` (after the grammar/caps
section) directing: emit 1-3 `optional_findings` (style, naming, readability,
idiom, consistency vs siblings) — be extra picky, anchor on a representative
line, severity OBSERVATION, these never block the PR. Add a prompt-invariant
test that the section name + the "optional_findings" field name are present.

### Success Criteria:

#### Automated Verification:

- `make test` passes; new tests cover: optional cap (3) enforced;
  exit_code unaffected by optional; `O{n}` id injection in both surfaces;
  prompt-invariant for the new section.
- `make check` (ruff + mypy) passes.

#### Manual Verification:

- A live run shows the "Optional style observations" section populated (1-3
  items) in the posted Markdown and the `optional_findings` key in stdout JSON.
- Exit code is unchanged by the presence of optional findings.

---

## Phase 3: recall tuning + stable validation (all 6 defects)

### Overview

Iterate on the prompt until the reviewer catches all 6 planted mock defects
(main findings) across 2 consecutive runs, with optional findings rendering.
Prompt-only; no schema change.

### Changes Required:

#### 1. Prompt recall iteration

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Close any remaining recall gap so all 6 defects are caught
consistently. The Phase-1 softening targeted the right patterns; if the A/B
still misses one, sharpen the lens wording (e.g. make the swallowing-`except`
cue more explicit, or add a "scan every changed function for a bare/broad
except" directive).

**Contract**: Iterate on the safety/coverage lens text based on which of the
6 defects the live run misses. Keep diff-scoping + severity calibration
intact. Each prompt edit keeps the prompt-invariant tests green.

### Success Criteria:

#### Automated Verification:

- `make test` passes; `make check` passes.

#### Manual Verification:

- 2 consecutive runs against `/tmp/mock-defect-review` both catch all 6
  planted defects (hardcoded token, off-by-one, untested branches, duplicated
  logic, bare `except Exception`, unbounded `_posts` dict).
- Optional findings render (1-3) on both runs.
- No severity inflation; no false-positive explosion (>~10 findings on the
  mock would signal over-correction).

---

## Testing Strategy

### Unit Tests:

- **Phase 2**: optional cap (3) enforced at the schema; `exit_code` unaffected
  by optional findings; `O{n}` id injection in stdout JSON + Markdown render;
  prompt-invariant for the optional_findings section.
- **Phase 1 (done)**: the 4 softening invariants.

### Manual Testing Steps:

1. Run `make run DIR=/tmp/mock-defect-review` (the 6-defect worktree) twice.
2. Confirm both runs catch all 6 defects + render optional findings.
3. Confirm exit code reflects only main findings.flagged.

## Performance Considerations

- The prompt grows by ~8-12 lines across Phases 2-3. Negligible vs the existing
  ~6.5k chars; cached-prompt discount amortizes it. No latency impact.

## References

- Schema: `reviewer-target-o-meter/src/reviewer_target_o_meter/findings.py`
- Prompt: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py:48-150`
- Renderers: `github.py` (Markdown), `cli.py:_emit_stdout` (JSON).
- Mock change (6 defects): git commit `aefe369` (worktree at `/tmp/mock-defect-review`).
- Pre-fine-tune A/B: `/tmp/mock_review_run2.log` (4/6).
- First softening A/B: `/tmp/mock_review_run3.log` (0/6 — variance).

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands.

### Phase 1: softening the safety lens (DONE)

#### Automated

- [x] 1.1 Extend the safety lens: add bare/swallowing-`except` + unbounded-state-accumulation to the pattern list; replace "Report only substantive issues" with recall-positive OBSERVATION guidance (suppress style noise only) — 5652b50
- [x] 1.2 Add 4 prompt-invariant tests: substantive-gate removed, error-suppression named, unbounded-growth named, OBSERVATION-recall guidance present — 5652b50
- [x] 1.3 `make test` passes (137); `make check` passes; the 6 existing prompt-invariant tests stay green — 5652b50

#### Manual

- [ ] 1.4 Re-run vs the `rate_limiter` mock change; rolled into Phase 3 (the 0/6 variance proved a single run isn't signal)

### Phase 2: `optional_findings` schema + render + prompt wiring

#### Automated

- [x] 2.1 Add `optional_findings: list[Finding]` (cap 3) to `FindingsReport`; confirm `exit_code`/`flagged` iterate main `findings` only (isolation)
- [x] 2.2 Thread `optional_findings` through the `report` node into the emitted report object
- [x] 2.3 Render in both surfaces: Markdown "Optional style observations" section + stdout JSON key, with `O{n}` ids (separate counter from `F{n}`)
- [x] 2.4 Add prompt section directing 1-3 style/pickiness observations into `optional_findings` every review + prompt-invariant test
- [x] 2.5 `make test` passes; `make check` passes

#### Manual

- [ ] 2.6 Live run shows optional findings populated (1-3) in Markdown + JSON; exit code unchanged

### Phase 3: recall tuning + stable validation (all 6 defects)

#### Automated

- [ ] 3.1 Iterate prompt recall (safety/coverage lens) until all 6 mock defects caught; keep invariants green

#### Manual

- [ ] 3.2 Two consecutive runs vs `/tmp/mock-defect-review` catch all 6 defects + render optional findings; no severity inflation / FP explosion
