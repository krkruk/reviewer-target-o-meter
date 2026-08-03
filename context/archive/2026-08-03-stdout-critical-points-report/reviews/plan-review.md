<!-- PLAN-REVIEW-REPORT -->
# Plan Review: S-01 — Stdout Critical-Points Report (North Star)

- **Plan**: `context/changes/stdout-critical-points-report/plan.md`
- **Mode**: Deep
- **Date**: 2026-08-03
- **Verdict**: SOUND (after triage — was REVISE; all 6 findings resolved)
- **Findings**: [0 critical] [3 warnings] [3 observations]

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS (OBSERVATION F5 was a test-strength nit, now fixed) |
| Architectural Fitness | PASS (F1 reframed from "needs host-side backstop" to "active-investigation protocol" per user) |
| Blind Spots | PASS (F2 consumer-precondition + F6 dimension assertions fixed) |
| Plan Completeness | PASS (F3 stale ref + F4 vague trigger fixed) |

## Grounding

9/9 code paths verified (`agent/nodes.py:38-56` `_SYSTEM_PROMPT`, `cli.py:48`
`"plan": None`, `findings.py` schema facts, `state.py` ReviewState,
`context_loader.py`, `diff.py`, `graph.py`, `config.py`, `agent/tools/`);
4/4 symbols verified (`_FakeAgent` DI pattern in `test_graph.py:126`,
`_build_buggy_repo` in `test_smoke_input_pipeline.py`, `MAX_FINDINGS_PER_DIMENSION`,
`gitpython` in `uv.lock`); brief↔plan consistent. One off-by-one in a citation
(plan says `cli.py:47`; the `plan` key is at `:48`) — trivial, not escalated.
Roadmap S-01 + OQ#7 and PRD FR-006/007/008/009/010/011 + Non-Goals all confirmed.
F-02 reference was stale (archived) — fixed as F3. Consumer repo state
(`feature/test-pull-request` empty-diff; `bootstrap-verification` has no
`plan.md`) verified directly — drove F2.

## Findings

### F1 — Diff-scoping rule was prompt-only; reframed as active-investigation protocol

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Blind Spots (reframed to Architectural Fitness in resolution)
- **Location**: Phase 1 §1.1 (Hard rules) + Critical Implementation Details; cf. `report()` in `agent/nodes.py:157`
- **Detail**: The plan called diff-scoping "the existential risk" / "core product differentiator" but enforced it only via prompt text, while giving the less-load-bearing per-dimension cap a host-side backstop (`_cap_per_dimension`, nodes.py:182) because "prompts are unreliable." Internal inconsistency: the most important rule had the weakest enforcement.
- **Resolution**: User chose neither host-side drop (Fix A) nor prompt-only-accept (Fix B). Direction: do NOT drop findings host-side (wastes the model's work); instead harden the prompt into an ACTIVE investigation protocol — read changed files first, then use `structural_search`/`text_search` to trace symbols and map control/data flow around risky sites, read siblings for pattern comparison. Enforcement stays prompt-resident; Phase 3.3 smoke is the regression gate.
- **Edits applied**: Phase 1 §1.1 hard rule (a) rewritten as a 3-step active-investigation protocol; rule (d) folded in; Critical Implementation Details "Diff-scoping" bullet rewritten; Phase 1.2 prompt-invariant test contract extended to assert both the anchor rule AND the active-investigation rule; Progress 1.2 + 1.3 updated.
- **Decision**: FIXED (user-directed reframing)

### F2 — Manual verification against ../target-o-meter was unverifiable as written

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Desired End State (L98-104); Phase 2.3 Manual; Phase 3.5 Manual; Testing Strategy step 2
- **Detail**: Two compounding facts: `feature/test-pull-request` is 0 commits ahead of master (empty diff → `compute_diff` returns `""`), and `bootstrap-verification` has only `verification.md` — no `plan.md` — so the single-active fallback globs `context/changes/*/plan.md` → [] → None, not that dir. The plan's claim that the fallback "should pick bootstrap-verification" (L403-404) was wrong. Every "run against the consumer PR, observe X" manual step could not show X.
- **Fix A ⭐ Applied**: Documented a "Consumer-repo manual-run precondition" block under Desired End State; re-pointed all three manual-run sites (Phase 2.3, Phase 3.5, Testing Strategy #2) to require a branch with a real diff + a real `plan.md`, or a synthetic repo mirroring that shape. Added unit case (h) to Phase 2.3: a single active change dir with only `verification.md` (no `plan.md`) → None, locking the real consumer shape. Updated Progress 2.1 + 2.3.
- **Decision**: FIXED via Fix A

### F3 — Stale F-02 reference path (archived)

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: References (L657)
- **Detail**: References cited `context/changes/change-input-pipeline/plan.md`; that path does not exist — F-02 is archived at `context/archive/2026-08-03-change-input-pipeline/plan.md`.
- **Fix**: Repointed the reference to the archive path.
- **Decision**: FIXED

### F4 — Vague `overall_verdict` rendering trigger

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Implementation Approach (L149-152)
- **Detail**: "if Phase 1's output reveals the optional overall_verdict deserves rendering" was undefined — the implementer had no criterion, and it seeded scope creep into the locked output contract.
- **Fix**: Replaced the vague conditional with a concrete trigger: `overall_verdict` is already an optional schema field (`findings.py:114`); `render_comment` renders it verbatim when non-empty, omits the line otherwise. No grading grid, no new field. If the model never populates it, skip even the one line.
- **Decision**: FIXED

### F5 — Phase 3.3 diff-scoping guard asserted a single filename

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Lean Execution
- **Location**: Phase 3.3 (Diff-scoping guard smoke)
- **Detail**: `assert "legacy.py" not in {f.file for f in …}` only caught that one name. A model inventing a *different* untouched filename passed; and the plan's own MISSING-file exception could false-trip if `legacy.py` were named in the fixture plan.
- **Fix**: Replaced with the set-difference form — every `finding.file` must be in the diff's changed-files set OR the fixture plan's planned-but-missing list. Added a second distinct untouched smelly file (`stale_util.py`) to defeat single-name checks; directed that the smelly files stay OUT of any fixture plan. Updated Progress 3.3.
- **Decision**: FIXED

### F6 — Dimension-label correctness was mostly unverified

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 3.1; lens→dimension mapping (Critical Impl. Details)
- **Detail**: The lens→dimension mapping is prompt-resident and fuzzy ("reliability-ish → maintainability", L173). On a free-tier model with a substantially larger prompt (the plan's own Open Risk), dimension mis-labeling is the likely failure mode — and `dimension` is the field that routes a security finding to documentation in downstream tooling. Yet only the UNCOVERED-BEHAVIOR smoke asserted `dimension = testability`; the drift and SQLi smokes asserted title+detail keywords only.
- **Fix**: Added a `dimension` assertion to each targeted smoke — drift → correctness/maintainability/design; SQLi → security; uncovered → testability — matching the emit-mapping the prompt teaches. Each targeted smoke now asserts BOTH the keyword blob AND the expected dimension. Updated Progress 3.3 wording.
- **Decision**: FIXED

## Notes for the implementer

- The Progress↔Phase mechanical contract was re-verified after edits: one `## Progress`, all four phases matched, no stray checkboxes in phase bodies.
- The single off-by-one in a citation (plan says `cli.py:47`; the `"plan": None` key is at `cli.py:48`) was not escalated — fix opportunistically when touching that line.
- F1's resolution is prompt-resident by design; do NOT add a host-side finding-drop in `report()`. The Phase 3.3 smoke (now strengthened via F5) is the regression gate.
