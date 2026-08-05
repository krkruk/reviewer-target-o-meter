---
date: 2026-08-04T23:57:38+02:00
researcher: Krzysztof Kruk
git_commit: cfbe0fa73e82e7907ec52cb9d497fbd115891f07
branch: feature/fine-tune-context
repository: reviewer-target-o-meter
topic: "Fine-tune context handling: raise timeout/caps, reorder context tiers, add raw-LLM-response stderr debug logging"
tags: [research, codebase, context-loader, diff-cap, max-tokens, run-timeout, debug-logging, checks-node]
status: complete
last_updated: 2026-08-04
last_updated_by: Krzysztof Kruk
---

# Research: Fine-tune context handling (timeout / caps / ordering / stderr debug)

**Date**: 2026-08-04T23:57:38+02:00
**Researcher**: Krzysztof Kruk
**Git Commit**: cfbe0fa73e82e7907ec52cb9d497fbd115891f07
**Branch**: feature/fine-tune-context
**Repository**: reviewer-target-o-meter

## Research Question

A live run against `krkruk/target-o-meter#28` (a large refactoring PR) hit the
`checks` node's 120s `run_timeout`, degraded to an empty report (exit 0), and
posted nothing actionable. The operator runs a paid 1M-context model, so the
context window is not the binding constraint. Four changes are requested:

1. **Raise `run_timeout`** from 120s to ~5 minutes (300s).
2. **Raise the diff/token caps proportionally** — `_MAX_TOKENS` to 128k,
   `MAX_DIFF_CHARS` scaled up to match (1M token model).
3. **Reorder/scope the context loader**: AGENTS.md always first (mandatory),
   then modified Python files, then (optionally, if cap not reached) any
   modified files under `./context`.
4. **Log the raw object received from the LLM to stderr** for debugging.

(The `PR_NUMBER=28 …` debug command itself is operator-only and intentionally
not captured in any artifact.)

## Summary

All four changes are feasible and **mostly unblocked**, but each carries a
load-bearing caveat the plan must address explicitly:

- **Timeout → 300s:** Allowed. 300s = the ~5-min wall-clock NFR
  (`prd.md:96-98`); 120s was a conservative pick *inside* that budget. Caveat:
  300s consumes the *entire* NFR headroom and leaves no margin for diff/context
  loading + GitHub posting on top of the `checks` node. One test pins the literal
  (`tests/test_config.py:37`).
- **Caps:** The working tree has **already** drifted up to `MAX_DIFF_CHARS=100000`
  (`diff.py:36`) and `_MAX_TOKENS=128000` (`provider.py:28`) — uncommitted. These
  are raisable; no prior decision blocks them (cost is latency-bound, not
  token-bound, per `graph-bugfixing/plan.md:326-329`). `_MAX_TOKENS=128000` is
  already exactly what was requested; `MAX_DIFF_CHARS` may want a further bump
  proportional to the new budget. No test references these literals.
- **Context reorder:** AGENTS.md-first is *already* the documented decision and
  the live behavior (`context_loader.py:55-70`). The new "modified Python files"
  tier **re-opens a knowingly-closed decision** — `change-input-pipeline/plan.md:86-88`
  explicitly decided NOT to preload source (the diff already carries changed
  lines; the agent's `text_search`/`structural_search` tools pull full files on
  demand). The plan must justify what *new* signal pre-loaded modified files add
  beyond the diff + tools, and handle the cap crowding (`MAX_CONTEXT_CHARS=8000`).
  Three tests pin the current ordering/truncation and will need updates.
- **Raw-response stderr logging:** Not blocked, but a strong, repeated
  "never echo secrets / never log input bodies" guardrail applies
  (`AGENTS.md:106,134-135`; `prd.md:44`; `prod-logging-markdown-preview/plan.md:83-87`).
  The raw `ainvoke` result **contains the `HumanMessage` with the diff+context
  spliced in**, so a naive dump leaks source bodies onto stderr and breaks
  `tests/test_cli.py:242-265`. Must be DEBUG-gated + redacted (headers, absolute
  paths), mirroring the existing failure-path probe (`nodes.py:310`). This is the
  single highest-risk change.

The `change.md` title/notes ("Fine-tune context directory dismissal") do **not**
yet reflect any of these four knobs — worth aligning before planning.

## Detailed Findings

### 1. `run_timeout` (120s) — the ~5-min NFR enforcer

