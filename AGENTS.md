# AGENTS.md — reviewer-target-o-meter

> Onboarding for AI coding agents (and humans) working in this repo. Read once,
> stay unblocked. This file pays down the `quality_override: true` debt recorded
> in `context/foundation/tech-stack.md` (§"Compensation owed"): pinned versions,
> canonical import paths, graph convention, severity rules, and the review-output
> checklist that builds the "can judge agent output" muscle.

## Where things live

```
reviewer-target-o-meter/          # the Python package (uv-managed)
  src/reviewer_target_o_meter/    # production code
    findings.py                   # typed Finding/Severity schema (the output contract)
    config.py                     # env-driven Config + cost/latency knobs
    provider.py                   # OpenRouter client + structured-output fail-safe
    state.py                      # ReviewState (typed graph state)
    graph.py                      # the four-node StateGraph + run_review
    cli.py                        # typer console command
    agent/
      nodes.py                    # context_load / plan_discovery / checks / report
      tools/                      # text_search (ripgrep), structural_search (ast-grep)
  tests/                          # pytest; tests/fixtures/sample-repo for the smoke
  Makefile, make.sh               # developer entry points (see Developer commands)
context/                          # planning docs (PRD, roadmap, tech-stack, changes/)
```

Python lives in the nested package; planning docs (`context/`) live at the git root.
There is **no remote yet** — all references are local `path:line`.

## (a) Pinned versions + canonical import paths

The LangChain/LangGraph stack churns weekly; 0.x web examples are **stale**. The
single source of truth is `reviewer-target-o-meter/uv.lock` plus the import paths
below. **Trust `uv.lock` + these import paths over web search.**

Pinned (verified PyPI 2026-08-01; resolved set recorded in `uv.lock`):

| Package | Pin | Resolved |
|---|---|---|
| `langchain` | `==1.3.14` | 1.3.14 |
| `langgraph` | `==1.2.10` | 1.2.10 |
| `langchain-openai` | `==1.4.1` | 1.4.1 |
| `langchain-core` | float | 1.5.3 |
| `pydantic` | float | 2.13.4 |

Canonical import paths used by this project:

```python
from langgraph.graph import StateGraph, START, END
from langgraph.errors import GraphRecursionError
from langgraph.types import RetryPolicy, TimeoutPolicy
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, Runtime
from langchain.agents.structured_output import ProviderStrategy   # json_schema+strict on an agent
from langchain.tools import tool
from langchain.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI                            # OpenRouter via base_url
```

## (b) Graph convention

- **One node per FR-006 phase**, as a LangGraph `StateGraph`:
  `START → context_load → plan_discovery → checks → report → END`.
- The spine is **deterministic** (`context_load`, `plan_discovery`, `report`);
  only `checks` is agentic — a single `create_agent` sub-graph with
  `response_format=ProviderStrategy(FindingsReport, strict=True)` and a
  `ModelCallLimitMiddleware(run_limit=...)` iteration cap.
- **Pydantic state is input-validation only.** Node outputs come back as plain
  dicts — so `findings` is **re-validated by `model_validate` at the `report`
  node** before emit. This is the single most load-bearing gotcha; do not rely on
  per-node enforcement.
- **`@tool`s never raise.** `text_search`/`structural_search` catch
  `subprocess.TimeoutExpired`/`FileNotFoundError` and return an error string; they
  degrade on missing binaries (`structural_search` points the model at
  `text_search`). Output is capped (20k chars); param names are snake_case; never
  name a tool parameter `config` or `runtime`.
