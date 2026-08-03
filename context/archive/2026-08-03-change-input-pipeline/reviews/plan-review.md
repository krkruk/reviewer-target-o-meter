<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Change Input Pipeline Implementation Plan

- **Plan**: `context/changes/change-input-pipeline/plan.md`
- **Mode**: Deep
- **Date**: 2026-08-03
- **Verdict**: REVISE → SOUND after fixes
- **Findings**: 1 critical · 1 warning · 2 observations (all resolved FIXED)

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding

10/10 existing paths ✓, 8/8 new-file slots clear ✓, ~24 line-refs ✓ (every
`file:line` reference in the plan was checked against source and matched),
brief↔plan ✓, consumer repo + `master` + `feature/test-pull-request` + clean
`merge-base` ✓. Blast-radius sweep: all importers of changed symbols
(`from_env`, `run_review`, `_MAX_REPORTED`, `_SYSTEM_PROMPT`, `report`,
`_FIXTURE_DIFF`) are accounted for in the plan; no existing diff/context/github
module collides. `arun_review` exists (`graph.py:62`).

Note: this plan is exceptionally well-grounded. The findings below are two
"won't pass `make check` as written" snags plus two minor nits; the
architecture is sound (plain-function libraries, degrade convention preserved,
report's host-side re-check intact, trust-but-verify on the cap).

## Findings

### F1 — Module load-order: f-string prompt references a constant defined later

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 3 — 3.1 + 3.2 (`agent/nodes.py`)
- **Detail**: 3.1 kept `MAX_FINDINGS_PER_DIMENSION` at line 54; 3.2 splices it into `_SYSTEM_PROMPT` (lines 31-47) via an f-string/`.format` evaluated at import time — before the constant is bound → `NameError` on import; Phase 3's `make test`/`make check` can't pass.
- **Fix**: Define `MAX_FINDINGS_PER_DIMENSION` ABOVE `_SYSTEM_PROMPT` (or build the prompt string at call time in `build_checks_node`).
- **Decision**: FIXED (Fix in plan) — Phase 3.1 contract updated to require the constant above `_SYSTEM_PROMPT`, with the load-order rationale recorded.

### F2 — mypy won't narrow `str | None` / `int | None` through the `post_to_github` property

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Completeness
- **Location**: Phase 5 — 5.2 (`cli.py` CLI branching contract)
- **Detail**: Pseudocode passes `token=config.github_token` (`str | None`) and `pr_number=config.pr_number` (`int | None`) into required `str`/`int` params; mypy doesn't narrow through a property, so `make check` (`uv run mypy src`, no relaxation) fails Phase 5's criterion.
- **Fix**: Narrow explicitly inside `if config.post_to_github:` (re-check for None + degrade, or `assert ... is not None` which mypy honors).
- **Decision**: FIXED (Fix in plan) — Phase 5.2 contract pseudocode now includes an explicit `assert config.pr_number is not None and config.github_token is not None` with a mypy-narrowing comment.

### F3 — `tests/fixtures/sample-repo` is not a git repo; plan called it "the existing git fixture"

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 — 1.3 (`tests/test_diff.py` contract)
- **Detail**: `tests/fixtures/sample-repo` holds only `src/app.py` and has no `.git`; test contract (a) needs a real base to assert a non-empty `diff --git`. The tmp-repo fallback is the actual path; the "existing git fixture" phrasing misleads.
- **Fix**: Reword 1.3 to state the test must build a tmp git repo via gitpython.
- **Decision**: FIXED (Fix in plan) — Phase 1.3 Intent rewritten to flag sample-repo as plain files and direct the test to build a tmp git repo.

### F4 — Phase 6 "make test unaffected" Success Criterion had no matching Progress checkbox

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 6 — Success Criteria vs `## Progress` (mechanical contract)
- **Detail**: Phase 6 Automated SC listed 3 bullets; Progress had checkboxes for only 2 (the "make test unaffected" bullet had none).
- **Fix**: Insert a `- [ ] 6.2 make test unaffected` checkbox; renumber SMOKE → 6.3, manual → 6.4/6.5.
- **Decision**: FIXED (Fix in plan) — Progress Phase 6 block updated with the new 6.2 checkbox and renumbered 6.3/6.4/6.5.
