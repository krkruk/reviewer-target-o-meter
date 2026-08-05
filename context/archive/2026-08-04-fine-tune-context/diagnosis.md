# Diagnosis — why the reviewer emits 0 findings on PR #28

> Artifact produced by Phase 2 of the fine-tune-context plan, updated through
> Phase 3 (the fix). Live `LOG_LEVEL=DEBUG` runs against
> `krkruk/target-o-meter#28` (HEAD `dbd3217`, +2731/-168, 38 files, raw diff
> 166670 chars). **The frame's hypothesis (diff-driven timeout) was overturned
> by the measurement**: the real causes are a tool-path bug (root), a
> tool-budget/non-convergence defect (secondary), and a structured-emit
> flakiness (tertiary). The three-layer fix below takes PR #28 from 0 findings
> to reliable >0 findings (3/3 verification runs, 4-6 findings each).

## Run summary

| | Run 1 | Run 2 |
|---|---|---|
| Wall-clock | ~300s | 483s |
| Terminal condition | `NodeTimeoutError` @ 300.001s (`timeout=300.0`) | finished — "Model call limits exceeded: run limit (8/8)" |
| Iterations used | <8 (timed out mid-run) | 8/8 (hit the cap) |
| `repo_path` ever correct? | n/a (no DEBUG dump — timed out before `ainvoke` returned) | **No** — 0/14 calls used the right path |
| Findings | 0 | 0 |
| DEBUG raw dump captured? | No (timeout path — `result: None`) | **Yes** (full message trace) |

Both runs produced 0 findings. Run 1 died on the node timeout; run 2 hit the
iteration cap. The DEBUG dump from run 2 is the load-bearing evidence — it
shows the agent's full 24-message trace.

## Dimension-map answers (from run 2's DEBUG dump)

### 1. Iteration count — 8/8 (hit the cap, not the timeout, in run 2)

