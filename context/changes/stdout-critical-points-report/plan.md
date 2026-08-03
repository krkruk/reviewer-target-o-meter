# S-01 — Stdout Critical-Points Report (North Star) Implementation Plan

## Overview

S-01 is the north-star slice: it proves the product hypothesis (that an
automated "critical points in this PR" signal is finally fillable) by turning
the `checks` node's **minimal** analysis prompt into the **full impl-review
methodology**, and by replacing the hardcoded `plan=None` with diff-driven plan
discovery. The output contract F-02 shipped (stdout JSON + PR Markdown comment +
advisory exit) is the delivery surface; S-01 owns only the **analysis layer**
that fills it with signal. Success = a reviewer reading the output sees
specific, file/line-anchored, actionable findings — not generic style noise —
and a clean change yields ~0 flagged findings (negative control).

## Current State Analysis

Both foundations are in place and the pipeline already runs end-to-end against a
real checkout and posts real comments.

- **F-01 (archived):** the four-node graph
  (`START → context_load → plan_discovery → checks → report → END`), the
  full-shape schema (`Finding`/`FindingsReport`: Severity + Impact + 7-dimension
  + Fix-grammar), the OpenRouter provider (`ProviderStrategy(FindingsReport,
  strict=True)`), the two search `@tool`s (`text_search`/`structural_search`),
  cost/latency bounds (`recursion_limit=40`, `max_iterations=12`,
  `run_timeout=120`), and the fail-safe (`GraphRecursionError` → partial report +
  advisory exit).
