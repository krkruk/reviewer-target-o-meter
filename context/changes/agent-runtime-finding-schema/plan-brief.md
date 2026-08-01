# F-01 — Agent Runtime + Finding/Severity Schema + OpenRouter Wiring — Plan Brief

> Full plan: `context/changes/agent-runtime-finding-schema/plan.md`
> Research: `context/changes/agent-runtime-finding-schema/research.md`

## What & Why

F-01 is the highest-risk foundation slice of `reviewer-target-o-meter`: scaffold the reviewer-agent
runtime as a LangGraph `StateGraph` (one node per FR-006 phase), the typed Pydantic `Finding`/`Severity`
schema, and the OpenRouter provider wiring. Its purpose is to **de-risk the unfamiliar agent stack
early** — the roadmap's stated top risk (`quality_override: true`) — by proving the free-tier model can
actually emit a valid findings report before S-01 invests in signal quality.

## Starting Point

A near-empty `uv init --package` scaffold: `dependencies = []`, a Hello-stub `main()`, Python `>=3.14`,
no graph/schema/tests. `.env.example` already exists and fixes the runtime-config mechanism
(`OPENROUTER_API_KEY`, `MODEL=nvidia/nemotron-3-super-120b-a12b:free`, `OPENROUTER_BASE_URL`). The
research doc verified the model slug, dissolved the LangChain-Agent-vs-LangGraph conflict
(`create_agent` is a sub-graph inside `checks`), and mapped the `/10x-impl-review-ci` methodology 1:1
onto FR-006.

## Desired End State

A developer runs the console command against a tiny fixture checkout and the agent loads context,
discovers a plan (both as accepted inputs), runs a **minimal** single-agent analysis over a fixture
diff via OpenRouter, and emits a real, host-re-validated `FindingsReport` of **full impl-review shape**
to stdout with an advisory exit code. The four-node graph, the two search `@tool`s, the cost/latency
bounds, and the fail-safe exist and are unit-tested; a live smoke proves the free model works; and
`AGENTS.md` records every "compensation owed" item.

## Key Decisions Made