Run 2's final AIMessage content is literally `"Model call limits exceeded: run
limit (8/8)"`. The agent used **all 8** allowed iterations. Run 1 used fewer
because it timed out before reaching the cap. So the `max_iterations=8` knob is
binding in run 2 — but reaching it is a *symptom*, not the cause (see #3).

### 2. Per-iteration token usage — modest; reasoning concentrated in call 1

From `usage_metadata` / `output_token_details.reasoning` across run 2's
AIMessages:

| call | input_tokens | output_tokens | reasoning_tokens | finish_reason |
|---|---|---|---|---|
| 1 (first tool batch) | 56233 | 7815 | **7508** | tool_calls |
| 2 | 56571 | 196 | 35 | tool_calls |
| 3 | 56749 | 124 | 44 | tool_calls |
| 4 | 56839 | 135 | 54 | tool_calls |
| 5 | 56930 | 209 | 60 | tool_calls |
| 6 | 57100 | 154 | 0 | tool_calls |
| 7 | 57271 | 139 | 58 | tool_calls |
| 8 (final) | 57378 | 104 | 23 | (run limit) |

`output_tokens` never approached the `_MAX_TOKENS=128000` ceiling (max 7815);
`finish_reason` was `"tool_calls"` throughout, never `"length"` (no truncation).
**The output token budget is NOT the constraint.** Input tokens are stable at
~57k (the cached diff — `cache_read: 53248` on most calls — keeps input cost
flat; OpenRouter is prompt-caching the diff automatically despite the repo not
configuring it). The frame's "diff re-sends with no caching" concern is
*mooted* — OpenRouter caches it.

### 3. Tool-call pattern — the actual killer: every search returns empty

Run 2 made **14 tool calls** across 8 iterations. The model's `repo_path`
arguments, with the result each returned:

| # | tool | query / pattern | `repo_path` model passed | result |
|---|---|---|---|---|
| 1-4 | text_search | DetectedHoleDTO / AcceptResultIn / marked-image / session_auth | `src/domains/vision/dtos.py`, `src/domains/vision`, `src/bff/routers/scoring_routes.py`, `src/bff` | **all empty (len 0)** |
| 5-6 | text_search | DetectedHoleDTO / AcceptResultIn | `.` | **empty** |
| 7 | text_search | ScoreListOut | `.` | **empty** |
| 8 | text_search | update_result | `/repo` | **empty** |
| 9-10 | structural_search | class DetectedHoleDTO / def get_job_for_user | `.` | **`[]`** |
| 11-12 | text_search | DetectedHoleDTO / get_job_for_user | `/repo` | **empty** |
| 13 | text_search | class ScoringStorage | `/` | **timed out 30s** |
| 14 | text_search | ScoringStorage | `src` | **empty** |

**Every single tool call returned empty.** Not one matched. The model kept
trying different path conventions (`src/...`, `.`, `/repo`, `/`) across all 8
iterations, got nothing back, and hit the iteration cap having produced no
findings.

**Why empty — the bug:** `text_search`/`structural_search` invoke
`rg`/`ast-grep` with the `repo_path` argument as-is, resolved against the
**reviewer's process CWD** (`reviewer-target-o-meter/`, where `make run` runs).
The reviewed checkout lives at `/home/.../target-o-meter/` — a different tree.
The model passes relative paths (`src/...`) or hallucinated absolute ones
(`/repo`, `/`), none of which exist relative to the reviewer's CWD, so `rg`
errors or finds nothing.

**Proof the symbols exist in the checkout** (rg run against the correct path):

```
rg 'DetectedHoleDTO'  <checkout>  → 33 matches
rg 'ScoreListOut'     <checkout>  → 13 matches
rg 'ScoringStorage'   <checkout>  → 74 matches
rg 'get_job_for_user' <checkout>  →  4 matches
```

The tools work; the **path they're given** is wrong. `ast-grep` IS installed
(`/usr/local/sbin/ast-grep`), so this is not a degrade case — it ran and
returned `[]` against the wrong path.

**Why the model never passes the right path:** `cli.py:70` puts the absolute
`repo_path` into `ReviewState.repo_path`, but the `checks` node
(`nodes.py:236-249`) builds the agent's `HumanMessage` from **only** `diff` +
`context` + `plan` — it never surfaces `repo_path` to the model. The tool
docstrings say `repo_path: Absolute or repo-relative path` with no default and
no anchor in the prompt, so the model has nothing to copy from and hallucinates.

### 4. Diff re-send cost — not the driver (caching mutes it)

The frame hypothesized the 166k-char diff re-sent every iteration with no
caching would dominate. The DEBUG dump disproves this: `input_tokens` is flat
at ~57k across all 8 calls, and `prompt_tokens_details.cached_tokens: 53248` on
most calls shows **OpenRouter is prompt-caching the diff automatically**. The
diff is NOT being re-billed at full cost each turn. (Note for `research.md`: the
repo doesn't configure caching, but OpenRouter applies it transparently for
this model — the "no caching" grep finding in the frame is true at the code
level but false at the provider level.)

### 5. Where did time go — tool-call round-trips dominate run 2; reasoning dominates run 1

- **Run 2 (483s, 8 iterations, 14 tool calls):** wall-clock was dominated by
  the **14 tool round-trips** (each `text_search`/`structural_search` is a
  separate model call after the tool returns), plus one 30s `text_search`
  timeout (call 13, `repo_path=/` — ripgrep walking the filesystem root). Not a
  single long reasoning step — reasoning_tokens were 0 on call 6 and ≤60 on the
  rest. The iteration cap, not latency, was the binding constraint.
- **Run 1 (~300s, timed out):** the first AIMessage spent **7508 reasoning
  tokens** before its first tool call — the reasoning model chewed the 166k diff
  deeply on turn 1, inflating per-call latency enough that fewer iterations
  completed within the 300s node window. This is the **secondary amplifier**
  the operator's reasoning-effort hint targets.

## Verdict — the bottleneck

**The leading cause of 0 findings is the tool-`repo_path` bug (#3), not the
timeout, not the diff, not the token budget.** Run 2 is dispositive: it
finished in 483s *without* a node timeout and still emitted 0 findings, because
every tool call hit the wrong path and returned empty. Fixing only the timeout
(the frame's plan A) would convert run 1 into run 2 — still 0 findings.

The timeout (run 1) is a **secondary amplifier**: the deepseek reasoning model
spends heavy reasoning tokens on turn 1 over the large diff, inflating latency.
Lowering reasoning effort (operator hint) addresses this amplifier but does not
address the 0-findings symptom — run 2 already proves the tool-path bug yields
0 findings even when the run completes.

## Prescribed Phase-3 fix

1. **PRIMARY — surface the absolute `repo_path` to the agent.** In the `checks`
   node, prepend a `Repository path (absolute): <repo_path>` line to the
   `HumanMessage` so the model has the correct path to copy into every tool
   call. This is the one-line fix that makes the tools actually search the
   reviewed checkout. (Touches `nodes.py` only; preserves the three
   product-specific prompt adaptations — plan-tolerance, no-command-execution,
   diff-scoping.)

2. **SECONDARY — lower reasoning effort to medium** via OpenRouter's
   `reasoning.effort` parameter (`{"reasoning": {"effort": "medium"}}`), passed
   through `ChatOpenAI(model_kwargs=...)` or `extra_body`. Belt-and-suspenders
   against run 1's reasoning-latency amplifier; medium is the documented
   default and trims the 7508 reasoning tokens on turn 1. (Touches
   `provider.py`.)

3. **Keep the Phase-1 knob values** (run_timeout=300, max_iterations=8,
   MAX_DIFF_CHARS=200000). They are not the cause and the values are reasonable
   for a paid 1M model; the measurement does not justify changing them further.

## Final knob values the fix implies

| Knob | Phase-1 hypothesis | Measured final | Rationale |
|---|---|---|---|
| `run_timeout` | 300 | **300** | verification runs finished in 200-478s; 300s is ample headroom. Keep. |
| `max_iterations` | 8 | **16** | 8/12 saw the agent exhaust every turn on tool calls and never emit (0 findings). 16 leaves room for the final structured emit. |
| (new) `max_tool_calls` | — | **18** | the decisive Phase-3 lever — see below. Forces convergence via `ToolCallLimitMiddleware(continue)`. |
| `MAX_DIFF_CHARS` | 200000 | **200000** | PR #28's 166670 raw chars fit untruncated; caching keeps input cost flat. Keep. |
| `_MAX_TOKENS` | 128000 | **128000** | never approached (max output ~4k). Keep. |
| (new) `reasoning.effort` | — | **medium** | low emits empty/malformed JSON (run 6); high over-investigates. medium emits reliably. |

## Phase 3 — the iterative fix and verification

The Phase-2 diagnosis identified the **root cause** (tool-`repo_path` bug) but
the first fix (surface `repo_path`) alone was **not sufficient**: runs 3-9
(with tools returning real results) still produced 0 findings. Iterating against
the DEBUG output revealed **two further defects**, each addressed by one layer
of the final fix. (Runs 3-12 are the diagnosis-extension iterations; runs 13-15
are the final verification.)

### The three defects and the three-layer fix

1. **ROOT — tool `repo_path` never surfaced (Phase 2 finding).** The `checks`
   node built the agent's message from diff+context+plan only; the model never
   saw the checkout path, so every tool call hit the reviewer's CWD and returned
   empty (14/14 empty in run 2). **Fix:** prepend a `Repository path (absolute)`
   line to the message; the model now passes the right path and tools return
   real results (verified run 3+).

2. **SECONDARY — agent never self-limits its tool investigation.** With tools
   working, the model burned **every** model call on tool batches (runs 4/7/8:
   8/12/16 turns all on tools, 0 findings — "run limit" before any emit).
   Prompt-nagging was ignored. **Fix:** `ToolCallLimitMiddleware(run_limit=18,
   exit_behavior="continue")` — a deterministic tool-call budget. Over-budget
   calls return an error message and execution continues, so the model converges
   and emits. (Native LangChain built-in; cleaner than the static-variable
   fallback the operator suggested — no per-review reset needed.) 18 lets a
   well-batched model (3 calls/turn) do ~6 investigation turns then emit.

3. **TERTIARY — deepseek emits empty JSON on the structured-output turn.** Even
   after convergence, the model intermittently returns empty content on its
   final emit (`StructuredOutputValidationError ... line 1 column 1 (char 0)`) —
   pure model flakiness, NOT a token-budget issue (output ~4k vs 128k ceiling;
   runs 6, 9, 11). **Fix:** `_invoke_with_emit_retry` — up to 2 retries with an
   explicit "emit valid JSON now" nudge. Recovers the flaky empty-emit (run 14
   recovered this way → 6 findings).

`reasoning.effort=medium` is the supporting choice: low made the empty-emit
flakiness worse (run 6); high amplified the over-investigation. medium emits
reliably and, with the tool-call budget, converges in time.

### Verification — runs 13-15 (final fix stack, 3/3 success)

| Run | Wall | findings | flagged | exit | retry fired | tool-budget hit |
|---|---|---|---|---|---|---|
| 13 | 200s | 4 | 1 | 1 | no | no (converged naturally) |
| 14 | 478s | 6 | 2 | 1 | yes (recovered empty-emit) | yes |
| 15 | 257s | 4 | 2 | 1 | no | no (converged naturally) |

All findings spot-checked: valid anchors (files exist, lines in range), correct
severities, substantive defects. Recurring flagged findings across runs (silent
`getScores` failure swallowing, missing PATCH score validation, delete-on-last-
page desync) are genuine correctness defects. Compare to runs 1-12: **0/12
produced findings; 3/3 of the final stack do.**
