# fine-tune-reviewer-system-prompts — Plan Brief

> Full plan: `context/changes/fine-tune-reviewer-system-prompts/plan.md`

## What & Why

A live validation run caught 4 of 6 planted defects but missed a swallowed
`except Exception` and an unbounded module-level dict — both real reliability
smells the reviewer should flag. The cause is the prompt's "Report only
substantive issues" gate (a recall suppressor) plus an incomplete reliability
pattern list. This change softens that gate for a specific enumerated class of
patterns, raising recall without inflating severity or relaxing diff-scoping.

## Starting Point

The reviewer runs DeepSeek with a single `_SYSTEM_PROMPT` (`agent/nodes.py`),
its safety lens listing reliability patterns but gating them behind "Report
only substantive issues." Six prompt-invariant tests lock the load-bearing
phrases (diff-scoping, plan-tolerance, no-execution, cap, three lenses). The
pre-fine-tune A/B is captured at `/tmp/mock_review_run2.log` (4/6).

## Desired End State

The reviewer flags error-suppression (bare/swallowing `except`), unbounded
state growth, and silent-failure patterns on changed files — at OBSERVATION
when not a real defect — while still suppressing trivial style noise. A re-run
against the same mock change catches the 2 previously-missed defects (ideally
6/6), with no severity inflation on the 4 it already caught.

## Key Decisions Made

| Decision | Choice | Why | Source |
|---|---|---|---|
| Recall lever | Soften "substantive" only; cap stays 5 | The suppressor was the gate + incomplete pattern list, not the cap | Plan |
| New patterns default severity | OBSERVATION | Keeps CRITICAL/WARNING reserved for real defects; avoids inflation | Plan |
| Validation method | Re-run vs the same mock change | Direct A/B on the exact 6-defect input | Plan |
| Diff-scoping | Unchanged | The miss was pattern recognition, not scoping — both defects were on changed files | Plan |

## Scope

**In scope:** edit the Safety lens in `_SYSTEM_PROMPT`; add 4 prompt-invariant
tests; re-validate vs the mock change.

**Out of scope:** raising the per-dimension cap; relaxing diff-scoping;
changing severity rules, model, or structured-output strategy; new
tools/dimensions.

## Architecture / Approach

Single-file prompt edit (`agent/nodes.py`, the f-string at `:48-143`) +
parallel test additions (`test_nodes.py`). No graph/node/tool behavior change.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Soften safety lens | Recall-positive prompt + invariant tests | Over-correction → false-positive explosion (guarded by "suppress style noise" clause + the re-run) |

**Prerequisites:** the `rate_limiter` mock change (6 planted defects) for the
A/B re-run; the pre-fine-tune log at `/tmp/mock_review_run2.log`.
**Estimated effort:** ~1 session, single phase.

## Open Risks & Assumptions

- Prompt edits are stochastic — the re-run may catch the 2 missed defects but
  also surface a new false positive or two; acceptable per the operator's
  "tolerate more false positives" directive, but watch for an explosion (>10
  findings on the mock would signal over-correction).
- The mock is synthetic; real diffs may behave differently. This tunes recall
  on one defect class, not a measured improvement across a corpus.

## Success Criteria (Summary)

- The 2 previously-missed defects (bare `except`, unbounded dict) are caught.
- No severity inflation on F1-F4; no false-positive explosion (>10 findings).
- All 137 tests green; `make check` clean.