| Decision                              | Choice                                              | Why (1 sentence)                                                                                       | Source   |
| ------------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | -------- |
| F-01 scope depth                      | Runnable end-to-end smoke (not scaffold-only)       | F-01's purpose is to de-risk the stack now; the smoke is the de-risking artifact.                      | Plan     |
| Finding schema richness               | Full impl-review shape (Severity+Impact+7-dim+Fix)  | Keeps provenance 1:1 with the methodology; the smoke is the canary for free-model reliability.         | Plan     |
| Deterministic checks (Non-Goal)       | Read-and-flag only — never execute tests/lint       | Honors PRD Non-Goal "no own deterministic checks" (`prd.md:118`); avoids flakiness/latency.            | Plan     |
| Graph shape                           | Single agentic `checks` node                        | Literal reading of "one node per FR-006 phase"; cheapest/cache-friendly; revisit parallelism at S-01.  | Plan     |
| F-01 / F-02 boundary                  | Accept (diff, context, plan) as inputs; don't compute | Honors the roadmap's deliberate split; F-02 owns diff/target-branch/context-loading.                  | Plan     |
| Provider client                       | `ChatOpenAI(base_url)` — honor tech-stack lock      | No doc drift; keeps the `.env.example` OpenAI-compatible swap path.                                    | Plan     |
| Search tools                          | Both ripgrep + ast-grep, degrade to ripgrep         | Matches FR-010 degrade philosophy; local devs without `sg` still run.                                  | Plan     |
| Test strategy                         | Unit always + opt-in live smoke (skip in CI)        | CI stays fast/hermetic; the de-risking smoke runs on demand + pre-merge.                               | Plan     |
| Severity taxonomy (OQ#3)              | CRITICAL/WARNING/OBSERVATION; `is_flagged` hidden   | Inherited from impl-review-ci; model picks enum, host decides signal (FR-011).                         | Research |
| Methodology provenance (OQ#7)         | `/10x-impl-review-ci` skill (Steps 0–5)             | Maps 1:1 onto FR-006; provenance resolved.                                                             | Research |
| Default model                         | `nvidia/nemotron-3-super-120b-a12b:free`            | Free; supports tools + structured_outputs + response_format (262k ctx).                                | Research |
| Cost ceiling (OQ#2)                   | recursion_limit≈40, max_iterations≈12, timeout=120s | $-cap moot (free model); bounds enforce the ~5-min latency NFR.                                         | Research |
| Structured-output method              | `json_schema` + `strict=True`                       | Super Nemotron supports it; host-side `model_validate` re-check as insurance.                           | Research |
| Fail-safe (OQ#1)                      | `include_raw=True` → empty+exit0; recursion→partial | Advisory-only step must not fail CI; degrade to empty/partial report.                                  | Research |
| Leakage redaction                     | Schema notes + absolute-path guard now; scanner deferred | Stdout mode writes nothing to the host (`prd.md:44`); regex scanner is S-01.                         | Research |

## Scope

**In scope:**
- Pin langchain/langgraph/langchain-openai/langchain-core (+ pydantic/typer/gitpython; dev pytest/ruff/mypy).
- Full-shape Pydantic `Finding`/`Severity`/`Impact`/`Dimension`/`FixOption`/`FindingsReport` schema.
- Env-driven `Config`; `ChatOpenAI(base_url)` provider + `with_structured_output` + host-side re-validate.
- Four-node `StateGraph` (deterministic spine + single agentic `checks`); `ReviewState`.
- Two subprocess `@tool`s (ripgrep + ast-grep-with-degrade).
- Cost/latency bounds + fail-safe + recursion probe.
- typer CLI joining it into one end-to-end smoke; unit + opt-in live-smoke tests.
- `Makefile` + `make.sh` helper — `make check` (ruff+mypy), `make test` (unit, excl. LLM smoke),
  `make llm-test` (live OpenRouter smoke), `make run DIR=<path>` (with `./make.sh run <dir>` wrapper).
- Repo-root `AGENTS.md` (compensation owed).

**Out of scope:**
- Real diff computation / target-branch discovery / git context loading (F-02).
- Full impl-review system prompt + 3-dimension signal-quality tuning (S-01).
- Executing the reviewed project's test/lint commands (Non-Goal).
- GitHub posting / GHA workflow (S-02) — only the ast-grep install recipe is *recorded*.
- Parallel analysis sub-nodes; secret regex scanner; configurable severity mapping; merge blocking.

## Architecture / Approach

Deterministic spine + agentic leaf: `START → context_load → plan_discovery → checks → report → END`.
`context_load`/`plan_discovery`/`report` are plain functions (accept inputs, no LLM loop); only `checks`
is agentic — a single `create_agent` sub-graph bound to the structured LLM and the two search `@tool`s,
bounded by `max_iterations≈12`. The graph is invoked with `recursion_limit≈40` + a `TimeoutPolicy` on
`checks`; `report` re-validates the payload (Pydantic state is input-validation only), sorts/caps/ids
findings, and emits stdout JSON + advisory exit.

```
[diff, context, plan] (accepted inputs — F-02 supplies the real pipeline)
        │
   context_load ──► plan_discovery ──► checks (create_agent + tools, structured LLM)
                                              │  FindingsReport
                                              ▼
                                           report ──► re-validate ► stdout JSON + exit 0/1
```

## Phases at a Glance

| Phase | What it delivers                                       | Key risk                                                         |
| ----- | ------------------------------------------------------ | ---------------------------------------------------------------- |
| 1. Schema + config + deps + Makefile | Full-shape schema + env `Config` + pinned versions + `make check/test/llm-test/run` helper | Schema over/under-specifies the methodology shape.               |
| 2. Provider + smoke      | `ChatOpenAI(base_url)` + live OpenRouter structured-output smoke | **Free-tier model can't emit the full shape reliably.** (the gate) |
| 3. Runtime + tools + e2e | Four-node graph, two `@tool`s, bounds, fail-safe, typer CLI, end-to-end smoke | Sub-agent/outer recursion interplay; free-tier variance in the loop. |
| 4. AGENTS.md             | Compensation owed: versions, import paths, conventions, checklist | Incomplete coverage of the `quality_override` debt.              |

**Prerequisites:** `.env.example` already present; an `OPENROUTER_API_KEY` for the Phase 2/3 live smoke.
**Estimated effort:** ~3-4 after-hours sessions across 4 phases (solo, unfamiliar stack).

## Open Risks & Assumptions

- **Free-tier structured-output reliability** — the full Fix-grammar is a lot for a free model; Phase 2's
  smoke is the canary. Mitigation: host-side `model_validate` re-check + `include_raw=True` fail-safe;
  if it fails, trim a field or move `MODEL` to a paid slug default.
- **Sub-agent recursion interplay unverified** — whether inner `max_iterations` counts against the outer
  `recursion_limit` is assumed-shared; Phase 3's probe confirms it before bounds are finalized.
- **Docs churn** — langchain/langgraph release ~weekly; the pins will age. Mitigation: `AGENTS.md` tells
  future agents to trust `uv.lock` + recorded import paths over web search.
- **Free-tier rate limits / withdrawal** — 429s or a withdrawn slug could break runs. Mitigation: slug
  centralized in one `Config` constant; `--model` escape hatch; advisory exit never fails CI.

## Success Criteria (Summary)

- `uv run reviewer-target-o-meter <fixture-dir>` emits a valid full-shape `FindingsReport` to stdout with
  an advisory exit code; `SMOKE=1` proves it against real OpenRouter.
- Unit tests (schema, mocked-subprocess tools, mocked-LLM graph) are green; CI stays offline/hermetic.
- `AGENTS.md` covers every `tech-stack.md` "compensation owed" item, and the unfamiliar-stack risk is
  retired ahead of S-01.