- **F-02 (this branch, all 6 phases done):** real diff computation (`diff.py`),
  context loading (`context_loader.py`), GitHub posting (`github.py`), the
  env-driven stdout/post mode switch, the per-dimension findings cap
  (`MAX_FINDINGS_PER_DIMENSION=5`, enforced in prompt AND host-side), the GHA
  workflow template + consumer integration (verified live on
  `krkruk/target-o-meter` PR #22).

What's still stub/minimal — S-01's scope:

- **The `checks` node's system prompt is minimal** (`agent/nodes.py:38-56`): it
  tells the model the output *shape* but not *how to review*. The full impl-review
  methodology (3 lenses, 7-dimension grading, finding grammar) is unbuilt.
- **`plan` is hardcoded `None`** (`cli.py:47`: `"plan": None,  # unchanged — real
  plan discovery is S-01`). So plan-dependent checks (drift, scope-discipline)
  never run, even when the reviewed repo *has* a plan. The consumer repo
  (`../target-o-meter`) carries the 10x `context/changes/<change-id>/` structure,
  so the plan input exists in the realistic target — it's just never loaded today.

### Key Discoveries:

- **The methodology is plan-centric; the product is plan-tolerant.**
  `impl-review-instructions.md` is titled *"review an implementation against the
  plan it claims to realize"* and step 3.4 says "Run the plan's automated test
  commands." Both must adapt for reviewer-target-o-meter: plan-dependent checks
  are **skipped when no plan exists** (FR-006), and the PRD Non-Goal
  (`prd.md:118`) forbids running the reviewed project's test/lint/build
  commands — so MISSING-TEST / UNCOVERED-BEHAVIOR are flagged from **static /
  presence evidence**, never execution.
- **3 lenses vs 7 dimensions is a think-vs-label split.** The methodology's 3
  review lenses (plan-drift / safety-quality-pattern / test-coverage) are the
  *method*; the `Finding.dimension` enum (correctness, security,
  maintainability, testability, performance, design, documentation) is the
  *label*. The prompt instructs in lenses, then maps each finding to the 7-dim
  enum at emit (decision Q4).
- **Diff-scoping is load-bearing for signal quality (user constraint).** The agent
  must anchor every finding on a **diff-touched file/line** — it must NOT use the
  search tools to discover and flag pre-existing problems in untouched files
  (that's the repo-wandering noise that kills the product). Tools are for
  deepening context on changed files only. One legitimate exception: a plan-drift
  MISSING finding anchors on a *planned* file the change should have touched but
  didn't.
- **`Severity.is_flagged` stays host-side** (`findings.py:27-34`): the model picks
  the enum; the host decides the signal (FR-011). The methodology's
  APPROVED/NEEDS-ATTENTION/REJECTED verdict and 7-dim PASS/WARN/FAIL grid are
  **narrative-only** in `overall_verdict` — the dimension grid is host-side
  (computed from flagged severities), not a model field (decision Q2).
- **Signal quality is the existential risk** (roadmap S-01: "if the agent's
  critical points are generic or low-signal, the whole product hypothesis
  fails"). The existing smoke (`test_smoke_input_pipeline.py`) only checks "a
  planted SQLi appears in the output" — it cannot distinguish a *specific* finding
  from a *generic* one. S-01 adds targeted + negative-control signal smoke
  (decision Q3).
- **The 10x change-folder shape is the plan source.** A repo following the 10x
  convention has `context/changes/<change-id>/plan.md` (and `frame.md`,
  `research.md`); `context/archive/` holds completed changes. The consumer repo
  confirms this layout.

## Desired End State

When S-01 is complete, a reviewer runs `reviewer-target-o-meter <dir>` (or the GHA
workflow fires) and the agent: discovers the plan from the diff (when one is
determinable), loads it, runs the **full impl-review methodology** scoped to the
diff's changed files (3 lenses → 7-dimension findings), and emits a
`FindingsReport` whose findings are **specific** (file+line+the-actual-concern)
and **non-generic** (a clean diff yields ~0 flagged findings). The output
contract — stdout JSON + PR Markdown comment + advisory exit — is unchanged; it
now carries materially better signal. A negative-control smoke proves the clean
case; targeted signal smoke proves the non-generic case against planted
plan-specific and context-dependent defects.

**Verification of the end state:** `make check` + `make test` green (no new
unit-test surface unless the plan-discovery module warrants it); the new
signal-quality smoke set (`SMO=1 … make llm-test`) shows (a) targeted defects
are flagged with specific anchors/keywords, and (b) a clean diff yields ~0
flagged findings; a `make run DIR=…` against a consumer branch that **actually
has a diff** (see "Consumer-repo manual-run precondition" below) shows findings
anchored on that branch's real changed files; `AGENTS.md` records the methodology
provenance (OQ#7).

> **Consumer-repo manual-run precondition (added in triage of F2).** As of
> 2026-08-03 the consumer's `feature/test-pull-request` is **0 commits ahead of
> master** (empty diff → `compute_diff` returns `""`), and its only active
> change dir `bootstrap-verification` has **no `plan.md`** (only
> `verification.md` → the single-active fallback returns `None`, not that dir).
> Both undercut the original "observe findings on the consumer PR" proof. Before
> running any `make run DIR=../target-o-meter …` manual step, FIRST put the
> consumer repo into the assumed state: either (a) check out / create a branch
> that carries a real diff against master, and add a real
> `context/changes/<id>/plan.md` to exercise the drift lens; or (b) fall back to
> a synthetic repo that mirrors that shape (a branch with a diff + a change dir
> containing `plan.md`). Do not run the manual step against an empty-diff branch
> — it cannot show anchored findings, and a `None` plan there is correct
> behavior, not a regression.

## What We're NOT Doing

- **No change to the output contract.** The `report` node, the stdout JSON shape,
  `render_comment`, the per-dimension cap, and the advisory exit stay as F-02
  shipped them. S-01 touches the analysis layer only (decision Q5). The model
  *may* populate `overall_verdict` (already an optional schema field) — S-01 does
  not add a dimension-grid field to the schema.
- **No executing the reviewed project's test/lint/build commands.** Read-and-flag
  only (PRD Non-Goal `prd.md:118`). MISSING-TEST / UNCOVERED-BEHAVIOR come from
  static/presence evidence (diff + plan), never execution.
- **No per-lens parallel sub-nodes.** Single `checks` node (F-01 locked decision;
  revisit at a later slice only if per-lens depth proves shallow on real output).
- **No schema changes.** `Finding`/`FindingsReport`/`Severity`/`Dimension` stay
  exactly as F-01 defined them. No `lens` field, no dimension-grid field.
- **No `--plan` / `PLAN_CHANGE_ID` config surface.** Plan discovery is
  diff-driven + single-active fallback only (decision Q1) — no new env knob.
- **No merge blocking.** Exit code stays advisory (FR-008, Non-Goal).
- **No LLM-as-judge.** Signal verification is the targeted + negative-control
  smoke (decision Q3), not a second model call.
- **No secret/entropy scanner.** Stdout mode writes nothing to the host
  (`prd.md:44`); the schema-level absolute-path guard already ships
  (`findings.py:95-100`).

## Implementation Approach

Four sequential phases, ordered so the **existential risk (signal quality)** is
attacked first and proven before the layer that depends on it (plan discovery)
adds complexity:

1. **Full methodology system prompt + diff-scoping rule** — the core deliverable.
   Rewrite `_SYSTEM_PROMPT` into a sectioned, methodology-bearing prompt; bake in
   the diff-scoping constraint (tools deepen context on changed files only). No
   plan input yet — the prompt is plan-tolerant by construction (the drift lens
   is gated on "if a plan is provided"). Proven by extending the existing smoke.
2. **Diff-driven plan discovery** — unlocks the drift lens. A new
   `plan_loader.py` module + CLI wiring replaces `plan=None`. Proven by a unit
   test over a tmp 10x-shaped tree + a plan-aware smoke.
3. **Signal-quality smoke suite** — proves the hypothesis. Targeted
   non-generic-defect smokes + a negative-control (clean diff) smoke. This is
   the make-or-break verification.
4. **Docs & sync** — `AGENTS.md` records the methodology provenance (OQ#7);
   `change.md` → `planned`; roadmap status touch (if the workflow asks).

The output contract (report node / stdout JSON / `render_comment`) is touched
**only** to surface `overall_verdict` — and only as a one-line addition in the
existing renderer, not a contract change. Concrete trigger (replaces the former
vague "if it deserves rendering"): `overall_verdict` is already an optional
schema field (`findings.py:114`); `render_comment` renders it verbatim whenever
the model emits a non-empty value, and omits the line otherwise. No grading
grid, no new field, no schema change. If Phase 1's live output shows the model
never populates `overall_verdict`, skip even this one line — the field stays
optional and the contract is untouched.

## Critical Implementation Details

- **Diff-scoping is an active investigation protocol, not a passive filter (user
  constraint — refined in triage of F1).** The product fails two ways: (1) the
  agent becomes a repo-wide linter emitting generic noise on untouched files, or
  (2) the agent stays shallow — findings that name the diff surface but miss the
  real risk because it never traced the flow. The prompt must drive BOTH: anchor
  every finding on a diff-touched file/line (the one exception is a plan-drift
  MISSING finding on a planned-but-absent file), AND actively use the tools to
  make findings specific and correct — `structural_search` to trace a changed
  symbol's definition/call sites and map control/data flow around a risky site,
  `text_search` to read a sibling for a pattern comparison. The old framing
  ("tools exist ONLY to confirm a concern; use sparingly") under-investigates and
  was replaced. A finding with no tool-backed context on a non-trivial change is a
  shallowness smell. State the protocol early, bluntly, and repeat it in tool-use
  guidance. Note: enforcement stays prompt-resident by design — the model's work
  should not be dropped host-side; the Phase 3.3 smoke is the regression gate.
- **Plan-tolerance is structural in the prompt, not just the wiring.** The drift
  lens's instructions are conditional: *"If a plan is provided, …; if not, skip
  plan-dependent checks."* This keeps Phase 1 independently shippable (plan
  discovery lands in Phase 2) and matches the existing `plan_discovery` node's
  None-tolerance (`agent/nodes.py:73-78`).
- **Lens→dimension mapping is prompt-resident (soft), not schema-enforced.** The
  prompt tells the model how each lens maps to the 7-dim enum at emit
  (drift→correctness/maintainability/design; safety→security/performance/
  reliability-ish→maintainability; coverage→testability). A real defect can
  legitimately map to two dimensions — the model picks the best fit; the host
  does not enforce a 1:1 mapping (decision Q4).
- **The methodology's verdict + dimension grid stay narrative/host-side
  (decision Q2).** The model may emit a 1-2 sentence `overall_verdict`; the
  PASS/WARN/FAIL-per-dimension grid (if surfaced at all) is host-side derivation
  from the flagged severities, NOT a model field. Do not extend the schema.
- **Negative control is the hardest signal test to keep honest.** A "clean diff"
  fixture must be clean enough that a good reviewer genuinely finds nothing
  flaggable — if the fixture has a real smell, a `~0 findings` assertion is
  misleading. Build it from the *base* (pre-defect) versions of the existing
  fixtures (`test_smoke_input_pipeline.py` already has clean modules).

## Phase 1: Full Methodology System Prompt + Diff-Scoping Rule

### Overview

Rewrite the minimal `_SYSTEM_PROMPT` (`agent/nodes.py:38-56`) into a sectioned,
methodology-bearing prompt that (a) instructs the 3 review lenses as the
thinking method, (b) maps findings to the 7-dim enum at emit, (c) bakes in the
diff-scoping hard rule, and (d) carries the finding-grammar + cap rules. No plan
discovery yet — the prompt is plan-tolerant by construction.

### Changes Required:

#### 1.1 Rewrite the system prompt with the full methodology

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Turn the shape-only minimal prompt into the full impl-review
methodology so the agent reviews *how the product requires* — targeted,
diff-scoped, plan-tolerant, read-and-flag-only — instead of emitting generic
dimension-sweep findings.

**Contract**: Replace `_SYSTEM_PROMPT` (`agent/nodes.py:38-56`) with a single
sectioned f-string (still splicing `MAX_FINDINGS_PER_DIMENSION`). Section order
is load-bearing (role → hard rules → lenses → emit mapping → grammar → caps).
The sections, in order:

1. **Role** — non-interactive critical-point reviewer embedded in an automated
   pipeline; given the diff (+ context-or-none + plan-or-none), emit a
   `FindingsReport`. Read and flag only.
2. **Hard rules (state bluntly, repeat in tool guidance)** —
   (a) **Diff-scoping as an ACTIVE investigation, not a passive filter** (this is
   the core differentiator — the product dies if the agent becomes a repo-wide
   linter, but it ALSO dies if findings stay shallow because the agent never
   looked past the diff surface). The protocol, in order:
     1. **Read the changed files first.** Before any tool call, read each diff
        hunk and form the change's core flow (what's wired to what, what's new,
        what shifted). Findings anchor on a file/line the diff touches.
     2. **Then deepen with tools — actively, on the changed files' context.**
        The search tools exist to make findings SPECIFIC and CORRECT, not merely
        to confirm a hunch: use `structural_search` (ast-grep) to trace a changed
        symbol's definition and call sites within the changed files and to map
        the real control/data flow around a risky site; use `text_search`
        (ripgrep) to read a sibling file for a pattern comparison or to confirm
        a symbol's usage. Scale effort to risk: a touched auth/SQL/migration
        boundary warrants full flow-mapping; a touched docstring does not.
     3. **Never flag a file the PR did not change.** Tools deepen context on
        changed files (and, for a pattern comparison, their immediate siblings)
        — they never discover issues in untouched files. The sole exception: a
        plan-drift MISSING finding anchors on a *planned* file the change should
        have touched but didn't.
   (b) Read-and-flag only: NEVER execute the reviewed project's
   test/lint/build/any-shell commands (PRD Non-Goal).
   (c) Never edit files, post comments, or ask questions.
   (d) (Folded into (a).) Use tools to build the evidence that makes a finding
   specific and correct — a finding with no tool-backed context on a non-trivial
   change is a smell that the analysis stayed shallow.
3. **Three review lenses (the method)** —
   - **Plan drift** (only if a plan is provided; else skip): for each planned
     change, judge MATCH / DRIFT / MISSING / EXTRA against the diff. Flag DRIFT
     (semantic mismatch), MISSING (planned but absent), and EXTRA not on the
     plan's exclusions list. If no plan is provided, this lens is skipped
     entirely.
   - **Safety, quality & pattern compliance**: over the changed source files,
     look for security (injection, hardcoded secrets, missing authn/authz at
     boundaries), performance (N+1, unbounded iteration, missing pagination),
     reliability (missing error handling at external boundaries, races, leaks),
     data-safety (destructive ops without rollback, migrations without a path),
     and substantive pattern mismatches vs 1-2 sibling files (use a tool to read
     a sibling). Scale pattern depth to change size (≤3 files → minimal pattern
     effort). Report only substantive issues.
   - **Test coverage**: the plan declares what "tested" means. Match each
     test-related Automated Verification commitment to a test file in the diff;
     flag MISSING TEST (severity CRITICAL). Scan changed source for new exported
     functions / new branches / new endpoints and flag UNCOVERED BEHAVIOR
     (WARNING) when no test in the diff covers them. Respect explicit opt-outs in
     the plan's exclusions. If no plan is provided, do only the diff-evident
     coverage check (a new public function with no test file touched → UNCOVERED
     BEHAVIOR).
4. **Emit mapping (lenses → the 7-dimension enum)** — pick the single
   best-fitting `dimension` per finding: drift→correctness/maintainability/design;
   safety→security/performance/maintainability; coverage→testability;
   documentation findings when a plan/doc commitment is missed. A finding may
   legitimately fit two dimensions — pick the best fit.
5. **Severity, impact, verdict** — severity (critical/warning/observation) says
   how bad if ignored; impact (low/medium/high) says how hard to decide; they're
   orthogonal. If you emit `overall_verdict`, make it 1-2 sentences naming the
   change's biggest risk (narrative, not a grade grid).
6. **Finding grammar + caps** — each finding: repo-relative `file`, 1-based
   `line`, `<=120`-char `title`, rationale in `detail`, up to 2 `FixOption`s (a
   one-sentence fix DIRECTION, never an applied patch; if two, exactly one
   `recommended`). Emit at most `{MAX_FINDINGS_PER_DIMENSION}` findings per
   dimension; prioritize the highest-severity, highest-impact within each.

Keep `_SYSTEM_PROMPT` as a module-level f-string (so `{MAX_FINDINGS_PER_DIMENSION}`
still resolves at import time — `MAX_FINDINGS_PER_DIMENSION` stays defined above
it, `agent/nodes.py:34`).

#### 1.2 Prompt unit test (offline, mocked)

**File**: `reviewer-target-o-meter/tests/test_graph.py` (extend) or
`reviewer-target-o-meter/tests/test_nodes.py` (NEW — see what the existing
test_graph.py DI `_FakeAgent` pattern looks like first)

**Intent**: Lock the prompt's load-bearing invariants without burning a model
call — the diff-scoping rule, the plan-tolerance conditional, the no-execution
rule, and the cap reference must all be present in `_SYSTEM_PROMPT`.

**Contract**: A pure offline test asserting `_SYSTEM_PROMPT` contains (a) the
diff-scoping protocol — both halves: the anchor rule ("anchor every finding on a
file the diff touches" / "never flag a file the PR did not change") AND the
active-investigation rule (a phrase directing the model to read changed files
first, then use `structural_search`/`text_search` to trace symbols/flow and read
siblings — not merely "confirm a concern"); (b) the plan-tolerance conditional
("if a plan is provided" / "if no plan"); (c) the no-execution rule ("never
execute" the reviewed project's commands); (d) the `MAX_FINDINGS_PER_DIMENSION`
cap reference; (e) the three lens names. This guards
against a future edit silently dropping the diff-scoping rule — the single most
load-bearing line.

### Success Criteria:

#### Automated Verification:

- `make check` — ruff + mypy clean on `agent/nodes.py`.
- `make test` — the new prompt-invariant test passes; all existing tests green
  (the prompt change is text-only; the mocked-LLM graph tests don't assert on
  prompt content beyond what this test adds).

#### Manual Verification:

- Eyeball `_SYSTEM_PROMPT`: confirm the section order is role → hard rules →
  lenses → emit mapping → grammar → caps, and the diff-scoping rule reads
  bluntly enough that a model won't misread it as a suggestion.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase. A live signal
check (`make llm-test` against an existing smoke) here is optional but
informative — if the new prompt produces visibly more specific findings on the
planted SQLi, that's early signal-quality evidence.

---

## Phase 2: Diff-Driven Plan Discovery

### Overview

Replace the hardcoded `plan=None` (`cli.py:47`) with a real plan-discovery
module: parse the diff for a touched `context/changes/<id>/plan.md`, fall back to
the single active (non-archived) change dir, else `None`. Unlocks the drift lens.

### Changes Required:

#### 2.1 Plan-loader module

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/plan_loader.py` (NEW)

**Intent**: Provide a single function that turns a (checkout path, diff) into the
plan text the analysis consumes, or `None` when no plan is determinable. Follow
the existing degrade convention (`AGENTS.md` §b): on any read failure, write a
`WARNING:` to stderr and return `None` (the prompt's plan-tolerance handles
`None`).

**Contract**: `def load_plan(repo_path: str | Path, diff: str) -> str | None`.
Discovery is a non-obvious ordered chain (the ordering is load-bearing —
diff-driven wins because "the current change" is what the diff touches;
single-active is the fallback when the diff is ambiguous or doc-only):

```python
def _discover_change_id(repo_path: Path, diff: str) -> str | None:
    # 1. Diff-driven: a path like context/changes/<id>/plan.md (or frame.md /
    #    research.md) appears in the diff → <id> is the current change.
    touched = _changed_change_ids(diff)        # parse "diff --git a/context/changes/<id>/..."
    if len(touched) == 1:
        return touched.pop()
    if len(touched) > 1:
        return None                             # ambiguous → fall through / give up
    # 2. Single-active fallback: exactly one non-archived change dir with a plan.md.
    active = _active_change_ids(repo_path)      # glob context/changes/*/plan.md, exclude context/archive/
    if len(active) == 1:
        return active[0]
    return None                                 # 0 or >1 active → no plan (plan-tolerance)
```

Then read `<repo_path>/context/changes/<id>/plan.md` (the authoritative artifact
— `frame.md`/`research.md` are context, already loaded by `context_loader.py`).
Cap with a module constant `MAX_PLAN_CHARS` (sized to leave room in the context
budget alongside the diff + context — start at ~12k chars; the plan is the
single highest-signal input, so it earns a generous share). Truncate at a clean
boundary and append `… [plan truncated: {remaining} more chars]`. Missing file /
unreadable → `WARNING:` to stderr + `None`. The function is a plain library call
(not a `@tool`, not a graph node) — same shape as `diff.py` / `context_loader.py`.

#### 2.2 CLI wiring

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/cli.py`

**Intent**: Feed the discovered plan into the graph instead of `None`.

**Contract**: `inputs["plan"]` becomes `load_plan(repo_path, diff)` where `diff`
is the already-computed `compute_diff(repo_path, config.base_ref)` result (compute
once, pass to both — don't diff twice). Replace
`cli.py:47` (`"plan": None, ...`) — keep the inline comment updated to reflect
that real plan discovery has landed. `_FIXTURE_DIFF` stays (system tests).

#### 2.3 Plan-loader unit tests

**File**: `reviewer-target-o-meter/tests/test_plan_loader.py` (NEW)

**Intent**: Cover the discovery chain, the cap, and None-tolerance with a tmp
10x-shaped tree (mirrors `test_context_loader.py`'s fixture approach).

**Contract**: Assert (a) a diff touching
`context/changes/feature-x/plan.md` → `load_plan` returns that plan's text; (b) a
diff touching two change dirs → returns `None` (ambiguous) + no raise; (c) a
diff touching nothing under `context/changes/` but a repo with exactly one active
change dir → returns that plan; (d) zero or two active change dirs and no
diff-touched change → `None`; (e) `context/archive/<id>/plan.md` is never picked
(single-active excludes archive); (f) an over-budget plan is truncated with the
marker; (g) a missing `plan.md` (change dir exists but no plan file) → `None` +
`WARNING:`; (h) a single active change dir whose only doc is `verification.md`
(no `plan.md`) → `None` (the real consumer shape as of 2026-08-03 — guards
against the loader accidentally treating a non-plan doc as the plan).

### Success Criteria:

#### Automated Verification:

- `make test` — new `test_plan_loader.py` green; existing tests unaffected.
- `make check` — ruff + mypy clean on the new module + the CLI edit.

#### Manual Verification:

- `make run DIR=../target-o-meter` against a consumer branch that **has a real
  diff and a real `context/changes/<id>/plan.md`** (see the "Consumer-repo
  manual-run precondition" under Desired End State — as of 2026-08-03
  `feature/test-pull-request` is empty-diff and `bootstrap-verification` has no
  `plan.md`, so neither shows a loaded plan). Confirm the stdout JSON's effective
  analysis ran with a real plan loaded (observable via a debug run or a
  plan-aware smoke; see Phase 3). If no such branch/dir exists yet, create one
  before running this step, or fall back to a synthetic repo that mirrors the
  shape — do NOT run against the empty-diff branch and expect an anchored,
  plan-driven result.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Phase 3: Signal-Quality Smoke Suite

### Overview

Prove the product hypothesis directly: the findings are **specific and
non-generic** (targeted-defect smokes assert the *actual concern*, not just "a
finding exists"), and a **clean diff yields ~0 flagged findings** (negative
control — the test that catches a generic style-linter regression). This is the
make-or-break verification; it lives in the opt-in `smoke` set
(`tests/test_smoke_signal.py`).

### Changes Required:

#### 3.1 Targeted non-generic-defect smokes

**File**: `reviewer-target-o-meter/tests/test_smoke_signal.py` (NEW,
`@pytest.mark.smoke`)

**Intent**: Assert the reviewer surfaces the *specific* planted concern with a
*specific* anchor + keyword, distinguishing a real finding from generic noise.
Each test plants a defect that requires reading the diff (and, for one case, the
context/plan) to flag correctly.

**Contract**: `pytestmark = pytest.mark.smoke`. Build per-test git repos via
`gitpython` (mirror `_build_buggy_repo` in `test_smoke_input_pipeline.py`).
Cases — each asserts `report.findings` is non-empty, at least one finding is
anchored on the changed file, AND the finding's `title+detail` blob contains the
**specific** concern keyword (not just "security risk"):

- **Plan-specific drift**: a repo with a `context/changes/<id>/plan.md` whose
  "Changes Required" names a field/behavior; the feature diff implements it
  differently (DRIFT). Assert a finding whose blob names the drifted field **and
  whose `dimension` is one of correctness / maintainability / design** (the
  drift→dimension mapping the prompt teaches). This is the test that proves plan
  discovery (Phase 2) + the drift lens (Phase 1) compose end-to-end.
- **Context-dependent security**: extend the existing SQLi pattern but place the
  defect such that flagging it correctly requires the loaded `AGENTS.md` context
  (e.g. AGENTS.md says "all SQL must be parameterized"; the diff introduces
  string-concat SQL). Assert the finding references the SQL/concat/injection
  concern specifically **and `dimension == security`**.
- **Uncovered behavior**: a diff adding a new exported function with no test file
  touched (and no plan, or a plan that doesn't opt out). Assert an
  UNCOVERED-BEHAVIOR finding anchored on the new function, `dimension ==
  testability`.

Reuse the `Config.from_env()` + `arun_review` invocation pattern from
`test_smoke_input_pipeline.py`. Each targeted smoke now asserts BOTH (i) the
specific title/detail keyword blob AND (ii) the expected `dimension` — the
dimension is the field that routes a finding in downstream tooling, so a finding
that names the right concern but files under the wrong dimension must fail (this
was added in triage of F6; previously only the uncovered-behavior case checked
`dimension`). The keyword assertions must be specific enough that a generic
"this code has issues" finding would NOT satisfy them.

#### 3.2 Negative-control smoke (clean diff → ~0 flagged)

**File**: `reviewer-target-o-meter/tests/test_smoke_signal.py` (same file)

**Intent**: The test that catches a generic-noise regression. A genuinely clean
change (a well-formed, safe, tested addition) must yield ~0 *flagged* findings
(no CRITICAL/WARNING). This is the hardest test to keep honest — the fixture must
be clean enough that a good reviewer agrees there's nothing to flag.

**Contract**: Build a clean repo: base = a correct, parameterized module; feature
diff = a *benign* improvement (e.g. add a docstring, rename a local for clarity,
add a trivial pure helper with a tiny test). Run the live reviewer; assert
`report.exit_code == 0` (no CRITICAL/WARNING findings). Tolerate a small number
of OBSERVATION findings (≤2) — observations on a clean diff are acceptable
stylistic notes, not noise that fails the product. If the model emits a
WARNING/CRITICAL on this clean diff, that's a signal-quality regression — the
test fails loudly. Build the clean module from the *base* versions of the
existing fixtures (they're already genuinely clean) to avoid inventing a
"clean" snippet that secretly has a smell.

#### 3.3 Diff-scoping guard smoke

**File**: `reviewer-target-o-meter/tests/test_smoke_signal.py` (same file)

**Intent**: Prove the Phase-1 diff-scoping rule holds on real model output: every
finding's `file` is either a diff-touched file OR a planned-but-missing file
(the one allowed exception). This is the guard against the repo-wandering failure
mode.

**Contract**: Build a repo with a changed file AND a pre-existing
deliberately-smelly file NOT touched by the diff (e.g. an untouched `legacy.py`
with a blatant SQLi or a bare `except:` — and, to defeat a single-name check, a
second distinct untouched smelly file, e.g. `stale_util.py` with a different
smell). Run the live reviewer; then assert the **set-difference** form, not a
single hardcoded name:

```python
changed = {path for path in git_diff_changed_files(diff)}      # the diff's touched set
planned_missing = {...}                                        # the fixture plan's planned-but-absent set, if any
allowed = changed | planned_missing
bad = {f.file for f in report.findings} - allowed
assert not bad, f"findings anchored off-diff: {bad}"
```

This catches *any* off-diff filename the model invents — not just `legacy.py` —
and correctly passes the one allowed exception (a planned-but-missing file). The
earlier single-name `assert "legacy.py" not in …` is too weak: it passes if the
model invents a *different* untouched filename, and it can false-trip if
`legacy.py` were ever named in the fixture's plan. (Keep `legacy.py` /
`stale_util.py` OUT of any fixture plan so they can't be legit MISSING anchors.)

### Success Criteria:

#### Automated Verification:

- `make test` — unaffected (the new smoke set is skipped without `SMOKE=1`).
- `make check` — ruff + mypy clean on the new test module.
- `SMOKE=1 OPENROUTER_API_KEY=… make llm-test` — the new signal smoke set runs
  green: targeted defects flagged with specific anchors/keywords; negative
  control exits 0 (no flagged findings); diff-scoping guard holds (no finding on
  the untouched file).

#### Manual Verification:

- Read the targeted-smoke findings: confirm they read as *specific* (name the
  actual concern at the actual location), not generic ("consider reviewing this
  code"). If they read generic, the Phase-1 prompt needs tightening — iterate
  before closing S-01.
- Run `make run DIR=../target-o-meter` against a consumer branch that has a real
  diff (see the "Consumer-repo manual-run precondition" under Desired End State —
  `feature/test-pull-request` is empty-diff as of 2026-08-03 and will not work
  here). Eyeball the findings: they should be anchored on that branch's actual
  changed files and reference the real changes, not the repo's pre-existing code.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase. This is the
phase where "is the signal actually good?" gets answered — if the negative
control fails or the targeted smokes show generic findings, do NOT proceed to
Phase 4; iterate on the Phase-1 prompt first.

---

## Phase 4: Docs & Sync

### Overview

Record the methodology provenance (resolves roadmap OQ#7) in `AGENTS.md` and
stamp `change.md` to `planned`. Docs-only; no code change.

### Changes Required:

#### 4.1 AGENTS.md methodology provenance

**File**: `AGENTS.md` (git root)

**Intent**: Resolve OQ#7 ("Critical-point analysis methodology provenance") so
future agents read the methodology source + the product-specific adaptations
once and stay unblocked — the same paydown pattern F-01 used for the
`quality_override` debt.

**Contract**: Add a section (or extend the existing graph-convention section,
§b) recording: (a) the methodology source — the `/10x-impl-review-ci` reference
(`references/impl-review-instructions.md`); (b) the **three product-specific
adaptations** that divergence from a literal impl-review — plan-tolerance (skip
plan-dependent checks when no plan; FR-006), no-command-execution (MISSING-TEST
/ UNCOVERED-BEHAVIOR from static evidence; PRD Non-Goal), and diff-scoping
(anchor on changed files only; tools deepen context on changed files, never
discover issues in untouched files); (c) the lens→dimension mapping is
prompt-resident (soft), not schema-enforced; (d) the verdict is narrative-only
(`overall_verdict`); the dimension grid is host-side. Point at
`_SYSTEM_PROMPT` (`agent/nodes.py`) as the single source of truth for the
prompt text.

#### 4.2 Update change.md status

**File**: `context/changes/stdout-critical-points-report/change.md`

**Intent**: Reflect that planning is complete.

**Contract**: Set `status: planned` and `updated: 2026-08-03`.

### Success Criteria:

#### Automated Verification:

- `uv run ruff check && uv run mypy src && uv run pytest` all still green
  (docs-only change).

#### Manual Verification:

- A fresh reader can locate the methodology source and the three adaptations in
  `AGENTS.md` without reading this plan.
- OQ#7 in `context/foundation/roadmap.md` is addressed by the new section (the
  roadmap entry itself is not edited — the AGENTS.md section is the resolution).

**Implementation Note**: Phase 4 is the final phase; once it passes, S-01 is
ready for `/10x-impl-review` and the north-star hypothesis is considered proven
(pending the live signal evidence from Phase 3).

---

## Testing Strategy

### Unit Tests:

- **Prompt invariants** (`test_graph.py` or new `test_nodes.py`, Phase 1.2): the
  `_SYSTEM_PROMPT` contains the diff-scoping rule, the plan-tolerance
  conditional, the no-execution rule, the cap reference, and the three lens
  names — a guard against a silent regression on the load-bearing prompt lines.
- **Plan loader** (`test_plan_loader.py`, Phase 2.3): the discovery chain
  (diff-driven → single-active → None), cap, archive exclusion,
  unreadable-file degrade.

### Integration Tests:

- **Signal-quality smoke** (`test_smoke_signal.py`, Phase 3): live OpenRouter,
  opt-in via `make llm-test`. Targeted non-generic defects + negative control +
  diff-scoping guard. This is the system-level proof of the north-star
  hypothesis.

### Manual Testing Steps:

1. `make llm-test` (Phase 3) — targeted defects flagged with specific anchors;
   clean diff exits 0; no finding on an untouched smelly file.
2. `make run DIR=../target-o-meter` (Phase 2/3) — a consumer branch with a real
   diff (precondition under Desired End State; the empty-diff
   `feature/test-pull-request` will not show anchored findings); findings
   anchored on the branch's changed files; plan loaded if discoverable.
3. Read 2-3 real-output findings by eye — confirm they read specific and
   actionable, not generic. If generic, iterate the Phase-1 prompt.
4. Grep the run output — confirm `OPENROUTER_API_KEY` never appears
   (`prd.md:44`).

## Performance Considerations

- The prompt grows substantially (minimal → full methodology). The cached-prefix
  effect (OpenRouter's ~99% cached-prompt discount, F-01 research) means the
  system prompt is amortized across all agent steps within a review — the
  per-step cost is dominated by the diff + tool output, not the prompt. No budget
  change expected; the existing `recursion_limit=40` / `max_iterations=12` /
  `run_timeout=120` bounds hold.
- `MAX_PLAN_CHARS ≈ 12k` is the one new budget knob. It sits alongside the
  ~20k-char diff cap and ~8k-char context cap (F-02 constants). Total prompt
  budget stays well within the model's context window; if a future diff+plan+
  context combo threatens the window, the caps truncate with visible markers
  (never silent truncation — `AGENTS.md` convention).
- No new model calls: single `checks` node, no LLM-as-judge, no per-lens
  parallelism. The cost/latency profile is unchanged from F-02.

## Migration Notes

- **Behavior change (intended):** the production CLI now loads a real plan when
  discoverable. Repos without the 10x `context/changes/` structure see no change
  (`load_plan` returns `None`, the prompt's plan-tolerance kicks in — FR-006).
- **Prompt change:** `_SYSTEM_PROMPT` is substantially rewritten. Any downstream
  consumer that string-matched the old prompt text (none known — it's an internal
  module constant) must re-match. The schema, the graph shape, and the output
  contract are unchanged.
- **No schema migration:** `Finding`/`FindingsReport` are exactly as F-01
  defined. `overall_verdict` was already optional; S-01 may populate it but
  doesn't require it.
- **New test module:** `test_smoke_signal.py` joins the opt-in smoke set. It is
  skipped by default (`make test` / `-m "not smoke"`); it runs only via
  `make llm-test` with `OPENROUTER_API_KEY` set.

## References

- Roadmap S-01 + OQ#7: `context/foundation/roadmap.md:82-93,126`
- PRD US-01 + FR-006/007/008/009/010/011 + Non-Goals:
  `context/foundation/prd.md:49-61,79-92,117-119`
- Methodology (provenance): `/home/krzysztofkruk/.agents/skills/10x-impl-review-ci/references/impl-review-instructions.md`
- F-01 plan (schema, graph convention, locked decisions):
  `context/archive/2026-08-01-agent-runtime-finding-schema/plan.md`
- F-02 plan (diff/context/posting/cap — the output contract S-01 builds on):
  `context/archive/2026-08-03-change-input-pipeline/plan.md`
- Graph convention + degrade philosophy + severity rules: `AGENTS.md` §b–§e
- Existing wiring touched: `agent/nodes.py:38-56` (prompt), `cli.py:47` (plan),
  `graph.py` (unchanged), `findings.py` (unchanged)
- Test patterns to follow: `tests/test_smoke_input_pipeline.py`
  (`_build_buggy_repo` gitpython fixture, `Config.from_env` + `arun_review`,
  keyword-blob assertions), `tests/test_context_loader.py` (tmp-tree unit
  fixture), `tests/conftest.py:16-22` (smoke gate)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step
> lands. Do not rename step titles.

### Phase 1: Full Methodology System Prompt + Diff-Scoping Rule

#### Automated

- [x] 1.1 `make check` clean on `agent/nodes.py` (rewritten `_SYSTEM_PROMPT`)
- [x] 1.2 `make test` green incl. new prompt-invariant test (diff-scoping
      protocol — anchor rule AND active-investigation rule; plan-tolerance
      conditional, no-execution rule, cap reference, lens names)

#### Manual

- [ ] 1.3 Eyeball `_SYSTEM_PROMPT`: section order role → hard rules → lenses →
      emit mapping → grammar → caps; the diff-scoping protocol reads as an
      active investigation (read changed files → trace flow with tools), not a
      passive "confirm a concern" filter

### Phase 2: Diff-Driven Plan Discovery

#### Automated

- [ ] 2.1 `make test` green incl. new `tests/test_plan_loader.py` (discovery
      chain, cap, archive exclusion, degrade, no-plan.md-dir → None)
- [ ] 2.2 `make check` clean on new `src/reviewer_target_o_meter/plan_loader.py`
      + the `cli.py` edit

#### Manual

- [ ] 2.3 `make run DIR=../target-o-meter` against a branch with a real diff +
      a real `context/changes/<id>/plan.md` (precondition under Desired End
      State) — plan loaded when discoverable; empty-diff / no-plan.md dirs
      correctly yield None

### Phase 3: Signal-Quality Smoke Suite

#### Automated

- [ ] 3.1 `make test` unaffected (new smoke skipped without `SMOKE=1`)
- [ ] 3.2 `make check` clean on new `tests/test_smoke_signal.py`
- [ ] 3.3 `SMOKE=1 OPENROUTER_API_KEY=… make llm-test` green: targeted defects
      flagged with specific anchors/keywords AND correct `dimension`; negative
      control exits 0; diff-scoping guard holds via the set-difference assertion
      (no finding anchored off the diff's changed-files / planned-missing set)

#### Manual

- [ ] 3.4 Read targeted-smoke findings — specific (name the actual concern at
      the actual location), not generic; iterate Phase-1 prompt if generic
- [ ] 3.5 `make run DIR=../target-o-meter` against the real PR — findings
      anchored on the PR's changed files, referencing the real changes

### Phase 4: Docs & Sync

#### Automated

- [ ] 4.1 `uv run ruff check && uv run mypy src && uv run pytest` still green
      (docs-only)

#### Manual

- [ ] 4.2 Fresh reader locates methodology source + 3 adaptations in `AGENTS.md`
      without reading this plan; OQ#7 addressed