The timeout is a deliberate cost/latency control (the "OQ#2 mechanism"), not
arbitrary. The binding constraint is the PRD NFR.

- **`config.py:47`** — `run_timeout: ClassVar[int] = 120  # seconds` (ClassVar,
  not env-driven — changing it is a one-line code edit; `Config.from_env` does
  not read it from the environment).
- **`graph.py:42`** — applied via `TimeoutPolicy(run_timeout=config.run_timeout)`
  on the `checks` node only (the only OpenRouter-calling node).
- **`graph.py:78-92`** — `NodeTimeoutError` is caught in `arun_review` (OUTSIDE
  the checks node body) and degrades to an empty report + advisory exit 0. This
  is exactly the path the live run hit: `WARNING: graph degraded — node 'checks'
  exceeded run timeout …`.
- **`prd.md:96-98`** — the NFR: "a typical review completes within ~5 minutes
  wall-clock". 300s = 5 min exactly → **at the edge** of the stated bound, not a
  divergence. The prior rationale (`agent-runtime-finding-schema/research.md:136,324-325,573`)
  consistently names `prd.md:98` as the binding constraint.

**Caveat the plan must record:** 120s was a conservative 2-min pick *inside* a
5-min budget. At 300s, the `checks` node alone can consume the entire NFR,
leaving zero margin for `compute_diff` + `load_context` + `load_plan` + GitHub
posting. The live log shows `diff computed` + `context loaded` + `plan
discovered` breadcrumbs fire *before* `graph start`, so they are outside the
node timeout but inside the wall-clock. If the operator's 5-min target is firm,
consider 240s (4 min) for the node to leave headroom; if the target is soft,
300s is fine. (The operator said "say 5 minutes," so 300s is the requested value
— flag the headroom tradeoff, don't override.)

**Historical note:** the timeout became the *binding* latency guard after
`graph-bugfixing` raised `_MAX_TOKENS` and the reasoning model started reasoning
past 120s (`graph-bugfixing/plan.md:369`). So today, a too-low timeout *masks*
real findings on large diffs (the exact symptom reported). Raising it is the
direct fix.

### 2. `_MAX_TOKENS` and `MAX_DIFF_CHARS` — already drifted up in the working tree

The working tree (uncommitted) **already contains** the requested `128000` for
`_MAX_TOKENS` and `100000` for `MAX_DIFF_CHARS`. The committed HEAD values are
`60000` / `45000`.

- **`provider.py:28`** — `_MAX_TOKENS = 128000` (working tree; committed = 60000).
  Applied at `provider.py:44` as `llm.max_tokens = _MAX_TOKENS` after
  construction. The comment at `provider.py:20-27` documents the raise rationale
  (reasoning tokens count against the completion budget; too-tight →
  `choices: None` crash).
- **`diff.py:36`** — `MAX_DIFF_CHARS = 100000` (working tree; committed = 45000).
  Applied by `_cap` (`diff.py:125-133`), which truncates at the next
  `diff --git` boundary AFTER the budget (so the actual cap can overshoot up to
  one file's worth — load-bearing, documented at `diff.py:8-11`).

**No prior decision blocks raising these further.** The established reasoning
(`graph-bugfixing/plan.md:326-329`): raising tokens is fine *because* the
`run_timeout` caps the latency blowup — the model is free/paid-flat, so cost is
not the constraint. The model-side `max_completion_tokens` cap is 384k
(`agent-runtime-finding-schema/research.md:317`), well above 128k. The 1M
context window claim is consistent with `research.md:283,522`.

**Proportional sizing (request #1 says "increase the number of characters
proportionally"):** the relationship is loose — `MAX_DIFF_CHARS` sizes the
*input* (prompt), `_MAX_TOKENS` sizes the *output* (reasoning + JSON). They are
"distinct" by explicit decision (`graph-bugfixing/plan.md:385`). If the intent
is "1M window → use more of it," the lever is `MAX_DIFF_CHARS` (input), not
`_MAX_TOKENS` (output, already generous at 128k). A reasonable proportional read:
current `MAX_DIFF_CHARS=100000` ≈ 25k tokens (≈4 chars/token); a 1M-window model
could absorb ~400k chars of input with room for the rest — but the boundary-cap
overshoot and the agent's own tool-fetching mean a huge diff cap is wasteful.
The plan should pick a concrete number with rationale (e.g. 200k–400k) rather
than leaving it open.

**`MAX_CONTEXT_CHARS=8000`** (`context_loader.py:32`) is the *third* cap and is
NOT in the working-tree diff — if the context reorder (§3) adds modified-file
content, this cap will crowd out foundation/change docs unless raised too.

### 3. Context loader reorder — AGENTS.md-first is already done; "modified files" re-opens a closed decision

This is the most nuanced of the four. Current behavior already matches part of
the request; the rest diverges from a documented prior decision.

**Already true (AGENTS.md first, mandatory-in-practice):**
- `context_loader.py:55-70` reads in exactly: (1) `<repo>/AGENTS.md`, (2)
  `context/foundation/*.md` sorted, (3) `context/changes/*/{plan,frame,research}.md`
  (archive excluded). AGENTS.md is appended first; if present it leads the
  joined string. `change-input-pipeline/plan.md:229-251` locks this as the
  "highest signal first" priority order.

**Diverges from request (no "modified files" tier):** the request inserts a new
tier "modified Python files" between AGENTS.md and the context docs. This
**re-opens a knowingly-closed decision**:
- `change-input-pipeline/plan.md:86-88` — "No pre-loading of source code into
  context. Source is fetched on demand by the agent's `text_search`/
  `structural_search` tools. The loader only reads AGENTS.md + foundation docs +
  the current change docs."
- The diff *already* carries changed-file content (it's a unified diff, computed
  with `--function-context` at `diff.py:71` so each hunk shows the WHOLE
  enclosing function). And the agent's tools (`text_search`, `structural_search`)
  pull full files on demand during the review.

**What the plan must justify for the "modified files" tier:** what *new* signal
does pre-loaded modified-file content add that the diff + on-demand tools don't
already provide? Possible answers (the plan should pick one and validate):
- The diff hunks show changes but not the *full* surrounding file when
  `--function-context` doesn't capture it (e.g. module-level code, class bodies);
  pre-loading gives the agent the complete changed file upfront.
- It removes a round-trip: the agent doesn't have to spend a tool call to read a
  file it will certainly need. This is a *latency* argument, which aligns with
  the timeout pressure that motivated this whole change.

**Overlap / scoping risk:** loading *all* modified files can blow the context
cap fast on a big refactor (PR #28 is "a major refactoring effort"). The request
says "first AGENTS.md … then modified python files, then (optionally if the cap
is not reached) any modified files in `./context`." So the intended precedence is
clear; the open question is whether `./context` modified files are even useful
given the loader already reads `context/foundation` + `context/changes` (see §3.1
below — this is likely *the* point of the change, given the title "context
directory dismissal").

**Cap interaction:** adding modified-file content under the existing
`MAX_CONTEXT_CHARS=8000` will evict the foundation/change docs that currently
fit. The plan must either raise this cap (proportional to the §2 raises) or
accept that on big PRs the context docs get truncated — which may be fine if
AGENTS.md is the load-bearing piece.

**Title alignment:** the `change.md` title is "Fine-tune context directory
*dismissal*" and the note says "properly dismissing certain directories if
necessary" — this suggests the *real* intent of request #3 may be about
*excluding* (dismissing) some `./context` subdirectories (e.g. `context/archive/`
is already excluded; maybe `context/changes/<other-changes>/` should be too, or
the `./context` modified-files tier is about pulling in *only* the changed
context docs). The plan should reconcile the literal request ("modified python
files" tier) with the change title ("directory dismissal") before implementing —
they point at different mechanics. **Recommend `/10x-frame` or a clarifying
question on this point before `/10x-plan`.**

### 3.1. What "dismiss certain directories" might mean concretely

The change title ("directory dismissal") + note ("properly dismissing certain
directories if necessary") is a different framing than the literal request #3
("add a modified-python-files tier"). Candidates for "directories to dismiss":

- `context/archive/` — **already excluded** (`context_loader.py:65-70` walks
  `context/changes/` only; archive is never read). Not it.
- `context/changes/<other-change-id>/` — currently ALL non-archived change dirs
  are read (`context_loader.py:66` `for change_dir in sorted(changes_root.iterdir())`).
  On a multi-change repo this loads every active change's plan/frame/research,
  which can be large and mostly irrelevant to the reviewed PR. "Dismiss" could
  mean: load only the change matching the reviewed PR (via `PR_NUMBER` →
  change-id mapping), or load none if the reviewed repo *is* this tool (self-
  review) vs a consumer repo.
- `context/changes/<change-id>/research.md`, `frame.md` — maybe only `plan.md`
  is review-relevant; research/frame are process artifacts. But
  `change-input-pipeline/plan.md:242` lists all three as in-scope.

This is genuinely ambiguous and the operator should clarify intent. The literal
request (modified-files tier) and the title (directory dismissal) are not the
same change.

### 4. Raw-LLM-response stderr logging — feasible but the highest leakage risk

The request: "log into stderr the object you receive from the LLM so we can
debug the issue."

**Where the object lives:**
- `agent/nodes.py:257` — `result = await agent.ainvoke({"messages": messages})`
  is the raw return. On success it flows to `_log_usage(result)` (`:272`) and
  `_extract_findings(result)` (`:273`). On exception, `_extract_response_shape(exc)`
  (`:263`, helper at `:309-343`) already probes `getattr(exc, "response", ...)`
  for `choices`/`finish_reason`/`usage` — but only structural keys, with an
  explicit redaction guard.

**Why a naive dump is dangerous (the load-bearing gotcha):**
- The `result` dict's `messages` list **contains the `HumanMessage` built at
  `nodes.py:240-248`** — which has the diff + context + plan spliced in as
  `content`. Dumping `result` to stderr echoes the full diff/context/source
  bodies onto stderr.
- `tests/test_cli.py:242-265` (`test_cli_log_lines_are_metadata_only`) pins the
  invariant: logs carry sizes/counts/refs, never bodies. It injects
  `secret_diff_body`/`secret_context_body` and asserts neither appears in the
  log region. A raw dump **will fail this test**.
- Guardrail priors: `AGENTS.md:106` ("key read at runtime only, never echoed"),
  `AGENTS.md:134-135` (no secrets/source spans leaked), `prd.md:44` (no
  secret/source leakage beyond the analysis call),
  `prod-logging-markdown-preview/plan.md:83-87,251` (logging is metadata-only:
  no input bodies), `agent-runtime-finding-schema/research.md:318-319`
  (reasoning content is debug-only, never in posted output).

**How to do it safely (precedent = the existing failure-path probe):**
- `graph-bugfixing/plan.md:223-224,322` set the pattern: raw-response shape IS
  logged on the failure path, but "Confirm no `OPENROUTER_API_KEY` or absolute
  host path leaks into the logged response_shape." The live helper
  (`nodes.py:309-343`) reads only `choices`/`finish_reason`/`usage` and never
  touches headers/bodies.
- **Recommend for the success path:** gate the dump behind `LOG_LEVEL=DEBUG`
  (the established verbosity knob, `prod-logging-markdown-preview/plan.md:355-357`;
  default INFO so prod CI isn't flooded), and dump a *redacted* projection —
  e.g. `usage_metadata`, `response_metadata` (`finish_reason`), tool-call
  counts, message *roles/lengths* — NOT message `content`. If the operator
  truly needs the full raw object for one debug session, a DEBUG dump of the
  parsed `structured_response` (the FindingsReport) is safe (it's the output
  contract, already posted publicly); dumping the raw `messages` content is the
  part that must be redacted.
- The operator's intent ("debug the issue" = the empty-report timeout) is served
  by: the existing `_log_usage` breadcrumb (already fires on success;
  `nodes.py:278-306`) + the existing `_extract_response_shape` on failure. The
  gap is the *timeout* path: `NodeTimeoutError` is raised in `graph.py:78`
  *outside* the checks node, so the partial `result` never reaches `_log_usage`.
  The highest-value debug addition may be capturing whatever partial
  `usage`/`finish_reason` is reachable from the `NodeTimeoutError` (or from the
  cancelled agent state), rather than a blanket raw dump.

**Net:** doable, but DEBUG-gate + redact, expect to update
`tests/test_cli.py:242-265`, and prefer the targeted "what did we get before the
timeout" signal over a full object dump.

## Code References

- `reviewer-target-o-meter/src/reviewer_target_o_meter/config.py:47` — `run_timeout: ClassVar[int] = 120` (the knob to raise; ClassVar, not env-driven).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/graph.py:42` — `TimeoutPolicy(run_timeout=config.run_timeout)` on `checks`.
- `reviewer-target-o-meter/src/reviewer_target_o_meter/graph.py:78-92` — `NodeTimeoutError` catch → empty report + advisory exit (the degrade path the live run hit).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/provider.py:28` — `_MAX_TOKENS = 128000` (working tree; committed 60000).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/provider.py:44` — `llm.max_tokens = _MAX_TOKENS` (applied post-construction).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/diff.py:36` — `MAX_DIFF_CHARS = 100000` (working tree; committed 45000).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/diff.py:71` — `--function-context` diff (hunks show the whole enclosing function).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/diff.py:125-133` — `_cap` truncates at the next `diff --git` boundary (may overshoot one file).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/context_loader.py:32` — `MAX_CONTEXT_CHARS = 8_000` (the third cap; NOT yet raised; crowding risk if modified-file content added).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/context_loader.py:55-70` — current AGENTS.md → foundation → changes ordering (already AGENTS-first).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/context_loader.py:65-70` — `context/archive/` exclusion (already in place).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py:240-248` — the `HumanMessage` with diff+context+plan spliced into `content` (the leakage source if dumped raw).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py:257-273` — `agent.ainvoke` → `_log_usage` → `_extract_findings` (the success path; where a debug log would hook in).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py:278-306` — `_log_usage` (existing success-path breadcrumb; already emits input/output/total tokens + finish_reason).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py:309-343` — `_extract_response_shape` (the failure-path redacted-raw-response probe — the precedent for safe raw logging).
- `reviewer-target-o-meter/src/reviewer_target_o_meter/_util.py:31-57` — `configure_logging` (single stderr handler; `LOG_LEVEL` applied here — the gate for a DEBUG dump).

### Test surface (must-touch for this change)

- `reviewer-target-o-meter/tests/test_config.py:37` — `assert Config.run_timeout == 120` (pins the literal; **update to new value**).
- `reviewer-target-o-meter/tests/test_graph.py:343-368` — timeout-degrade behavior test; the `120.001`/`120.0` are throwaway constructor args, not the config value (safe; narrative comment at `:347` worth updating).
- `reviewer-target-o-meter/tests/test_context_loader.py:31-45` — `test_loads_agents_foundation_and_change_in_priority_order` pins AGENTS→foundation→change order; **rewrite for new tiers**.
- `reviewer-target-o-meter/tests/test_context_loader.py:92-100` — oversize AGENTS.md IS truncated; **conflicts** with any "AGENTS never truncated" semantics (decide semantics, then update).
- `reviewer-target-o-meter/tests/test_context_loader.py:48-57,63-71,77-86,106-128` — sibling ordering/exclusion/truncation tests (review for new-tier compatibility).
- `reviewer-target-o-meter/tests/test_cli.py:242-265` — `test_cli_log_lines_are_metadata_only` — **the key guard**; raw-result dump leaks diff/context bodies → **will fail** unless redacted/gated.
- `reviewer-target-o-meter/tests/test_diff.py:184-192`, `tests/test_provider.py:25-42` — cap/value tests; all derive from the constants, **no literal pins** (safe).
- No test references `_MAX_TOKENS`, `max_tokens`, `_log_usage`, or checks-node stderr content directly (these are uncovered — the plan may add coverage).

## Architecture Insights

- **Three independent caps, one latency guard.** `MAX_DIFF_CHARS` (input/diff),
  `MAX_CONTEXT_CHARS` (input/context), `_MAX_TOKENS` (output/reasoning+JSON) are
  "distinct" by decision (`graph-bugfixing/plan.md:385`); `run_timeout` is the
  single binding latency guard over all of them. Raising any input cap increases
  prompt size (cached-prompt discount amortizes it per `README.md:114-117`) but
  the latency blowup is capped by the timeout.
- **Degrade-on-timeout masks findings on large diffs.** The reported symptom
  (empty report on PR #28) is the timeout degrade firing, not a model failure.
  The fix is raising the timeout (§1) and/or giving the model fewer/more-focused
  input tokens (§3) so it finishes within the bound.
- **Context loader is a plain function, not a node.** `load_context` runs in the
  CLI (`cli.py:65`) *before* the graph; its output is spliced into the `checks`
  prompt at `nodes.py:241-242`. Reordering tiers is a localized change to
  `context_loader.py` only — no graph/state changes.
- **The diff already uses `--function-context`.** So changed functions are shown
  whole in the diff; the "modified Python files" tier adds value mainly for
  module-level / cross-function / large-file context the hunks don't capture.

## Historical Context (from prior changes)

- `context/foundation/prd.md:44` — no-leakage guardrail (secret/source never persists beyond the analysis call).
- `context/foundation/prd.md:96-98` — the ~5-min wall-clock NFR (300s sits at its edge).
- `context/foundation/prd.md:128` + `context/foundation/roadmap.md:121` — OQ#2: the per-review cost ceiling is the recursion/step/timeout trio.
- `context/archive/2026-08-01-agent-runtime-finding-schema/research.md:136,316-319,324-325,573` — why `run_timeout=120` (the ~5-min NFR enforcer); reasoning tokens count against `max_completion_tokens` (cap 384k); reasoning content = debug-only, never in posted output.
- `context/archive/2026-08-01-agent-runtime-finding-schema/plan.md:241,602-603` — `run_timeout=120` locked as the ~5-min NFR enforcer.
- `context/archive/2026-08-03-change-input-pipeline/plan.md:86-88,117,164,229-251` — context_loader scope/order locked (AGENTS.md → foundation → changes; **explicitly NO source preload**); `MAX_DIFF_CHARS=20000` originally.
- `context/archive/2026-08-04-graph-bugfixing/plan.md:62-66,79-82,107-125,223-224,322,326-329,365,369,385` — `_MAX_TOKENS` raise rationale + live tuning trail (8192→…→60000); `MAX_DIFF_CHARS` → 45000; raw-response logging on failure path with explicit redaction; `run_timeout=120` named the binding NFR guard; raising tokens is fine *because* the timeout caps latency.
- `context/archive/2026-08-04-prod-logging-markdown-preview/plan.md:83-87,251,355-357` — stderr logging is metadata-only (no input bodies); `LOG_LEVEL` is the verbosity mechanism (default INFO).
- `context/archive/2026-08-03-change-input-pipeline/reviews/impl-review.md:61-67` (F3) — stderr exception forwarding flagged as a token-leak risk to harden.

## Related Research

- `context/archive/2026-08-01-agent-runtime-finding-schema/research.md` — provider/timeout/token-budget sizing (the original "why 120s / why max_tokens matters").
- `context/archive/2026-08-03-change-input-pipeline/` — the diff/context/plan loading design (the loader this change modifies).
- `context/archive/2026-08-04-graph-bugfixing/` — the `_MAX_TOKENS` raise + `NodeTimeoutError` degrade path (the live crash→timeout chain this change relaxes).
- `context/archive/2026-08-04-prod-logging-markdown-preview/` — the stderr-logging contract this change must stay inside.

## Open Questions

1. **Reconcile request #3 with the change title.** The literal request ("add a
   modified-Python-files tier between AGENTS.md and context docs") and the
   `change.md` title ("context directory *dismissal*" / "properly dismissing
   certain directories") describe *different* changes. Which is the real intent?
   The title suggests *excluding* some `./context` subdirs (e.g. other changes'
   docs), not *adding* a source-files tier. **Recommend resolving this before
   `/10x-plan`** (a clarifying question, or `/10x-frame`).
2. **Concrete `MAX_DIFF_CHARS` value.** "Proportional" is underspecified. With a
   1M window and the boundary-cap overshoot, pick a number with rationale
   (e.g. 200k or 400k) rather than leaving open. `_MAX_TOKENS=128000` is already
   the requested value in the working tree.
3. **Raise `MAX_CONTEXT_CHARS` too?** If modified-file content enters the
   context tier, the 8000 cap evicts the foundation/change docs. Decide: raise
   it proportionally, or accept truncation of context docs on big PRs.
4. **Timeout headroom.** 300s consumes the full ~5-min NFR with no margin for
   diff/context/plan loading + posting. Is 300s firm, or is 240s (4 min) safer?
   The operator said "say 5 minutes" — confirm whether the 5-min NFR is firm.
5. **Raw-log scope.** For debugging the timeout specifically, the gap is the
   *timeout path* (`NodeTimeoutError` fires in `graph.py`, so the partial result
   never reaches `_log_usage`). Is the goal a full raw dump (high leakage risk),
   or a targeted "usage/finish_reason captured before the timeout" signal
   (lower risk, higher signal for this specific bug)?

## Recommendation on next step

Given Open Question #1 (the request vs. title mismatch on context handling),
**run `/10x-frame fine-tune-context` or ask one clarifying question before
`/10x-plan`**. The timeout/caps/logging changes (requests #1, #2, #4) are
unambiguous and plan-ready; the context-reorder (request #3) is not, and
implementing the literal "modified files" tier would re-open a closed decision
(`change-input-pipeline/plan.md:86-88`) for reasons the change title doesn't
actually point at.
