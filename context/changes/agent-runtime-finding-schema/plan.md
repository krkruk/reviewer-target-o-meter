# F-01 — Agent Runtime + Finding/Severity Schema + OpenRouter Wiring

## Overview

F-01 is the highest-risk foundation slice: scaffold the reviewer-agent runtime as
a LangGraph `StateGraph` (one deterministic node per FR-006 phase — `context_load →
plan_discovery → checks → report` — with a single agentic `checks` node built from
`create_agent`), the typed Pydantic `Finding`/`Severity` schema in the **full
impl-review shape** (Severity + Impact + 7-dimension + Fix-grammar), env-driven
OpenRouter provider wiring via `langchain-openai.ChatOpenAI(base_url=...)`, and
subprocess-backed search `@tool`s — proven by a **runnable end-to-end smoke** that
produces a real, validated `FindingsReport`, plus the root `AGENTS.md` that pays down
the `quality_override` debt. F-01's purpose is to de-risk the unfamiliar agent stack
*early*; it does **not** deliver the signal-quality analysis (that is S-01).

## Current State Analysis

- **Baseline is a near-empty `uv init --package` scaffold.** `reviewer-target-o-meter/pyproject.toml`
  has `dependencies = []` and `requires-python = ">=3.14"`; `src/reviewer_target_o_meter/__init__.py:1`
  is a Hello-stub `main()` wired as the `[project.scripts]` console entry. No CLI parsing,
  no graph, no schema, no tests. Python `3.14` (`.python-version`).
- **`.env.example` already exists** and fixes the runtime-config mechanism: `OPENROUTER_API_KEY`
  (required), `MODEL=nvidia/nemotron-3-super-120b-a12b:free` (the verified free default),
  `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`, and an opt-in `GITHUB_TOKEN`. Provider
  wiring is therefore env-driven, not hardcoded.
- **Nested layout.** Python package lives in `reviewer-target-o-meter/src/reviewer_target_o_meter/`;
  planning docs (`context/`) live at the git root. F-01 code goes under the package; `AGENTS.md`
  goes at the git root.
- **No remote yet** (research.md:23-26) — all references are local `path:line`.
- **Research is the authoritative grounding** (`research.md`): it dissolved the LangChain-Agent-vs-
  LangGraph conflict (`create_agent` is a compiled sub-graph embedded inside `checks`), verified the
  model slug and its `tools`/`structured_outputs`/`response_format` support, mapped the
  `/10x-impl-review-ci` methodology 1:1 onto FR-006, and resolved OQ#3 (severity taxonomy),
  OQ#7 (methodology provenance), and OQ#2's mechanism. This plan does not re-investigate what
  research already mapped.

### Key Discoveries:

- `create_agent` returns a compiled LangGraph graph → it composes as a **sub-graph inside the
  `checks` node**, not as an alternative to the locked `StateGraph` (`research.md:88-112`).
- **Pydantic state is input-validation only.** LangGraph validates `ReviewState` on graph input,
  but node outputs come back as plain dicts — the `Finding[]` must be **re-validated at the `report`
  node** (`research.md:114-118`). Load-bearing gotcha.
- **The model judges severity; the tool decides signal.** `Severity.is_flagged` is a Python
  `@property` **not** exposed to the LLM (FR-011's hardcoded mapping stays host-side) (`research.md:173-184`).
- **Reserved tool-arg names:** `config` and `runtime` — never name a `@tool` parameter these
  (`research.md:126-127`).
- **Docs churn is the real risk.** langchain/langgraph release ~weekly; 0.x web examples are stale.
  Future agents must trust `uv.lock` + the recorded import paths over web search (`research.md:149-152`,
  `tech-stack.md:153-155`).
- **Free-tier model variance** is the residual unknown the smoke exists to surface (`research.md:559-567`).

## Desired End State

When F-01 is complete, a developer can run the console command (or the graph directly) against a
tiny fixture checkout, and the agent will: load context, discover a plan (both as accepted inputs —
no git diff computed), run a **minimal** single-agent analysis over a fixture diff via OpenRouter
using `with_structured_output(FindingsReport, method="json_schema", strict=True)`, and emit a
real, host-re-validated `FindingsReport` of **full impl-review shape** to stdout with an advisory
exit code. The full-shape schema, the four-node graph, the two search `@tool`s, the cost/latency
bounds, and the fail-safe behavior all exist and are unit-tested; the live smoke proves the free
model emits a valid report. `AGENTS.md` at the repo root records every "compensation owed" item.

**Verification of the end state:** `uv run pytest` (unit) is green; `SMOKE=1 uv run pytest -m smoke`
(live OpenRouter) returns a validated non-empty `FindingsReport`; `uv run reviewer-target-o-meter
<fixture-dir>` (Phase 3 wiring) prints JSON to stdout and exits 0/1 advisory; `uv run ruff check &&
uv run mypy src` are clean; `AGENTS.md` exists at the repo root.

## What We're NOT Doing

- **No real diff computation / target-branch discovery / git-based context loading** — that is F-02
  (FR-005/002/004). F-01's `context_load`/`plan_discovery` accept their inputs; the smoke uses a fixture.
- **No full impl-review system prompt or 3-dimension signal-quality tuning** — that is S-01. F-01's
  `checks` node carries a **minimal** analysis prompt sufficient only to exercise the smoke.
- **No executing the reviewed project's test/lint/build commands** — read-and-flag only (PRD Non-Goal,
  `prd.md:118`). The agent flags MISSING-TEST / UNCOVERED-BEHAVIOR risk from static/presence evidence.
