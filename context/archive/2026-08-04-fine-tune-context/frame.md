# Frame Brief: Fine-tune context handling

> Framing step before /10x-plan. This document captures what is *actually*
> at issue, separated from what was initially assumed.

## Reported Observation

A live run against `krkruk/target-o-meter#28` (a large refactoring PR) emitted
**0 findings**. The `checks` node exceeded its 120s `run_timeout` →
`NodeTimeoutError` → degraded to an empty report + advisory exit 0 → posted
nothing actionable. The operator runs a paid 1M-context model, so the context
window is not the constraint. Operator's own attribution: *"No findings are
likely associated with the timeout."*

## Initial Framing (preserved)

- **User's stated cause or approach**: The timeout is too low for a big PR; and
  separately, the context the model receives needs restructuring and the caps
  need raising, and we lack visibility into what the LLM returned.
- **User's proposed direction**: Ship four changes together — (1) raise
  `run_timeout` to ~5 min, (2) raise `MAX_DIFF_CHARS`/`_MAX_TOKENS`
  proportionally, (3) reorder context tiers (AGENTS.md → modified python files →
  optional `./context` files), (4) log the raw LLM object to stderr.
- **Pre-dispatch narrowing**: Leading concern = *"The empty report (timeout)"*.
  Context intent = *"Dismiss/trim context dirs"* (NOT "add modified-python-files
  tier" — the literal request #3 text was the opposite of the real intent; the
  `change.md` title was right).

## Dimension Map

The observation ("empty report on a big PR via timeout") could originate at any
of these dimensions:

1. **Diff size** — a large diff → more reasoning tokens → model runs past 120s.
   (Trimming context dirs would NOT fix this; raising the timeout/caps would.)
2. **Context prompt size (bloated context docs)** — context_loader reads EVERY
   active change's plan/frame/research + ALL foundation docs; on a repo with
   many changes this crowds/truncates. If the timeout is the model chewing a fat
   context, trimming dirs WOULD help.