- **Async `checks`.** The `checks` node is `async def` and the graph is driven via
  `ainvoke` because LangGraph only enforces `TimeoutPolicy` on async nodes (sync
  Python execution can't be safely cancelled in-process).

## (c) Severity taxonomy + line-anchor rules

- `Severity` enum: **CRITICAL / WARNING / OBSERVATION** (OQ#3, from the
  impl-review-ci methodology). Sorted CRITICAL → WARNING → OBSERVATION.
- `Severity.is_flagged` is a **plain `@property`, NOT a `@computed_field`** — it is
  deliberately absent from the JSON schema the model sees (`True` for CRITICAL/WARNING,
  `False` for OBSERVATION). **The model picks the enum value; the host decides the
  signal** (FR-011). Likewise `FindingsReport.flagged`/`exit_code` are host-side.
- Anchors (FR-009): `file` is **repo-relative** (absolute paths are rejected by a
  validator); `line` is **required, 1-based, `ge=1`**; `end_line` (optional) must be
  `>= line`. `title` ≤120 chars; `detail` is the rationale (required).
- **Exit code is advisory (FR-008):** `0` if no finding is flagged, else `1`. It
  never blocks a merge. `FindingsReport.exit_code` computes this from the flagged set.
- **No `id` on `Finding`.** The `report` node injects `F{n}` during serialization
  (models are unreliable at sequential ids). **No `Decision: PENDING`** field
  (CI-harness-triage only).
- Fix grammar: `fixes: list[FixOption]` (`max_length=2`); an `approach` is a
  one-sentence fix **DIRECTION, never an applied patch**; if there are exactly two,
  exactly one must be `recommended=True`.

## (d) Locked decisions (from the F-01 plan)

- **Provider:** `ChatOpenAI(model=..., base_url=$OPENROUTER_BASE_URL, api_key=...,
  temperature=0)` against OpenRouter — env-driven, not hardcoded. Key read at runtime
  only, never echoed.
- **Structured output:** `create_agent(..., response_format=ProviderStrategy(
  FindingsReport, strict=True))` (json_schema + strict), with a host-side
  `model_validate` re-check as cheap insurance.
- **Determinism:** `temperature=0` for "consistent across re-runs".
- **Read-and-flag only** — the agent must NOT execute the reviewed project's
  test/lint/build commands (PRD Non-Goal).
- **Single `checks` node** (no parallel sub-nodes — revisit at S-01 if per-lens depth
  is shallow).
- **Both tools degrade** (ripgrep missing → error string; ast-grep missing →
  point at ripgrep).
- **Full schema shape:** Severity + Impact + 7-dimension + Confidence + Fix-grammar.
- **Fail-safe (OQ#1):** `GraphRecursionError` → partial/empty report + advisory
  exit; structured-output parse failure → empty report + exit 0. Never crash the
  pipeline.

## (e) Review-output checklist

Before trusting (or posting) a `FindingsReport`, sanity-check it:

1. **Every finding has a real anchor** — repo-relative `file`, `line >= 1`, and the
   file actually exists at that path in the reviewed checkout.
2. **Severity matches the claim** — a CRITICAL must be a real correctness/security
   defect; OBSERVATION is stylistic/optional. Reject severity inflation.
3. **`detail` is a rationale, not a restatement** — it explains *why* it's a problem,
   with the causal chain; not just "this is bad".
4. **`fixes` are directions, not patches** — no applied diffs; ≤2; exactly one
   `recommended` if two. A fix that edits code is out of scope.
5. **No secrets/source spans leaked** beyond the analysis call — confirm
   `OPENROUTER_API_KEY` and absolute host paths never appear in the report.
6. **`dimension` is one of the seven** (correctness, security, maintainability,
   testability, performance, design, documentation) and actually fits the finding.
7. **The exit code matches the flagged findings** — 0 iff nothing is CRITICAL/WARNING.

## (f) ast-grep GitHub Actions install recipe

`ripgrep` (`rg`) ships on `ubuntu-latest`; `ast-grep` (`sg`) needs a setup step.
Recorded here so S-02 doesn't re-discover it:

```yaml
- name: Install ast-grep
  run: |
    # Option A: cargo (needs Rust toolchain)
    cargo install ast-grep
    # Option B: download the prebuilt binary. NOTE: the asset carries an `app-`
    # prefix (app-x86_64-unknown-linux-gnu.zip), NOT x86_64-unknown-linux-gnu.zip
    # — the unprefixed URL 404s and breaks the step (verified on the consumer
    # GHA run, 2026-08-03).
    curl -L https://github.com/ast-grep/ast-grep/releases/latest/download/app-x86_64-unknown-linux-gnu.zip -o sg.zip
    unzip sg.zip && install -m 0755 ast-grep /usr/local/bin/sg
```

If `sg` is unavailable at runtime, `structural_search` returns an error string
pointing the model at `text_search` — the pipeline still runs (degrade philosophy).

## (g) Developer commands

All run from `reviewer-target-o-meter/` (where `pyproject.toml` lives):

```bash
make check        # ruff + mypy src            (linters + static type verification)
make test         # uv run pytest -m "not smoke" (unit tests; excludes live LLM smoke)
make llm-test     # SMOKE=1 uv run pytest -m smoke  (live OpenRouter; needs OPENROUTER_API_KEY)
make run DIR=path # uv run reviewer-target-o-meter "$DIR"  (run the app)
make help         # list targets
```

`./make.sh` is a thin wrapper that lets `run` take a positional dir:
`./make.sh run <dir>` ⇄ `make run DIR=<dir>`; `./make.sh {check|test|llm-test|help}`
pass straight through. The Makefile is the single source of truth.

**Env:** copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` (required).
`MODEL` and `OPENROUTER_BASE_URL` have sensible defaults (override for a paid slug).
`.env` is gitignored.

## (h) Critical-point analysis methodology provenance (resolves roadmap OQ#7)

The `checks` node's `_SYSTEM_PROMPT`
(`reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`) is the
**single source of truth** for the analysis methodology prompt text. It adapts
an established implementation-review methodology rather than inventing one:

- **Source:** the `/10x-impl-review-ci` reference
  (`references/impl-review-instructions.md`) — "review an implementation against
  the plan it claims to realize", with its three review lenses (plan drift /
  safety-quality-pattern / test-coverage) and the MISSING-TEST /
  UNCOVERED-BEHAVIOR commitments.

- **Three product-specific adaptations** (where this product diverges from a
  literal impl-review — load-bearing, do not "fix" them back to the literal form):
  1. **Plan-tolerance.** Plan-dependent checks (the drift lens) run only when a
     plan is discoverable; with no plan they are skipped (FR-006). `plan_loader.py`
     turns a (checkout, diff) into a plan or `None`; the prompt's plan-tolerance
     conditional handles `None`.
  2. **No command execution.** MISSING-TEST / UNCOVERED-BEHAVIOR come from
     **static / presence evidence** (diff + plan), never from running the
     reviewed project's test/lint/build commands (PRD Non-Goal). Read-and-flag only.
  3. **Diff-scoping (active investigation).** Every finding anchors on a
     diff-touched file/line (the one exception: a plan-drift MISSING finding on
     a *planned-but-absent* file). The tools deepen context on changed files
     only — `structural_search` traces a changed symbol's definition/call sites
     and maps control/data flow; `text_search` reads a sibling for a pattern
     comparison — they never discover issues in untouched files (that is the
     repo-wandering noise that kills the product). This is prompt-resident and
     gated by the `test_smoke_signal.py` diff-scoping guard smoke.

- **Lens→dimension mapping is prompt-resident (soft), NOT schema-enforced.** The
  prompt teaches the mapping (drift→correctness/maintainability/design;
  safety→security/performance/maintainability; coverage→testability); a real
  defect may legitimately fit two dimensions, so the model picks the best fit and
  the host does not enforce a 1:1 mapping. No `lens` field exists on `Finding`.

- **Verdict is narrative-only.** The model may emit a 1-2 sentence
  `overall_verdict` naming the change's biggest risk. The PASS/WARN/FAIL-per-
  dimension grid (if ever surfaced) is **host-side derivation** from the flagged
  severities — it is NOT a model field. `Severity.is_flagged` (§c) stays
  host-side: the model picks the enum; the host decides the signal (FR-011).

## What's NOT here yet (deferred to later slices)

- **S-02:** GitHub posting on the consumer GHA workflow + the `ast-grep` GHA
  install (the recipe is recorded in §f; `structural_search` degrades to a
  pointer at `text_search` when `sg` is unavailable).
- **S-02:** GitHub posting + the GHA workflow. F-01 only *records* the ast-grep recipe.
