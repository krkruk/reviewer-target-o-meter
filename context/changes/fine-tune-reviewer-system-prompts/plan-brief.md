# fine-tune-reviewer-system-prompts — Plan Brief

> Full plan: `context/changes/fine-tune-reviewer-system-prompts/plan.md`

## What & Why

Two coupled goals from the mock-defect validation: (1) raise recall so all 6
planted defects are caught, stable across runs (pre-fine-tune caught 4/6; a
first softening then hit 0 on variance — a single run can't certify recall);
and (2) add an `optional_findings` style-pickiness bucket (cap 3) that always
emits something meaningful but never blocks the PR.

## Starting Point

Phase 1 shipped (`5652b50`): the safety lens was softened (swallowing-`except`
+ unbounded-growth enumerated; "substantive" gate replaced with OBSERVATION
recall guidance). 137 tests green. The mock change (6 defects) is at git
`aefe369`, worktree `/tmp/mock-defect-review`.

## Desired End State

`FindingsReport` carries `optional_findings` (cap 3, reuses Finding,
exit-code-isolated), rendered in both surfaces with `O{n}` ids. The reviewer
catches all 6 mock defects across 2 consecutive runs AND emits 1-3 optional
style findings every review. No severity inflation; diff-scoping/cap unchanged.

## Key Decisions Made

| Decision | Choice | Why | Source |
|---|---|---|---|
| optional_findings shape | Reuse Finding, cap 3 | Zero new schema; all validators reuse; renderers already handle Finding | Plan |
| Exit code isolation | Optional never affects exit | "Doesn't block the PR" — exit driven only by main findings.flagged | Plan |
| Recall lever | Soften lens (Phase 1) + iterate (Phase 3) | The suppressor was the gate + pattern list, not the cap | Plan |
| Validation bar | All 6 caught, stable across 2 runs | The 0/6 variance proved a single run isn't signal | Plan |
| O{n} vs F{n} ids | Separate counters | Distinguish style observations from blocking findings in both surfaces | Plan |

## Scope

**In scope:** Phase 2 (schema field + render + prompt section); Phase 3 (prompt
recall iteration to all-6); validation.

**Out of scope:** new schema type; optional affecting exit code; raising the
main cap; relaxing diff-scoping; changing model/temperature.

## Architecture / Approach

Phase 2 is TDD: schema field → report-node threading → both renderers → prompt
section. Phase 3 is iterative prompt tuning gated on the live 2-run A/B.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Soften safety lens | recall-positive prompt (DONE) | LLM variance (materialized as 0/6) |
| 2. optional_findings | schema + render + prompt | exit-code isolation must hold |
| 3. Recall tuning | all 6 caught, 2-run stable | over-correction → FP explosion |

**Prerequisites:** the mock worktree at `/tmp/mock-defect-review`.
**Estimated effort:** ~2 sessions (Phase 2 schema, Phase 3 iteration).

## Open Risks & Assumptions

- LLM variance: temperature=0 ≠ identical across prompt edits. The 2-run bar
  guards but may need 3+ prompt iterations in Phase 3.
- "Stable across 2 runs" is a sample of 2, not a statistical guarantee.

## Success Criteria (Summary)

- All 6 mock defects caught across 2 consecutive runs; optional findings render.
- Exit code unaffected by optional; no severity inflation; no FP explosion.
- All tests green; `make check` clean.