- **No GitHub posting, no GHA workflow** — that is S-02. F-01 only *records* the ast-grep install
  recipe in `AGENTS.md` so S-02 doesn't re-discover it.
- **No parallel analysis sub-nodes** — single `checks` node (revisit parallelism at S-01 if per-lens
  depth is shallow).
- **No secret regex/entropy scanner** — schema-level leakage notes + absolute-path guard ship now;
  the scanner is deferred (stdout mode writes nothing to the host — `prd.md:44`).
- **No configurable severity-to-signal mapping** — FR-011 hardcoded in v1.
- **No merge blocking** — exit code is advisory only (`prd.md:117`).
- **No `Decision: PENDING` field** — CI-harness-triage-only (`research.md:259-261`).

## Implementation Approach

Four sequential phases, ordered so the highest-risk unknown (free-tier structured output of the full
schema) is gated **before** the runtime is built on top of it:

1. **Schema + config + deps + Makefile** — the typed contract every later phase validates against,
   plus the `make check`/`make test`/`make llm-test`/`make run` helper (targets come online as their
   deps land across phases).
2. **Provider wiring + structured-output smoke** — proves the free model emits a valid full-shape
   `FindingsReport`. *If this fails, adjust (trim schema / switch model) before Phase 3.*
3. **LangGraph runtime + tools + end-to-end smoke** — builds the four-node graph and joins it into one
   runnable end-to-end path via a typer CLI.
4. **`AGENTS.md`** — the `quality_override` paydown.

Provider client: `langchain-openai.ChatOpenAI(base_url=$OPENROUTER_BASE_URL)` — honors the locked
tech-stack decision and the `.env.example` override semantics. Structured output:
`with_structured_output(FindingsReport, method="json_schema", strict=True)` (the Super Nemotron
supports it — `research.md:591-592`), with a host-side `model_validate` re-check as cheap insurance.
Graph: `START → context_load → plan_discovery → checks → report → END`; only `checks` is agentic
(a single `create_agent` sub-graph). Cost/latency: `recursion_limit≈40`, inner `max_iterations≈12`,
`TimeoutPolicy(run_timeout=120)` on `checks`, bounded `RetryPolicy` on OpenRouter-calling nodes.
Determinism: `temperature=0`. Fail-safe (OQ#1): `include_raw=True` → empty report + exit 0 on parse
failure; catch `GraphRecursionError` → partial report + advisory exit.

## Critical Implementation Details

- **Pydantic state is input-validation only.** Node outputs return as plain dicts — the `report` node
  MUST call `FindingsReport.model_validate(...)` on the agent's payload before emit (do not rely on
  per-node enforcement). This is the single most load-bearing gotcha (`research.md:114-118`).
- **`Severity.is_flagged` is a `@property`, not `@computed_field`.** It must NOT appear in the JSON
  schema the model sees — the model picks the enum value; the host decides the signal (FR-011).
- **Reserved `@tool` parameter names: `config` and `runtime`.** Never name a tool argument either.
- **`@tool` functions must never raise.** Catch `subprocess.TimeoutExpired` / `FileNotFoundError` and
  return an error string; cap output (e.g. `[:20000]`, `--max-count`) for the context budget; use
  snake_case names (some providers reject other chars); type hints define the input schema and the
  docstring is the LM-visible description.
- **Sub-agent recursion interplay is unverified.** Whether the inner `create_agent`'s `max_iterations`
  counts against the outer `recursion_limit` is assumed-shared (size outer = chain + inner×2). Confirm
  with a ~10-line probe in Phase 3 before finalizing the bounds (`research.md:477-479`, D-SubAgentRecursion).
- **Trust `uv.lock` + the recorded import paths over web search.** The pinned versions below are the
  source of truth; 0.x LangChain web examples are stale (`research.md:149-152`).

## Phase 1: Dependencies, Config & Typed Schema

### Overview

Pin the stack, then build the typed contract — the full impl-review-shaped Pydantic schema and the
env-driven `Config` — that every later phase validates against, plus the `Makefile`/`make.sh` helper
that exposes `check`/`test`/`llm-test`/`run`. No graph, no provider yet.

### Changes Required:

#### 1.1 Pin dependencies

**File**: `reviewer-target-o-meter/pyproject.toml`

**Intent**: Pay the `quality_override` version-pin debt and provision the runtime + dev toolchain.

