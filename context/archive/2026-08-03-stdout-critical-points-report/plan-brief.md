# Stdout Critical-Points Report (North Star) — Plan Brief

> Full plan: `context/changes/stdout-critical-points-report/plan.md`

## What & Why

S-01 is the north-star slice — the one that proves the product hypothesis: that
an automated "critical points in this PR" signal is finally fillable at a
useful price and quality point. Both foundations (F-01 agent runtime + schema,
F-02 diff/context/posting pipeline) are in place and the tool already runs
end-to-end against a real checkout and posts real PR comments. What's still
**minimal** is the analysis itself — the `checks` node carries a shape-only
prompt, and `plan` is hardcoded `None`. S-01 fills the analysis layer with the
full impl-review methodology and real plan discovery, then proves the signal is
non-generic.

## Starting Point

The pipeline works end-to-end today, but the *signal* is unproven. The `checks`
node's system prompt (`agent/nodes.py:38-56`) tells the model the output *shape*
but not *how to review* — the full methodology (3 lenses, 7-dimension grading)
is unbuilt. `cli.py:47` hardcodes `plan=None`, so plan-dependent checks (drift,
scope-discipline) never run even though the consumer repo carries the 10x
`context/changes/` structure. The existing smoke only checks "a planted SQLi
appears in the output" — it cannot distinguish a *specific* finding from a
*generic* one.

## Desired End State

A reviewer runs the tool (CLI or GHA) and gets findings that are **specific and
non-generic** — each anchored on a file/line the PR actually changed, naming the
actual concern — with a clean diff yielding ~0 flagged findings (negative
control). The output contract F-02 shipped (stdout JSON + PR Markdown comment +
advisory exit) is unchanged; it now carries materially better signal.

## Key Decisions Made

| Decision                    | Choice                                                  | Why (1 sentence)                                                                                       | Source |
| --------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------ |
| Plan discovery              | Diff-driven + single-active fallback                    | "The current change" is what the diff touches — matches how a reviewer thinks; no env knob needed.     | Plan   |
| Verdict surfacing           | Narrative `overall_verdict` only; dimension grid host-side | Keeps the model on content, not grading bookkeeping; grid is deterministic host output.               | Plan   |
| Signal verification         | Targeted signal smoke + negative-control                | Catches the generic-style-linter failure mode directly — the one that kills the product.              | Plan   |
| Lenses vs dimensions        | Lenses = method; map to 7-dim enum at emit              | Model gets a structured thinking process; output stays the locked 7-dim schema. No schema change.     | Plan   |
| Prompt structure            | Single consolidated prompt, sectioned                   | Single source of truth, diffable, fits the existing `_SYSTEM_PROMPT` slot.                            | Plan   |
| Diff-scoping (user-added)   | Findings anchor on changed files only; tools deepen context on changed files | Kills the repo-wandering generic-noise failure mode; the core product differentiator.                 | User   |
| Scope boundary              | Analysis layer only; output contract unchanged          | Tightest scope on the existential risk; F-02's just-shipped renderer/stdout already works.            | Plan   |
| Schema changes              | None                                                    | `Finding`/`FindingsReport` stay exactly as F-01 locked them; avoids free-tier structured-output risk.  | Plan   |

## Scope

**In scope:**
- Full impl-review methodology system prompt (3 lenses → 7-dimension findings)
- Diff-scoping hard rule (anchor on changed files; tools deepen, don't discover)
- Diff-driven plan discovery module (replaces `plan=None`)
- Signal-quality smoke suite (targeted + negative-control + diff-scoping guard)
- `AGENTS.md` methodology provenance (resolves OQ#7)

**Out of scope:**
- Any change to the output contract (report node, stdout JSON, `render_comment`)
- Schema changes (no `lens` field, no dimension-grid field)
- Executing the reviewed project's test/lint/build commands (PRD Non-Goal)
- Per-lens parallel sub-nodes; LLM-as-judge; `--plan`/`PLAN_CHANGE_ID` config
- Merge blocking; secret/entropy scanner

## Architecture / Approach

Four sequential phases, attack-the-existential-risk-first:

```
Phase 1: Full methodology prompt + diff-scoping rule  (the core deliverable)
   │  rewrites _SYSTEM_PROMPT; plan-tolerant by construction
   ▼
Phase 2: Diff-driven plan discovery                    (unlocks the drift lens)
   │  new plan_loader.py + CLI wiring; diff-driven → single-active → None
   ▼
Phase 3: Signal-quality smoke suite                    (proves the hypothesis)
   │  targeted defects + negative control + diff-scoping guard
   ▼
Phase 4: Docs & sync                                   (AGENTS.md OQ#7, status)
```

No new model calls, no schema change, no graph-shape change. The single `checks`
node keeps the cached-prefix cost advantage (OpenRouter ~99% prompt-cache
discount amortizes the larger prompt across agent steps).

## Phases at a Glance

| Phase | What it delivers                                                | Key risk                                                                       |
| ----- | --------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| 1. Full methodology prompt | The sectioned 3-lens prompt + the diff-scoping hard rule | The prompt is long; ordering/emphasis tuning is text editing, not code.        |
| 2. Plan discovery          | `plan_loader.py` + CLI wiring (replaces `plan=None`)    | Ambiguous diffs / multiple active change dirs → must degrade cleanly to None. |
| 3. Signal-quality smoke    | Targeted + negative-control + diff-scoping-guard smokes | "Non-generic" is partly judgment; negative control must be genuinely clean.   |
| 4. Docs & sync             | `AGENTS.md` provenance + change.md stamp                | Docs-only; lowest risk.                                                        |

**Prerequisites:** F-01 (archived) + F-02 (this branch, all 6 phases done) — both
landed. The consumer repo `../target-o-meter` is the realistic test target and
carries the 10x `context/changes/` structure.

**Estimated effort:** ~4 sessions across 4 phases; Phase 3 is the longest
(fixture authoring + live-run iteration on signal quality).

## Open Risks & Assumptions

- **Signal quality is genuinely hard to verify without circularity.** The
  negative-control fixture must be clean enough that a good reviewer agrees
  there's nothing to flag — built from the *base* versions of existing fixtures
  to avoid inventing a "clean" snippet with a secret smell.
- **The methodology is plan-centric; the product is plan-tolerant.** The
  `/10x-impl-review-ci` reference assumes a plan and says "run the plan's test
  commands." Both adapt: plan checks skip when no plan (FR-006); MISSING-TEST /
  UNCOVERED-BEHAVIOR come from static/presence evidence (PRD Non-Goal), never
  execution.
- **Free-tier model looseness.** A substantially larger prompt is more surface
  for the free model to mis-handle. F-01's `ProviderStrategy(strict=True)` +
  host-side `model_validate` re-check are the backstop; if signal regresses, the
  prompt's section order/emphasis is the tuning knob (not the schema).
- **Plan discovery ambiguity.** A diff touching several change dirs, or a repo
  with multiple active changes, degrades to `None` (plan-tolerance) — the drift
  lens is skipped. Acceptable: better no plan than the wrong plan.

## Success Criteria (Summary)

- A reviewer reading the output sees **specific, file/line-anchored, actionable**
  findings on real PRs (not generic style noise).
- A **clean diff yields ~0 flagged findings** (negative-control smoke exits 0).
- No finding is anchored on a file the PR **did not change** (diff-scoping guard).
- `make check` + `make test` green; the new signal smoke set green under
  `make llm-test`; `AGENTS.md` records the methodology provenance.