3. **Token budget (output cap)** — `_MAX_TOKENS` too small → model stalls/
   retries → wall-clock grows. (Caps raise fixes; context-trim doesn't.)
4. **Agent iteration (tool round-trips)** — `ModelCallLimitMiddleware`
   `run_limit=12` + many `text_search` calls → many model calls → cumulative
   wall-clock > 120s. (Only timeout/paid-model helps; trim & caps don't.)

The user's initial framing (a bundled punch list) landed across all four. The
decisive split is **#1 vs #2**: is the timeout diff-driven (trim won't help) or
context-driven (trim *is* a real fix)? And **separately** — does the loader
actually pull irrelevant content (the "dismiss dirs" premise)?

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| **#1 Diff size drives the timeout** | Live log: `diff=105568 chars` vs `context=8040 chars` (ratio ~13x). Diff is re-sent in full on every one of up to 12 agent iterations (`nodes.py:257`), with **no prompt caching configured anywhere** in the repo (grep for `cach`/`prefix`/`cache_control` = 0 matches). The diff is the only input whose cap (100k, with boundary overshoot to 105k) is even in the same order of magnitude as the budget. | **STRONG** |
| **#2 Context size drives the timeout** | Context is hard-capped at 8000 (`context_loader.py:32`) and ran at 8040 in the live run — ~7.6% of the diff. Trimming it to zero saves ~8k against a ~105k diff re-sent every iteration. | **NONE** (for the timeout) |
| **#2′ Context loader pulls irrelevant content (the "dismiss dirs" premise)** | `context_loader.py:66` `for change_dir in sorted(changes_root.iterdir())` reads `plan.md`+`frame.md`+`research.md` for **EVERY** non-archived change dir, unconditionally — no filter to the current change. `load_context(repo_path)` takes only `repo_path` (`cli.py:65`); it is never told which change the PR is. Contrast: `plan_loader.load_plan(repo_path, diff)` IS diff/change-aware (`plan_loader.py:104-132`). The cap (`_cap`, positional hard-cut) does NOT protect any tier — AGENTS.md survives only by append order, and the PR's own change docs may be in the evicted tail while unrelated changes' docs occupy the prompt. | **STRONG** (a real, independent problem — but NOT a timeout driver) |
| **#3 Output token budget** | `_MAX_TOKENS=128000` already in the working tree (`provider.py:28`); the `_log_usage` WARNING (`nodes.py:291-301`) exists to flag ceiling approach. Generous; not the structural driver. | WEAK |
| **#4 Agent iteration amplifies cost** | `max_iterations=12` (`config.py:46`); each turn re-sends full diff + up to 20k/turn tool output (`tools/text_search.py:16`). Second-order amplifier on top of #1, not independent. | WEAK (amplifier, not origin) |

## Narrowing Signals

Decisive observations that split the bundled framing into two independent
problems:

- **The live log itself** (`diff=105568` vs `context=8040`) proves the timeout is
  diff-driven, not context-driven. Trimming context dirs cannot dent the
  timeout — context is already a rounding-error fraction of the prompt. This
  rules out #2-as-timeout-driver and confirms #1.
- **The pre-dispatch answer** (*"dismiss/trim dirs"* as the real intent, not
  *"add modified-python-files"*) revealed that request #3's literal text was the
  opposite of the operator's intent. The change title was right; the inline
  request was misframed.
- **The loader code** (`context_loader.py:66`, unconditional multi-change read;
  blind `load_context(repo_path)` at `cli.py:65`) confirms the "dismiss dirs"
  premise is a **genuine relevance problem** — but a relevance problem, not a
  timeout problem. Two different problems, two different fixes.

Step 3 evidence was conclusive (STRONG on #1, STRONG on #2′, NONE on the rest).
Skipping Step 4 questioning.

## Cross-System Convention

- **Timeout → raise**: consistent with `graph-bugfixing/plan.md:326-329`
  ("raising tokens is fine *because* the timeout caps latency" — so the inverse,
  raising the timeout to accommodate a paid 1M model, is the same lever from the
  other end). 300s sits at the edge of the `prd.md:96-98` ~5-min NFR.
- **Caps → raise**: the working tree already did this (`_MAX_TOKENS=128000`,
  `MAX_DIFF_CHARS=100000`); consistent with prior sizing decisions.
- **Context-trim → mirror `plan_loader`**: the cleanest fix for the relevance
  problem is to thread the diff (or the already-discovered `change_id` from
  `plan_loader._discover_change_id`) into `load_context`, so it loads only the
  *current* change's `plan/frame/research` — not a hand-maintained dismissal
  list. A static dismissal list needs re-tuning every time a change is archived;
  a diff-driven filter self-updates. This is the established pattern in the
  sibling loader.

## Reframed (or Confirmed) Problem Statement

> **The actual problem to plan around is**: this is **two independent changes
> bundled as one**, with the proposed solutions partially crossed.

**Problem A (primary, per the operator's own narrowing):** the reviewer emits 0
findings on large PRs because the `checks` node times out. The timeout is
diff-driven (~105k-char diff, re-sent every iteration, no caching). The fix is
raising the timeout (120s→~300s, at the edge of the ~5-min NFR — flag the
headroom tradeoff), confirming the already-raised caps, and adding visibility
into what the LLM returned before the timeout. **Trimming context dirs does not
help this problem** — context is ~8k, a rounding error vs the diff.

**Problem B (real, but secondary — the "dismiss dirs" intent):** `load_context`
reads *every* active change's `plan/frame/research` unconditionally
(`context_loader.py:66`), is blind to the current PR (`cli.py:65`), and the cap
can evict the *relevant* change's docs while keeping irrelevant ones. This is a
**relevance** problem, not a latency problem. The fix is to make `load_context`
change-aware (thread the diff/`change_id` in, mirroring `plan_loader`), NOT to
add a "modified-python-files tier" (that literal request was the opposite of the
intent, and would re-open the closed "no source preload" decision at
`change-input-pipeline/plan.md:86-88`).

**What changes for the plan:** keep requests #1 (timeout), #2 (caps — already in
working tree), and #4 (stderr debug logging — DEBUG-gated + redacted) as one
plan addressing Problem A. Split request #3 into its own scope addressing
Problem B, with the mechanic corrected from "add modified-python-files tier" to
"make context_loader change-aware (diff-driven filter), mirroring plan_loader."
The raw-LLM-object logging (#4) is the highest leakage risk and must be
DEBUG-gated + redacted (`prd.md:44`; `tests/test_cli.py:242-265`).

## Confidence

- **HIGH** — strong file:line evidence on both problems; the live log numbers
  (diff 105k vs context 8k) are dispositive for the timeout being diff-driven;
  the loader code (`context_loader.py:66`, `cli.py:65`) is dispositive for the
  relevance problem; the operator's own narrowing confirmed the two-problem
  split.

## What Changes for /10x-plan

Plan **two scopes**, not one:

1. **Make the reviewer finish on large PRs** (Problem A): raise `run_timeout`
   (`config.py:47`, `tests/test_config.py:37`), confirm/land the working-tree
   caps (`provider.py:28`, `diff.py:36`), add DEBUG-gated redacted stderr logging
   of the LLM result/usage on the success path AND a probe of whatever is
   reachable on the `NodeTimeoutError` path (`graph.py:78`) — the timeout path
   is the actual gap, since the partial result never reaches `_log_usage`
   (`nodes.py:272`). Expect to update `tests/test_cli.py:242-265` for the
   logging.

2. **Make context_loader change-aware** (Problem B): thread the diff
   (or `plan_loader`'s discovered `change_id`) into `load_context` so it loads
   only the current change's `plan/frame/research`, mirroring `plan_loader`. Drop
   the "modified-python-files tier" from scope entirely. Update
   `tests/test_context_loader.py:31-45` (ordering) and the multi-change-read
   behavior. Consider whether to do this as a second change folder to keep the
   two problems cleanly separated.

## References

- Source files:
  - `reviewer-target-o-meter/src/reviewer_target_o_meter/config.py:47` (`run_timeout=120`)
  - `reviewer-target-o-meter/src/reviewer_target_o_meter/graph.py:42,78-92` (timeout policy + degrade)
  - `reviewer-target-o-meter/src/reviewer_target_o_meter/provider.py:28` (`_MAX_TOKENS=128000`, working tree)
  - `reviewer-target-o-meter/src/reviewer_target_o_meter/diff.py:36,125-133` (`MAX_DIFF_CHARS=100000` working tree + boundary-cap)
  - `reviewer-target-o-meter/src/reviewer_target_o_meter/context_loader.py:32,55-70,98-103` (cap + unconditional multi-change read + positional `_cap`)
  - `reviewer-target-o-meter/src/reviewer_target_o_meter/cli.py:65` (`load_context(repo_path)` — blind)
  - `reviewer-target-o-meter/src/reviewer_target_o_meter/plan_loader.py:63,104-132` (the diff-aware contrast to mirror)
  - `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py:236-273,278-306,309-343` (prompt assembly, `_log_usage`, redacted-probe precedent)
- Related research: `context/changes/fine-tune-context/research.md`
- Prior decisions:
  - `context/foundation/prd.md:44,96-98` (no-leakage guardrail; ~5-min NFR)
  - `context/archive/2026-08-01-agent-runtime-finding-schema/research.md:136,316-319` (why 120s; reasoning = debug-only)
  - `context/archive/2026-08-03-change-input-pipeline/plan.md:86-88,229-251` (no-source-preload decision; context_loader scope locked)
  - `context/archive/2026-08-04-graph-bugfixing/plan.md:326-329,369` (timeout is the binding latency guard; raised `_MAX_TOKENS` made the model reason past 120s)
  - `context/archive/2026-08-04-prod-logging-markdown-preview/plan.md:83-87,251,355-357` (logging is metadata-only; `LOG_LEVEL` is the verbosity knob)
- Investigation: parallel Explore agents (timeout cost-driver trace; context-loader multi-change behavior).