**Contract**: Add to `[project.dependencies]` (versions verified PyPI 2026-08-01, `research.md:140-148`):
`langchain==1.3.14`, `langgraph==1.2.10`, `langchain-openai==1.4.1`, `langchain-core` (float → let `uv`
resolve; record exact set in `uv.lock`), `pydantic`, `typer`, `gitpython`. Add `[dependency-groups.dev]`
(or `uv add --dev`): `pytest`, `ruff`, `mypy`. Register the `smoke` test marker now in
`[tool.pytest.ini_options]` (`markers = ["smoke: live OpenRouter tests — opt in via make llm-test"]`)
so `-m "not smoke"` (used by `make test`) is warning-free from Phase 1, before any smoke test exists.
Run `uv sync` so `uv.lock` captures the resolved graph. `requires-python=">=3.14"` is compatible (all
declare `>=3.10`).

#### 1.2 Full-shape Finding/Severity schema

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/findings.py`

**Intent**: The machine-validatable output contract (FR-009 anchors, FR-011 hardcoded signal mapping,
OQ#3 severity taxonomy) in the full impl-review shape chosen in planning (Severity + Impact +
7-dimension + Fix-grammar; no `Decision: PENDING`).

**Contract**: Pydantic v2 models. `Severity(str, Enum)` = `CRITICAL/WARNING/OBSERVATION` with a `@property
is_flagged` (returns `True` for `CRITICAL|WARNING`) — **not** a `@computed_field`, so it is absent from
the JSON schema the model sees. `Impact(str, Enum)` = `LOW/MEDIUM/HIGH`. `Dimension(str, Enum)` = the
seven impl-review dimensions (`research.md:198-202`, `references/impl-review-instructions.md:101-108`).
`Confidence(str, Enum)` = `HIGH/MEDIUM/LOW`. `FixOption` (`approach` required and min_length=1 — a
direction, **never** an applied patch, per Non-Goal `prd.md:119`; optional `strength`, `tradeoff`,
`blind_spot`, `confidence`, `recommended: bool = False`). `Finding` (`frozen=True`): required `file`
(repo-relative, `min_length=1`), `line` (`ge=1`, 1-based — FR-009 mandatory), `severity`, `impact`,
`dimension`, `title` (`max_length=120`), `detail` (the rationale — FR-009); optional `end_line` (`ge=1`)
and `fixes: list[FixOption]` (`max_length=2`). `FindingsReport`: `findings: list[Finding]`,
optional `summary`, optional `overall_verdict`, a `@property flagged` and a `@property exit_code`
(`0` if no flagged findings else `1` — FR-008 advisory). Validators: `_end_line_ge_line` (model,
`end_line >= line`), `_no_absolute_path` (field, reject `file` starting with `/`), and a fixes validator
(≤2; if exactly 2, exactly one `recommended=True`). No `id` field on `Finding` — the `report` node
injects `F{n}` during serialization (models are unreliable at sequential IDs; keeps the model's job
content-only).

```python
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Severity(str, Enum):
    CRITICAL = "critical"; WARNING = "warning"; OBSERVATION = "observation"
    @property
    def is_flagged(self) -> bool:           # FR-011 — NOT a @computed_field (hidden from the model)
        return self in (Severity.CRITICAL, Severity.WARNING)

class FixOption(BaseModel):
    model_config = ConfigDict(frozen=True)
    approach: str = Field(..., min_length=1, description="One-sentence fix DIRECTION, never an applied patch.")
    strength: str | None = None; tradeoff: str | None = None; blind_spot: str | None = None
    confidence: "Confidence | None" = None; recommended: bool = False

class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)
    file: str = Field(..., min_length=1)
    line: int = Field(..., ge=1)
    end_line: int | None = Field(default=None, ge=1)
    severity: Severity; impact: "Impact"; dimension: "Dimension"
    title: str = Field(..., min_length=1, max_length=120)
    detail: str = Field(..., min_length=1)              # = rationale (FR-009)
    fixes: list[FixOption] = Field(default_factory=list, max_length=2)
    @model_validator(mode="after")
    def _end_line_ge_line(self) -> "Finding":
        if self.end_line is not None and self.end_line < self.line: raise ValueError("end_line >= line")
        return self
    @field_validator("file")
    @classmethod
    def _no_absolute_path(cls, v: str) -> str:
        if v.startswith("/"): raise ValueError("file must be repo-relative, not absolute")
        return v
    @model_validator(mode="after")
    def _fixes_grammar(self) -> "Finding":
        if len(self.fixes) == 2 and sum(o.recommended for o in self.fixes) != 1:
            raise ValueError("two fix options must mark exactly one recommended")
        return self

