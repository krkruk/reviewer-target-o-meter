# Make the Reviewer Finish on Large PRs — Plan Brief

> Full plan: `context/changes/fine-tune-context/plan.md`
> Frame brief: `context/changes/fine-tune-context/frame.md`
> Research: `context/changes/fine-tune-context/research.md`

## What & Why

The reviewer emits **0 findings** on large refactoring PRs because the `checks`
node hits its 120s `run_timeout`, degrades to an empty report, and posts nothing
actionable. The trigger was `krkruk/target-o-meter#28` — a major refactor that
timed out and posted 0 findings despite a paid 1M-context model.

> **Reframed problem (from frame.md):** this is a **diff-driven** timeout, not a
> context-driven one. The live log showed `diff=105568 chars` vs
> `context=8040 chars` (13× ratio), with the full diff re-sent on every agent
> iteration and **no prompt caching** configured. Trimming context dirs (the
> change's original title) cannot fix this — context is a rounding error. The
> real fix requires knowing *which* dimension (input size, iteration count,
> reasoning depth, tool-call explosion) dominates wall-clock on a big PR — which
> is why this plan is **diagnose-first**.

## Starting Point

Today: `run_timeout=120s`, `max_iterations=12`, `MAX_DIFF_CHARS=100000`
(working tree; committed 45000), `_MAX_TOKENS=128000` (working tree; committed
60000). On timeout, `NodeTimeoutError` is caught in `arun_review`
(`graph.py:78-92`) → empty report + exit 0. The success path logs token usage
(`_log_usage`, `nodes.py:272`); the **timeout path logs nothing useful** — the
partial result never reaches `_log_usage`. That visibility gap is why we can't
just tune knobs blind.

## Desired End State

Running the reviewer against PR #28 (or any large refactor) **produces real
findings** (not 0) within budget — because the actual bottleneck was measured
and fixed, not papered over with a timeout raise. The final knob values are
justified by evidence in `diagnosis.md`, and the temporary debug
instrumentation is gone (`test_cli.py:242-265` metadata-only invariant green
again).

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Plan approach | Diagnose-first (instrument → measure → fix → strip) | Blindly raising knobs risks masking the real bottleneck; PR #28 is the reproducible test case. | Plan (operator directive) |
| `run_timeout` starting value | 300s (5 min) | Operator's literal ask; sits at the edge of the ~5-min NFR (`prd.md:96-98`). | Plan |
| `max_iterations` starting value | 12 → 8 | Bounds worst-case wall-clock by cutting full-diff re-sends; the second lever in the starting hypothesis. | Plan |
| `MAX_DIFF_CHARS` | 200000 | Fits PR #28's 166k raw untruncated; ~50k tokens, well within the 1M window. | Plan |
| `_MAX_TOKENS` | 128000 (already in working tree) | Generous reasoning+JSON budget; raisable per `graph-bugfixing` prior. | Research |
| Debug log content | Full raw dump, DEBUG-gated | Operator's explicit choice for diagnosis; leakage bounded by DEBUG-gate (off in CI) + ephemerality (Phase 4 removes it). | Plan |
| Problem B (change-aware `load_context`) | Deferred to a follow-up change | Frame proved it's a relevance problem, not the timeout driver; trimming wouldn't have saved PR #28. | Frame |
| "Modified-python-files tier" | Dropped | Opposite of operator's real intent ("dismiss/trim"); re-opens a closed decision. | Frame |

## Scope

**In scope:**
- Temporary DEBUG-gated instrumentation on the success path AND the timeout path
  (the real visibility gap).
- Starting-hypothesis knob changes: `run_timeout`→300, `max_iterations`→8,
  `MAX_DIFF_CHARS`→200000.
- Live diagnosis run against PR #28, producing `diagnosis.md`.
- Diagnosis-driven fix + confirmation that real findings are produced.
- Instrumentation removal + final knob landing + docs sync.

**Out of scope:**
- Problem B: change-aware `load_context` (separate change folder).
- "Modified-python-files" context tier (dropped — wrong direction).
- Prompt caching (provider-side; noted as a future lever).
- Model change (the 1M model is not the constraint being fixed).
- Permanent DEBUG raw-dump logging (temporary by design).

## Architecture / Approach

Diagnose-first, four phases. The instrumentation is a means to diagnosis, not an
end. The DEBUG gate keys off the existing `LOG_LEVEL` knob (`_util.py:31-57`),
so it's off in CI at default INFO and only enabled for the diagnosis run.

```
Phase 1: instrument (DEBUG-gated) + set hypothesis knobs → make check/test green
Phase 2: run PR #28 with LOG_LEVEL=DEBUG → write diagnosis.md (NO code)
Phase 3: apply diagnosis-prescribed fix → confirm >0 real findings (iterate ≤3×)
Phase 4: strip instrumentation + land final knobs + sync docs → invariant green
```

Phases 2–3 require a live OpenRouter run (`OPENROUTER_API_KEY` + `GITHUB_TOKEN`)
and are manual-verification phases — `make test` alone cannot validate them.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Instrument + baseline knobs | DEBUG logging on success+timeout paths; hypothesis knobs applied; tests green | DEBUG dump leaks at INFO if the gate is wrong (mitigated: level-gated, test_cli.py:242-265 stays green) |
| 2. Measure + diagnose | `diagnosis.md` naming the real bottleneck with evidence | Diagnosis inconclusive after 2–3 runs (mitigated: add instrumentation, re-measure) |
| 3. Apply fix + confirm findings | PR #28 produces >0 real findings | Fix doesn't produce findings in ≤3 iterations (mitigated: redo Phase 2 with deeper instrumentation) |
| 4. Remove instrumentation + finalize | Clean production code, final knobs landed, docs synced | Forgetting a `TEMPORARY` block (mitigated: `grep -rn "TEMPORARY"` in success criteria) |

**Prerequisites:** `OPENROUTER_API_KEY` set; `GITHUB_TOKEN` available
(`gh auth token`); a local checkout of the reviewed repo at
`../../target-o-meter/` (operator's path; adjust if needed); PR #28 accessible
in `krkruk/target-o-meter`.

**Estimated effort:** ~2–3 sessions — Phase 1 is a focused code session; Phases
2–3 are live-run iterations (each run is up to 5 min + analysis); Phase 4 is a
short cleanup. The live-run phases dominate the calendar time, not the code time.

## Open Risks & Assumptions

- **The diagnosis might point at a fix outside the knob space** — e.g. a prompt
  change, a tool-output trimming need, or a real code bug. The plan allows this
  (Phase 3 is open-ended) but it expands scope. If the fix is large, consider
  splitting it into its own change.
- **PR #28 may genuinely have no findings.** The success criterion is ">0 real
  findings" — if the refactor is genuinely clean, validate against a substitute
  large PR instead. Documented in Phase 3.
- **`max_iterations=8` may reduce finding depth.** It's a hypothesis to test in
  Phase 2; if the diagnosis shows the model needs more iterations to trace
  flows, raise it back and find wall-clock savings elsewhere.
- **The ~5-min NFR (`prd.md:96-98`) leaves no margin at 300s** for diff/context
  loading + posting outside the checks node. If wall-clock is firm, the final
  landed value may need to come back down (Phase 4 lands what the measurement
  justifies, not necessarily 300).

## Success Criteria (Summary)

- PR #28 (or a substitute large PR) produces **>0 real findings** with valid
  anchors and severities (AGENTS.md §e checklist), within budget.
- `diagnosis.md` records the measured bottleneck and justifies every final knob
  value with evidence.
- `make check` + `make test` green; `grep -rn "TEMPORARY" src/ tests/` empty;
  `test_cli.py:242-265` (metadata-only invariant) green without gating.
- README knob values match the code.