class FindingsReport(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    summary: str | None = None; overall_verdict: str | None = None
    @property
    def flagged(self) -> list[Finding]:
        return [f for f in self.findings if f.severity.is_flagged]
    @property
    def exit_code(self) -> int:                          # FR-008 advisory 0/1
        return 1 if self.flagged else 0
```

#### 1.3 Env-driven Config

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/config.py`

**Intent**: One place that holds the model slug, endpoint, and the cost/latency bounds (OQ#2 mechanism),
all env-overridable; a `--model` escape hatch for a paid slug in CI.

**Contract**: A frozen Pydantic `BaseSettings`-like (or plain `pydantic.BaseModel` populated from
`os.environ`) `Config` reading `OPENROUTER_API_KEY` (required), `MODEL` (default
`nvidia/nemotron-3-super-120b-a12b:free`), `OPENROUTER_BASE_URL` (default
`https://openrouter.ai/api/v1`). Centralize the cost/latency knobs as constants on `Config`:
`recursion_limit=40`, `max_iterations=12`, `run_timeout=120` (seconds), plus the attribution headers
(`HTTP-Referer`, `X-Title`). The model slug lives in exactly one constant so a free-tier withdrawal
is a one-line change (`research.md:567`). Startup `GET /api/v1/models` membership check for the slug
is optional here; record as a Phase-3 follow-up.

#### 1.4 Makefile + make.sh helper

**Files**: `reviewer-target-o-meter/Makefile`, `reviewer-target-o-meter/make.sh`

**Intent**: Encapsulate the everyday interactions (lint/static checks, unit tests, the LLM-enabled
test set, and running the app with a directory argument) behind short, self-documenting commands —
so developers and CI invoke one entry point instead of recalling long `uv run` incantations. The
`make.sh` wrapper exists because passing a directory argument is ergonomic positionally
(`./make.sh run <dir>`) where `make` requires `DIR=` syntax.

**Contract**: A `Makefile` with `.PHONY: check test llm-test run help`, all targets invoking `uv run`
from the package dir (where `pyproject.toml` lives):
- `check` → `uv run ruff check && uv run mypy src` (linters + static type verification).
- `test` → `uv run pytest -m "not smoke"` (all unit tests; excludes the live LLM smoke set).
- `llm-test` → `SMOKE=1 uv run pytest -m smoke` (the separate LLM-enabled set; live OpenRouter,
  opt-in, run on the system — not in default CI). Needs `OPENROUTER_API_KEY`.
- `run` → `uv run reviewer-target-o-meter "$(DIR)"`, guarded so a missing `DIR` errors with a
  usage message (`make run DIR=/path/to/checkout`).
- `help` → prints the target list.

A thin `make.sh` (chmod +x) delegates to `make` for the param-less targets and accepts a positional
dir for `run`, so `./make.sh run <dir>` ⇄ `make run DIR=<dir>`; `./make.sh {check|test|llm-test|help}`
pass straight through. The Makefile is the single source of truth; `make.sh` only translates args
(no duplicated command logic). Targets come online as their dependencies land: `check`/`test` work
after Phase 1; `llm-test` after Phase 2 (the smoke test); `run` after Phase 3 (the CLI).

```makefile
.PHONY: check test llm-test run help

check:          ## linters + static type verification
	uv run ruff check
	uv run mypy src

test:           ## unit tests (excludes the live LLM smoke set)
	uv run pytest -m "not smoke"

llm-test:       ## live OpenRouter smoke set (needs OPENROUTER_API_KEY; run on the system)
	SMOKE=1 uv run pytest -m smoke

run:            ## run the app: make run DIR=/path/to/checkout
	@test -n "$(DIR)" || { echo "Usage: make run DIR=/path/to/checkout"; exit 2; }
	uv run reviewer-target-o-meter "$(DIR)"

help:           ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/ :.*##/:/' | column -t -s ':'
```

### Success Criteria:

#### Automated Verification:

- `uv sync` succeeds and `uv.lock` pins the resolved set.
- `uv run pytest` (schema-validator unit tests) passes: `end_line < line` rejected; absolute `file`
  rejected; `fixes` >2 rejected; two-option-without-exactly-one-`recommended` rejected; `is_flagged`
  true for CRITICAL/WARNING, false for OBSERVATION; `exit_code` is 0 on empty/all-OBSERVATION and 1
  when any CRITICAL/WARNING present.
- `uv run mypy src` passes.
- `uv run ruff check` passes.
- `make check` (from the package dir) runs ruff + mypy and exits 0.
- `make test` runs the unit tests (smoke excluded) and exits 0.
- `make help` lists `check`, `test`, `llm-test`, `run`; `./make.sh check`/`test` delegate correctly.

#### Manual Verification:

- Schema field set matches the full impl-review shape (Severity/Impact/Dimension/Title/Location/Detail/Fix)
  and visibly excludes `Decision: PENDING`.
- `is_flagged` does not appear in `FindingsReport.model_json_schema()` output (confirm the model cannot
  see the signal mapping).

**Implementation Note**: After Phase 1's automated verification passes, pause for manual confirmation
before proceeding to Phase 2.

---

## Phase 2: Provider Wiring + Structured-Output Smoke

### Overview

Wire OpenRouter via `ChatOpenAI(base_url=...)` and prove the free model emits a valid **full-shape**
`FindingsReport` through `with_structured_output(..., method="json_schema", strict=True)`. This is the
de-risking gate: if the free model cannot reliably emit the full schema, adjust here (before building
the graph).

### Changes Required:

#### 2.1 Provider factory

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/provider.py`

**Intent**: Build the LLM client from `Config`, OpenAI-compatible against OpenRouter, deterministic.

**Contract**: A `build_llm(config: Config) -> ChatOpenAI` returning
`ChatOpenAI(model=config.model, base_url=config.base_url, api_key=config.api_key,
temperature=0, default_headers=config.attribution_headers)`. Import:
`from langchain_openai import ChatOpenAI` (`research.md:296-308`, `research.md:546-557`). Never hardcode
the key; never echo it. `temperature=0` for the "consistent across re-runs" NFR (`prd.md:97`).

#### 2.2 Structured-output wrapper + host-side re-validation

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/provider.py`

**Intent**: Give the graph a single callable that returns a validated `FindingsReport`, degrading
safely on parse failure (OQ#1 fail-safe).

**Contract**: A `build_structured_llm(config)` returning
`build_llm(config).with_structured_output(FindingsReport, method="json_schema", strict=True,
include_raw=True)`. `include_raw=True` so a parse failure is catchable rather than raising. Add a
`to_report(result) -> FindingsReport` helper that runs `FindingsReport.model_validate(...)` on the
parsed payload and, on any `ValidationError`, returns an empty `FindingsReport` (exit 0) with a
short warning string in `summary` — the host-side re-check that compensates for free-tier looseness
(`research.md:539-543`, `research.md:593`).

#### 2.3 Live OpenRouter smoke test

**File**: `reviewer-target-o-meter/tests/test_smoke_provider.py`

**Intent**: Prove the end-to-end model→schema contract works against the real free tier — F-01's
central de-risking artifact.

**Contract**: A `@pytest.mark.smoke` test (the `smoke` marker was registered in 1.1; add a conftest
skip rule so it is skipped unless `SMOKE=1` is set). It constructs `Config` from the real env, builds
the structured LLM, sends a trivial review prompt over a hardcoded tiny diff (e.g. a one-line SQL
string-concat), and asserts the result is a `FindingsReport` with `>=1` finding whose required fields
are populated and that survives `model_validate`. The marker excludes it from the default run
(`make test` = `-m "not smoke"`); it is selected only via `make llm-test`.

### Success Criteria:

#### Automated Verification:

- `uv run pytest` (default) still green and **does not** hit the network (smoke skipped).
- `SMOKE=1 uv run pytest -m smoke` passes against real OpenRouter and returns a validated non-empty
  `FindingsReport`.
- `make llm-test` runs the smoke set end-to-end (equiv. to `SMOKE=1 uv run pytest -m smoke`) and exits 0.
- `uv run mypy src` and `uv run ruff check` pass.

#### Manual Verification:

- Inspect the smoke output: confirm the free model populates the **full** shape (Impact + Dimension +
  a FixOption with the grammar) without truncation; note any field it struggles with for S-01 tuning.
- Confirm `OPENROUTER_API_KEY` is never printed anywhere in the run.

**Implementation Note**: After Phase 2's live smoke passes, pause for manual confirmation before
proceeding to Phase 3. If the free model cannot emit the full shape reliably, decide now: trim a field,
or move `MODEL` to a paid slug default.

---

## Phase 3: LangGraph Runtime, Tools & End-to-End Smoke

### Overview

Build the four-node `StateGraph` (deterministic spine + single agentic `checks` sub-graph), the two
subprocess-backed search `@tool`s (ripgrep + ast-grep-with-degrade), the cost/latency bounds and
fail-safe, and the typer CLI that joins everything into one runnable end-to-end path against a fixture.
The `checks` node carries a **minimal** analysis prompt (the full impl-review system prompt is S-01).

### Changes Required:

#### 3.1 Typed graph state

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/state.py`

**Intent**: The Pydantic state passed edge-to-edge (typed spine), with `findings` reduced by add so
the agentic node's output accumulates cleanly.

**Contract**: A `ReviewState(TypedDict)` (or Pydantic `BaseModel`) with `repo_path: str`, `diff: str`
(accepted input — **not** computed here), `context: str | None`, `context_present: bool`,
`plan: str | None`, `findings: list[Finding]` (LangGraph `add` reducer via `Annotated[list[Finding],
add]`), and `messages: list` (for the agent loop). Recall: validation fires on graph input only —
re-validation happens at `report`.

#### 3.2 Search @tool wrappers

**Files**: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/tools/text_search.py`,
`.../structural_search.py`, plus `agent/__init__.py`, `agent/tools/__init__.py`.

**Intent**: Give the agent best-available code-search capability per environment, degrading when a
binary is absent (FR-010 degrade philosophy).

**Contract**: `from langchain.tools import tool`. `text_search(query: str, repo_path: str,
max_count: int = 50) -> str` shells out to `rg` and returns capped stdout; `structural_search(pattern:
str, repo_path: str, lang: str | None = None) -> str` shells out to `sg`. Each **probes `shutil.which`
at call time**: if the binary is missing, return an error string (`"ast-grep unavailable on PATH; use
text_search instead"` / `"ripgrep unavailable on PATH"`) — never raise. Catch
`subprocess.TimeoutExpired`/`FileNotFoundError`; cap output (`[:20000]`); snake_case names; required
type hints; docstrings written for the model. Never name a parameter `config` or `runtime`.

#### 3.3 The four nodes

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Implement `context_load`, `plan_discovery`, `checks`, `report`. The deterministic spine
accepts inputs without computing them; the single agentic node runs a minimal analysis; the report node
serializes, re-validates, and computes the advisory exit.

**Contract**:
- `context_load(state)` — deterministic; reads `repo_path`/`context` from input and sets
  `context_present` (bool). Does **not** walk the checkout to load AGENTS.md/skills/source (F-02).
- `plan_discovery(state)` — deterministic; accepts `plan` from input; sets `plan=None` gracefully if
  absent (plan-tolerance: the agent skips plan-dependent checks — `prd.md:60`). No diff-relative
  discovery (F-02).
- `checks(state, config)` — the **single agentic node**: a `create_agent` sub-graph
  (`from langchain.agents import create_agent`) bound to the structured LLM (2.2) and the two search
  tools (3.2), with `max_iterations≈12`. F-01 gives it a **minimal** system prompt — role: non-interactive,
  read+analyze+emit, no edits/posts/questions; given the diff (+ plan-or-none + context), emit a
  `FindingsReport`. The full impl-review methodology prompt (3 dimensions, grading, finding grammar) is
  S-01. Read-and-flag only: the prompt must instruct the agent **not** to execute the reviewed project's
  test/lint commands (`prd.md:118`).
- `report(state)` — deterministic; `FindingsReport.model_validate(...)` the agent payload (the load-bearing
  re-check), inject `F{n}` ids, sort CRITICAL→WARNING→OBSERVATION, cap at 10, serialize to stdout JSON
  (FR-007 stdout default), compute `exit_code` (0 if no flagged else 1 — FR-008 advisory), emit remaining
  budget. `include_raw=True` → empty report + exit 0 on parse failure (OQ#1).

#### 3.4 Graph wiring, bounds, and recursion probe

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/graph.py`

**Intent**: Assemble the typed spine + agentic leaf into one `StateGraph`, with cost/latency bounds and
the fail-safe that catches `GraphRecursionError`.

**Contract**: `from langgraph.graph import StateGraph, START, END`; `from langgraph.errors import
GraphRecursionError`; `from langgraph.types import RetryPolicy, TimeoutPolicy`. Build
`START → context_load → plan_discovery → checks → report → END`. Invoke with
`graph.invoke(inputs, {"recursion_limit": config.recursion_limit, ...})`; layer
`TimeoutPolicy(run_timeout=config.run_timeout)` on `checks` and a bounded `RetryPolicy` on
OpenRouter-calling nodes. Wrap invoke in a helper that catches `GraphRecursionError` → returns a partial
report + advisory exit (OQ#1). Include a ~10-line **recursion probe** (a unit test that runs the inner
agent to `max_iterations` and observes whether the outer `recursion_limit` is consumed) to confirm the
interplay assumption before finalizing bounds (D-SubAgentRecursion, `research.md:477-479`).

#### 3.5 typer CLI entrypoint + fixture

**Files**: `reviewer-target-o-meter/src/reviewer_target_o_meter/cli.py`, update `.../__init__.py`,
`reviewer-target-o-meter/tests/fixtures/` (tiny fixture checkout + diff), `tests/test_graph.py`,
`tests/test_tools.py`.

**Intent**: The single console command (FR-001) that joins the pipeline end-to-end, and the tests that
prove it runs.

**Contract**: A typer app `reviewer-target-o-meter <repo-path>` that builds `Config` from env, assembles
the fixture `(diff, context, plan)` inputs (F-01 accepts them; real pipeline is F-02), invokes the graph,
prints the report JSON, and `sys.exit(report.exit_code)`. Keep `[project.scripts]` pointed at the entry
(`__init__.py:main` delegates to `cli.app`). `test_tools.py` exercises both `@tool`s with **mocked
subprocess** (incl. the missing-binary degrade path). `test_graph.py` runs the graph end-to-end with a
**mocked** LLM (deterministic, offline) asserting nodes fire in order and `report` re-validates +
emits advisory exit; the recursion-probe test lives here too.

### Success Criteria:

#### Automated Verification:

- `uv run pytest` green: tool tests (incl. missing-`sg` degrade) and graph tests (mocked LLM) pass; the
  live smoke remains skipped by default.
- The recursion-probe test documents the confirmed inner-vs-outer recursion interplay.
- `uv run reviewer-target-o-meter <fixture-dir>` (mocked or live) prints valid `FindingsReport` JSON and
  exits 0/1 advisory.
- `make run DIR=<fixture-dir>` (and `./make.sh run <fixture-dir>`) produce the same output as the bare
  console command; `make run` with no `DIR` exits non-zero with a usage message.
- `uv run mypy src` and `uv run ruff check` pass.

#### Manual Verification:

- Run `SMOKE=1 uv run reviewer-target-o-meter <fixture-dir>` end-to-end against real OpenRouter: confirm
  a real validated full-shape report reaches stdout and the exit code is advisory.
- Confirm `GraphRecursionError`/timeout paths emit a partial report + advisory exit (force a tiny
  `recursion_limit` to trigger).
- Confirm no secrets/source spans are echoed beyond the analysis call (`prd.md:44`).

**Implementation Note**: After Phase 3's automated + manual verification passes, pause before Phase 4.

---

## Phase 4: Compensation Owed — `AGENTS.md`

### Overview

Pay down the `quality_override` debt (`tech-stack.md:148-163`): a repo-root `AGENTS.md` that captures the
pinned versions, canonical import paths, graph convention, severity/anchor rules, and the review-output
checklist — so future agents read it once and stay unblocked.

### Changes Required:

#### 4.1 Repo-root AGENTS.md

**File**: `AGENTS.md` (git root)

**Intent**: The single onboarding doc that neutralizes the stack's main risks (docs churn, agent-judgment
not yet built) and records every locked decision.

**Contract**: Sections — (a) **Pinned versions** + exact import paths (paste `research.md:154-163`), with
the rule "trust `uv.lock` + these import paths over web search"; (b) **Graph convention** — one node per
FR-006 phase, deterministic spine + single agentic `checks` node, Pydantic state is input-validation-only
→ re-validate at `report`, `@tool`s never raise and degrade on missing binaries; (c) **Severity taxonomy +
line-anchor rules** (CRITICAL/WARNING/OBSERVATION, `is_flagged` hidden `@property`, `line` required,
file repo-relative, exit 0/1 advisory); (d) **Locked decisions** from this plan (ChatOpenAI/base_url,
json_schema+strict, read-and-flag-only, single checks node, both-tools-degrade, full schema shape); (e)
**Review-output checklist** the developer uses to sanity-check agent findings before posting (builds the
"can judge agent output" muscle — `tech-stack.md:159-161`); (f) **ast-grep GHA install recipe** (the
`sg` setup step + the degrade-to-ripgrep note) recorded so S-02 doesn't re-discover it
(`tech-stack.md:131-132`); (g) **Developer commands** — point to `make check` / `make test` /
`make llm-test` / `make run DIR=<path>` (and the `./make.sh` wrapper) as the canonical entry points.

#### 4.2 Update change.md status

**File**: `context/changes/agent-runtime-finding-schema/change.md`

**Intent**: Reflect that planning is complete.

**Contract**: Set `status: planned` and `updated: 2026-08-01`.

### Success Criteria:

#### Automated Verification:

- `uv run ruff check && uv run mypy src && uv run pytest` all still green (docs-only change).
- `AGENTS.md` exists at the repo root.

#### Manual Verification:

- Every "Compensation owed" bullet in `tech-stack.md:148-163` is covered by an `AGENTS.md` section.
- A fresh reader can locate the pinned versions, the graph convention, and the severity rules without
  reading `research.md`.

**Implementation Note**: Phase 4 is the final phase; once it passes, F-01 is ready for `/10x-impl-review`
and hand-off to F-02/S-01.

---

## Testing Strategy

### Unit Tests:

- **Schema** (`test_findings.py`): every validator (`end_line>=line`, absolute-path rejection, `fixes`
  cap + recommended-rule), `is_flagged`, `exit_code`.
- **Tools** (`test_tools.py`): both `@tool`s with **mocked subprocess**; the missing-binary degrade path
  (no `sg` → error string, no raise); output capping.
- **Graph** (`test_graph.py`): node ordering with a **mocked LLM**; `report` re-validation + advisory exit
  on a flagged vs all-OBSERVATION report; the recursion probe.

### Integration Tests:

- **End-to-end smoke** (`test_smoke_provider.py`, Phase 2) and the CLI run (Phase 3) — live OpenRouter,
  opt-in via `make llm-test` (equiv. `SMOKE=1 uv run pytest -m smoke`), excluded from the default run.

### Manual Testing Steps:

1. `make llm-test` — confirm a real validated full-shape report returns against OpenRouter.
2. `make run DIR=<fixture-dir>` (or `./make.sh run <fixture-dir>`) — confirm JSON to stdout + advisory exit.
3. Force `recursion_limit=2` — confirm partial report + advisory exit (fail-safe).
4. Unset `ast-grep` on PATH — confirm `structural_search` degrades and the agent falls back to `text_search`.
5. Grep the run output — confirm `OPENROUTER_API_KEY` never appears.

## Performance Considerations

- The model is free, so the **$-per-review cap is moot** (OQ#2 re-scoped, `research.md:569-573`); the
  binding constraint is the **~5-min wall-clock NFR** (`prd.md:98`). Enforced via `recursion_limit≈40`,
  inner `max_iterations≈12`, and `TimeoutPolicy(run_timeout=120)` on `checks`.
- Design the graph so heavy context sits in a **cacheable prefix** (OpenRouter's ~99% cached-prompt
  discount makes repeated repo context across agent steps nearly free — `research.md:431-433`).
- Reasoning tokens count against `max_completion_tokens` and inflate latency — set generous `max_tokens`
  so JSON doesn't truncate mid-generation (`research.md:316-319`).

## Migration Notes

None — greenfield; the baseline is an empty `uv init` scaffold. No existing data or systems to migrate.
`AGENTS.md` is new; no prior agent-instructions file to reconcile.

## References

- Research: `context/changes/agent-runtime-finding-schema/research.md`
- F-01 outcome + risk: `context/foundation/roadmap.md:51-63`
- PRD FRs/NFRs/Non-Goals: `context/foundation/prd.md:79-92,96-99,117-119`
- Locked stack + compensation owed: `context/foundation/tech-stack.md:57-79,148-163`
- Methodology (provenance): `/home/krzysztofkruk/.agents/skills/10x-impl-review-ci/references/impl-review-instructions.md`
- Baseline: `reviewer-target-o-meter/pyproject.toml`, `reviewer-target-o-meter/src/reviewer_target_o_meter/__init__.py:1`
- Env config: `reviewer-target-o-meter/.env.example`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename
> step titles.

### Phase 1: Dependencies, Config & Typed Schema

#### Automated

- [x] 1.1 `uv sync` succeeds; `uv.lock` pins langchain/langgraph/langchain-openai/langchain-core/pydantic/typer/gitpython + dev (pytest/ruff/mypy); `smoke` marker registered
- [x] 1.2 `uv run pytest` schema-validator unit tests pass (end_line, absolute-path, fixes cap, is_flagged, exit_code)
- [x] 1.3 `uv run mypy src` passes
- [x] 1.4 `uv run ruff check` passes
- [x] 1.5 `Makefile` + `make.sh` exist; `make check` (ruff+mypy) and `make test` (unit, smoke excluded) exit 0; `make help` lists targets; `./make.sh check` delegates

#### Manual

- [x] 1.5 Confirm schema field set = full impl-review shape and excludes `Decision: PENDING`
- [x] 1.6 Confirm `is_flagged` absent from `FindingsReport.model_json_schema()` output

### Phase 2: Provider Wiring + Structured-Output Smoke

#### Automated

- [ ] 2.1 `uv run pytest` (default) green and does not hit the network (smoke skipped)
- [ ] 2.2 `SMOKE=1 uv run pytest -m smoke` passes against real OpenRouter, returns validated non-empty `FindingsReport`
- [ ] 2.3 `make llm-test` runs the smoke set end-to-end (equiv. `SMOKE=1 uv run pytest -m smoke`) and exits 0
- [ ] 2.4 `uv run mypy src` passes
- [ ] 2.5 `uv run ruff check` passes

#### Manual

- [ ] 2.6 Inspect smoke output — free model populates the full shape without truncation; note struggles for S-01
- [ ] 2.7 Confirm `OPENROUTER_API_KEY` never printed

### Phase 3: LangGraph Runtime, Tools & End-to-End Smoke

#### Automated

- [ ] 3.1 `uv run pytest` green: tool tests (incl. missing-`sg` degrade) + graph tests (mocked LLM) pass; smoke still skipped by default
- [ ] 3.2 Recursion-probe test documents confirmed inner-vs-outer recursion interplay
- [ ] 3.3 `uv run reviewer-target-o-meter <fixture-dir>` prints valid `FindingsReport` JSON + exits 0/1 advisory
- [ ] 3.4 `make run DIR=<fixture-dir>` and `./make.sh run <fixture-dir>` match the bare console command; `make run` w/o `DIR` errors with usage
- [ ] 3.5 `uv run mypy src` passes
- [ ] 3.6 `uv run ruff check` passes

#### Manual

- [ ] 3.7 `SMOKE=1 uv run reviewer-target-o-meter <fixture-dir>` end-to-end — real validated full-shape report to stdout + advisory exit
- [ ] 3.8 Force tiny `recursion_limit` — partial report + advisory exit (fail-safe confirmed)
- [ ] 3.9 Confirm no secrets/source spans echoed beyond the analysis call

### Phase 4: Compensation Owed — `AGENTS.md`

#### Automated

- [ ] 4.1 `uv run ruff check && uv run mypy src && uv run pytest` still green (docs-only)
- [ ] 4.2 `AGENTS.md` exists at repo root

#### Manual

- [ ] 4.3 Every `tech-stack.md:148-163` "Compensation owed" bullet covered by an `AGENTS.md` section
- [ ] 4.4 Fresh reader can locate pinned versions, graph convention, severity rules, and developer commands (`make check/test/llm-test/run`) without reading `research.md`
