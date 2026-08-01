---
date: 2026-08-01T18:40:07+02:00
researcher: Krzysztof Kruk (via opencode, model glm-5.2)
git_commit: 126828260d3db7415f22b85fe4c17192d9acaf03
branch: master
repository: reviewer-target-o-meter
topic: "F-01 — reviewer agent runtime (LangChain Agent module + LangGraph), typed Finding/Severity Pydantic schema, OpenRouter provider wiring (deepseek/deepseek-v4-pro), and the /10x-impl-review-ci → FR-006 methodology mapping"
tags: [research, codebase, f-01, agent-runtime, langgraph, langchain, openrouter, deepseek, pydantic, finding-schema, impl-review-ci]
status: complete
last_updated: 2026-08-01
last_updated_by: Krzysztof Kruk
last_updated_note: "Follow-up (2026-08-01): F-01 default model settled on nvidia/nemotron-3-super-120b-a12b:free (free; tools + structured_outputs + response_format all yes; 262k ctx). The earlier Ultra-free pick was dropped because it lacks structured_outputs. See 'Follow-up Research'."
---

# Research: F-01 — Agent runtime + Finding/Severity schema + OpenRouter wiring

**Date**: 2026-08-01T18:40:07+02:00 (CEST)
**Researcher**: Krzysztof Kruk (via opencode, model glm-5.2)
**Git Commit**: `126828260d3db7415f22b85fe4c17192d9acaf03` (short `1268282`, "Init repo")
**Branch**: `master`
**Repository**: `reviewer-target-o-meter`

> **Permalinks:** the repo has **no git remote** configured (`git remote -v` is empty),
> so GitHub permalinks cannot be generated. All references below are local `path:line`.
> Re-run `/10x-research` (or hand-edit) to convert to permalinks once a remote is added
> and the commit is pushed.

## Research Question

> Research **F-01 (agent-runtime-finding-schema)** from `context/foundation/roadmap.md`,
> using the LangChain Agent module (https://docs.langchain.com/oss/python/langchain/agents)
> as an implementation lens, with model `deepseek/deepseek-v4-pro` as the default, and the
> reviewer agent's methodology/system-prompt drawn from the `/10x-impl-review-ci` skill.

Scope locked with the requester: **plan-ready deep dive**, all four focus areas —
(agent architecture · Finding/Severity schema · provider+model verification ·
impl-review→FR-006 map). This is **research only**; no code was written or installed.

## Summary

Four parallel read-only sub-agents investigated the four focus areas. The headline verdicts:

1. **The model is real.** `deepseek/deepseek-v4-pro` is a **verified, live OpenRouter slug**
   (released 2026-04-24; 1.6T-total/49B-active MoE; 1M context; $0.435/$0.87 per 1M tok;
   supports `tools`, `tool_choice`, `structured_outputs`, `response_format`). It is, in fact,
   an excellent fit for an agentic code-reviewer. My incoming suspicion that it was a
   hallucination was **wrong** — confirmed against `GET https://openrouter.ai/api/v1/models`
   and https://openrouter.ai/deepseek/deepseek-v4-pro . Fallback: `deepseek/deepseek-v4-flash`
   (~3× cheaper, same capabilities).

2. **Agent module vs LangGraph is not a conflict — they coexist.** The locked decision
   (`tech-stack.md:67-71`) is a **LangGraph `StateGraph` with one node per FR-006 phase**.
   The LangChain Agent module (`create_agent`) *returns a compiled LangGraph graph* — so it
   is a **sub-component**, not an alternative. Recommended shape: explicit `StateGraph` spine
   (deterministic `context-load → plan-discovery → report` nodes) with a `create_agent`
   sub-agent embedded **inside the `checks` node** — that is where "an agent that interacts
   with the codebase" (the user's Agent-module directive) actually lives.

3. **The methodology maps 1:1 onto FR-006.** FR-006 *is* `/10x-impl-review-ci` Steps 0–5
   (`SKILL.md:32-152`) + the entirety of `references/impl-review-instructions.md`. The skill's
   three parallel evidence subagents become three LangGraph analysis nodes (drift /
   safety-quality-patterns / test-coverage). **Provenance of OQ#7 is resolved:** the
   methodology is the impl-review-ci skill itself. Steps 6–9 (commit/MCP-inline/summary
   comment/`gh` CLI) are **out of scope** — they belong to slice S-02.

4. **Severity taxonomy adopted (resolves OQ#3):** `CRITICAL / WARNING / OBSERVATION`
   (inherited from impl-review-ci). The hardcoded signal mapping (FR-011) is a plain
   `@property` `Severity.is_flagged` → `CRITICAL|WARNING` flagged, `OBSERVATION` info-only.
   Advisory exit code (FR-008): `0` if no flagged findings, `1` otherwise.

5. **Versions pinned (pays the `quality_override` debt):** `langchain==1.3.14`,
   `langgraph==1.2.10`, `langchain-openai==1.4.1`, `langchain-core` floats to the resolved
   bound (record exact set in `uv.lock` + AGENTS.md). All post-1.0, mutually compatible,
   Python ≥3.10 (project's `requires-python=">=3.14"` is fine).

6. **One genuine cross-cutting tension for `/10x-plan` to resolve:** the impl-review
   methodology's finding shape (Severity + Impact + 7-dimension + Fix-options grammar) is
   **richer** than the PRD's stated "severity + file/line + rationale" — adopt the full shape
   (keeps provenance 1:1) or trim to a minimal set (lower cost/tokens)? Both sub-agents
   flagged this; see Open Decision **D-SchemaRichness**.

7. **Baseline nuance:** the Python package lives in a **nested** `reviewer-target-o-meter/`
   subdir; the `context/` planning docs live at the git root. F-01 code goes under
   `reviewer-target-o-meter/src/reviewer_target_o_meter/`.

## Detailed Findings

### 1. Architecture — LangChain Agent module + LangGraph

**The two abstractions are different layers of the same stack, not alternatives.**
From the LangGraph overview: *"LangChain agents are built on top of LangGraph… If you are
just getting started… we recommend you use LangChain's agents that provide prebuilt
architectures."* And from the Agents page: *"`create_agent` is a highly configurable
harness… Behind the scenes that passes an update to the agent's State… especially useful
when embedding the agent as a **subgraph**."* `create_agent(...)` returns a compiled
LangGraph graph — so dropping it inside a node is the supported composition.

**Recommended graph (one node per FR-006 phase, `tech-stack.md:67-71`):**

| Node | Type | Job | PRD ref |
|---|---|---|---|
| `context_load` | deterministic | Load AGENTS.md/skills/source; set `context_present` | FR-004 |
| `plan_discovery` | deterministic | Find `plan.md` (or None) | FR-006 |
| `checks` | **agentic (`create_agent` sub-graph)** | drift/safety/pattern analysis over the diff via `@tool`s; emit `Finding[]` | FR-006 |
| `report` | deterministic | serialize → stdout JSON; advisory exit code | FR-007/008/009 |

Edges: `START → context_load → plan_discovery → checks → report → END`.
Conditional logic (plan-tolerance, FR-006/FR-010) lives **inside `checks`** as prompt/tool
selection (not a separate graph branch), keeping the graph 1:1 with FR-006. The three
impl-review dimensions become **three parallel analysis calls** (fan-out from plan-load,
fan-in to grade) — matching the skill's 3-subagent dispatch (`SKILL.md:100-124`) → Open
Decision **D-ParallelDims**.

**Typed Pydantic state (edge-to-edge, `tech-stack.md:156-158`)** — `ReviewState`:
`repo_path`, `diff`, `context`, `context_present`, `plan`, `findings: list[Finding]` (reducer
= add), `messages`. ⚠️ **Gotcha (record in AGENTS.md):** Pydantic-state run-time validation
fires **only on graph input**, not per-node output (node outputs come back as plain dicts).
So the severity/anchor schema **must be re-validated at the `report` node** boundary.

**`@tool` wrappers (ast-grep + ripgrep — PATH deps, subprocess-backed, `tech-stack.md:112-116`):**
canonical import `from langchain.tools import tool` (same object as `langchain_core.tools.tool`
— standardize on the former and document both). Conventions: type hints required (they define
the input schema); docstrings are the **LLM-visible** description (write for the model); never
raise — catch `subprocess.TimeoutExpired`/`FileNotFoundError` and return an error string;
cap output size (e.g. `[:20000]`, `--max-count`) for the context budget; snake_case names
(some providers reject other chars). Reserved tool-arg names: **`config` and `runtime`** —
do not name any parameter these. Tool groups (`tech-stack.md:156-158`):
`agent/tools/{structural_search.py (ast-grep), text_search.py (ripgrep), github.py (S-02)}`.

**Cost ceiling (OQ#2, `roadmap.md:121`):** LangGraph bounds execution via
`recursion_limit` (default 25 supersteps — too loose here) passed in config:
`graph.invoke(inputs, {"recursion_limit": N})`; raises `GraphRecursionError` (import
`from langgraph.errors import GraphRecursionError`). The inner `create_agent` is bounded by
its `max_iterations`. **Recommended defaults:** inner `max_iterations ≈ 12`; outer
`recursion_limit ≈ 40` (chain of 4 + inner budget ×2 — each iteration ≈ 2 supersteps). Layer
`TimeoutPolicy(run_timeout=120)` on `checks` (enforces the ~5-min NFR, `prd.md:98`) and a
bounded `RetryPolicy` on OpenRouter-calling nodes. Emit remaining-budget in the report. Catch
`GraphRecursionError` → partial report + advisory exit (ties to OQ#1 fail-safe).

**Pinned versions (verified PyPI, 2026-08-01):**

| Package | Pin | Source |
|---|---|---|
| `langchain` | `==1.3.14` | pypi.org/project/langchain (Jul 16 2026) |
| `langgraph` | `==1.2.10` | pypi.org/project/langgraph (Jul 28 2026) |
| `langchain-openai` | `==1.4.1` | pypi.org/project/langchain-openai (Jul 23 2026) |
| `langchain-core` | float → resolved | let `uv` resolve; record exact in `uv.lock` |

All declare `Python >=3.10`; project's `>=3.14` is compatible. The LangChain 1.x line
(Oct 2025 GA) moved many import paths — 0.x web examples are now stale; AGENTS.md must
instruct agents to **trust `uv.lock` + the recorded import paths over web search** (this is
exactly the `tech-stack.md:153-155` failure mode).

**Canonical import paths (paste into AGENTS.md):**
```python
from langgraph.graph import StateGraph, START, END
from langgraph.errors import GraphRecursionError
from langgraph.types import Command, RetryPolicy, TimeoutPolicy
from langchain.agents import create_agent, AgentState      # used INSIDE the checks node
from langchain.tools import tool, ToolRuntime
from langchain.messages import SystemMessage, HumanMessage, ToolMessage, AnyMessage
from langchain_openai import ChatOpenAI                     # OpenRouter via base_url
```

### 2. Finding / Severity schema (Pydantic v2)

**Severity taxonomy (resolves OQ#3, `prd.md:129` / `roadmap.md:122`):** adopt the
impl-review-ci levels `CRITICAL / WARNING / OBSERVATION` as a `str, Enum`. Free alignment
with the inherited methodology; the skill's sort order (`SKILL.md:150`) is reused. Rejected
`critical/warning/info`: "observation" fits a non-blocking advisory tool better than
"informational".

**Hardcoded signal mapping (FR-011, `prd.md:91-92`):** a plain `@property` on `Severity`
(not `@computed_field`, so it is **not** emitted into the JSON schema the model sees — the
model picks the enum value; the **tool**, not the model, decides the signal):

| Severity | `is_flagged` | Stdout JSON | Posted (S-02) | Exit code |
|---|---|---|---|---|
| `CRITICAL` | True | always | inline annotation | non-zero |
| `WARNING` | True | always | inline annotation | non-zero |
| `OBSERVATION` | False | always | summary only | `0` |

**Advisory exit code (FR-008):** `0` if no flagged findings, `1` if ≥1 flagged. Advisory
only — must NOT block merges (`prd.md:83-84,117`). (0/1 vs richer 0/2 is a plan micro-decision.)

**Proposed Pydantic v2 schema** (`src/reviewer_target_o_meter/findings.py`):

```python
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Severity(str, Enum):
    CRITICAL = "critical"; WARNING = "warning"; OBSERVATION = "observation"
    @property
    def is_flagged(self) -> bool:           # FR-011 hardcoded mapping
        return self in (Severity.CRITICAL, Severity.WARNING)

class Dimension(str, Enum):                  # inherited 7-value taxonomy (SKILL.md:181-189)
    PLAN_ADHERENCE="plan_adherence"; SCOPE_DISCIPLINE="scope_discipline"
    SAFETY_QUALITY="safety_quality"; ARCHITECTURE="architecture"
    PATTERN_CONSISTENCY="pattern_consistency"; TEST_COVERAGE="test_coverage"
    SUCCESS_CRITERIA="success_criteria"

class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)
    file: str = Field(..., min_length=1,
        description="Repo-relative path, e.g. 'src/auth/handler.py'. Required (FR-009).")
    line: int = Field(..., ge=1, description="1-based line. Required on every finding (FR-009).")
    end_line: int | None = Field(default=None, ge=1, description="Optional inclusive end line.")
    severity: Severity = Field(..., description="critical|warning|observation.")
    rationale: str = Field(..., min_length=1,
        description="Concrete risk/drift grounded in diff/plan/context. Never quote secrets "
                    "or large source spans verbatim (guardrail, prd.md:44).")
    title: str = Field(..., min_length=1, max_length=120, description="One-line summary.")
    dimension: Dimension | None = Field(default=None, description="Optional review dimension.")
    fix_hint: str | None = Field(default=None,
        description="Optional short suggested direction (NOT an applied patch).")

    @model_validator(mode="after")
    def _end_line_ge_line(self) -> "Finding":
        if self.end_line is not None and self.end_line < self.line:
            raise ValueError("end_line must be >= line")
        return self

    @field_validator("file")
    @classmethod
    def _no_absolute_path(cls, v: str) -> str:           # partial leakage defense
        if v.startswith("/"):
            raise ValueError("file must be repo-relative, not absolute")
        return v

class FindingsReport(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    summary: str | None = None
    @property
    def flagged(self) -> list[Finding]:
        return [f for f in self.findings if f.severity.is_flagged]
    @property
    def exit_code(self) -> int:                          # FR-008 advisory
        return 1 if self.flagged else 0
```

**Why single-line required + optional range:** FR-009 demands an anchor on *every* finding, so
`line` is required. GitHub's `POST /pulls/:n/comments` accepts a single `line` or a range
(`start_line`+`line` on `side=RIGHT`) → `end_line` maps cleanly to S-02 posting regardless of
the still-open posting-format OQ#8. `frozen=True` prevents mutation between nodes; the
absolute-path validator is a partial leakage defense.

**Machine validation via structured output:** `ChatOpenAI(...).with_structured_output(
FindingsReport, method="json_schema", strict=True)` returns a validated instance; the `report`
node calls it. Use `include_raw=True` so a parse failure degrades to empty-report + exit 0 +
warning (ties to OQ#1) instead of raising. **Requirement:** the model must support tool-calling
or json-schema mode — confirmed for `deepseek/deepseek-v4-pro` (§3).

**impl-review richer fields — carry now or defer?** (see Open Decision **D-SchemaRichness**):
the schema sub-agent recommended a **minimal** set (title + optional dimension + optional
fix_hint; defer `Impact` and the Fix-grammar Strength/Tradeoff/Confidence/Blind spot and
`Decision:PENDING`). The methodology sub-agent recommended adopting the **full** shape (keeps
provenance 1:1, aids reviewer triage). Both agree the `Decision: PENDING` field is
**CI-harness-triage-only** (`SKILL.md:152,164,500`) and should be **excluded**. Resolution
belongs to `/10x-plan`; lean minimal for v1 cost control, revisit if signal quality demands.

**Leakage guardrail (`prd.md:44`):** (a) field-description notes already reach the LLM via the
JSON schema; (b) absolute-path validator; (c) bounded text length (`title` ≤120); (d)
recommended (defer-or-now) host-side secret-pattern redaction over rationale/fix_hint/title,
mirroring `SKILL.md:505`. Note S-01 stdout-only mode writes nothing to the host, so leakage
risk is concentrated in S-02 posting.

### 3. Provider wiring + model verification

**VERDICT — `deepseek/deepseek-v4-pro` is REAL. ✅** Verified live
(`GET https://openrouter.ai/api/v1/models`, record `id: "deepseek/deepseek-v4-pro"`;
marketing page https://openrouter.ai/deepseek/deepseek-v4-pro "DeepSeek V4 Pro", released
2026-04-24, 1.6T total / 49B activated MoE, 1M context). Catalog description: *"designed for
advanced reasoning, coding, and long-horizon agent workflows… well suited for… full-codebase
analysis, multi-step automation."* My initial suspicion it was hallucinated was **wrong**.

**DeepSeek slugs on OpenRouter (all `text→text`, all support tools + structured output except
the distill):**

| Slug | Context | $/1M in | $/1M out | tools | struct-out |
|---|---|---|---|---|---|
| **`deepseek/deepseek-v4-pro`** (recommended) | 1,048,576 | $0.435 | $0.87 | ✅ | ✅ |
| `deepseek/deepseek-v4-flash` (cheaper fallback) | 1,048,576 | $0.14 | $0.28 | ✅ | ✅ |
| `deepseek/deepseek-v3.2` | 163,840 | $0.269 | $0.40 | ✅ | ✅ |
| `deepseek/deepseek-chat` (V3 non-reasoning) | 163,840 | $0.2574 | $1.0287 | ✅ | ✅ |
| `deepseek/deepseek-r1` (reasoning) | 163,840 | $0.70 | $2.50 | ✅ | ✅ |
| `deepseek/deepseek-r1-distill-llama-70b` | 8,192 | $0.80 | $0.80 | ❌ | ❌ |

**Recommended default:** `deepseek/deepseek-v4-pro` (as specified) — 1M context, tools +
structured output, built for coding/agents. **Fallback / cost-saver:** `deepseek/deepseek-v4-flash`
(same 1M ctx, ~3× cheaper) — good `--model` override or for cheap re-runs. **Avoid**
`deepseek-r1-distill-*` (8k ctx, no tools/structured output — would break F-01).

**Wiring (OpenAI-compatible, `tech-stack.md:62-64,96-97`):**
```python
import os
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(
    model="deepseek/deepseek-v4-pro",
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],          # runtime-only, never hardcoded
    default_headers={                                    # optional (attribution)
        "HTTP-Referer": "https://github.com/<owner>/reviewer-target-o-meter",
        "X-Title": "reviewer-target-o-meter",
    },
)
```
OpenRouter: *"OpenRouter's API is OpenAI-compatible — most SDKs work by just swapping the
base URL."* Routing-mode note: prefer **Exacto** routing for the tool-heavy `checks` node
(highest tool-calling accuracy).

**Tool-calling + structured output:** v4-pro advertises `tools`, `tool_choice`,
`structured_outputs`, `response_format` — exactly what `with_structured_output(...)` consumes.
Reasoning tokens are emitted **separately** from the structured payload, so structured output
still returns a clean Pydantic object — but reasoning tokens **count against
`max_completion_tokens`** (cap 384k, generous). Set `max_tokens` high enough that reasoning +
JSON both fit, or JSON truncates mid-generation. Treat `include_reasoning` content as
debug-only — never echo it into posted output (leakage, `prd.md:44`).

**Cost/latency (feeds OQ#2):** cached prompt read $0.003625/1M (≈99% discount — large for
repeated repo context across agent steps). Realistic per-review ≈ **$0.03–0.15** (list);
sub-$0.05 typical with caching. A **$0.50–$1.00 per-review ceiling** gives large headroom for
the ~5-min NFR. Latency: `high`/`xhigh` reasoning is slower; the 5-min wall-clock
(`prd.md:98`) is the binding constraint (mitigate via `reasoning_effort`, diff cap, or
v4-flash). `is_moderated: false` (no OpenRouter-side training) — consistent with the no-leakage
guardrail.

**Provider-wiring divergence (Open Decision **D-ProviderClient**):** `tech-stack.md:96-97,122`
pins `langchain-openai.ChatOpenAI(base_url=...)`. LangChain now also ships a first-class
`langchain-openrouter.ChatOpenRouter` with native `with_structured_output(method=...,
strict=True)` and structured agent `response_format`. `/10x-plan` should decide which F-01
wires (lean `ChatOpenAI(base_url=...)` to honor the locked decision; if switching, update
`tech-stack.md` "Locked decisions" to avoid doc drift).

### 4. impl-review-ci → FR-006 methodology mapping

**FR-006 = `/10x-impl-review-ci` Steps 0–5 (`SKILL.md:32-152`) + the entirety of
`references/impl-review-instructions.md`.** The skill splits: `SKILL.md` is the CI harness
(orchestration); `references/impl-review-instructions.md` is the actual review (dimensions,
checks, grading, finding grammar) — `SKILL.md:18` says Steps 1–5 only orchestrate it.

**Phase ↔ methodology mapping:**

| FR-006 phase | Product behavior | impl-review-ci step | Ref |
|---|---|---|---|
| context-load (FR-004) | read AGENTS.md/skills/source from checkout | (product-specific; skill assumes context present) | `references/...:9-12` |
| plan discovery | find `plan.md` in reviewed project's own checkout; **degrade**, don't exit | Step 0 Find the plan | `SKILL.md:32-74` |
| (load plan + diff) | parse 5 extraction targets; merge-base 3-dot diff; cross-ref | Step 1 | `SKILL.md:76-98`; `references/...:35-41` |
| checks — dim 1 | plan drift MATCH/DRIFT/MISSING/EXTRA | Step 2 → Agent 1 | `references/...:47-56` |
| checks — dim 2 | safety/quality (security/perf/reliability/data) + pattern vs siblings | Step 2 → Agent 2 | `references/...:58-73` |
| checks — dim 3 | test coverage; run plan's test cmds | Step 2 → Agent 3 | `references/...:75-91` |
| (verify success criteria) | run plan's non-test Automated Verification | Step 3 | `SKILL.md:126-138`; `references/...:93-97` |
| report — grade | PASS/WARNING/FAIL ×7; APPROVED/NEEDS ATTENTION/REJECTED | Step 4 | `references/...:99-115` |
| report — compile | sort CRITICAL→WARNING→OBSERVATION; cap 10 | Step 5 | `SKILL.md:146-152` |
| report — emit | **stdout JSON (advisory exit)** — NOT a committed `.md` | Step 6 (adapted) | `SKILL.md:154-220` |
| (post) | **S-02, out of scope** | Steps 7–9 (commit/MCP-inline/summary) | `SKILL.md:222-496` |

**Plan-tolerance (FR-006/FR-010) — the load-bearing behavioral divergence:** the skill
**exits 0** on no plan (`SKILL.md:63-72`); the product must **degrade** (`prd.md:60,79-80,89-90`).
- **Skip on no-plan (plan-dependent):** dim 1 (drift), cross-ref matrix, dim-3 steps 1/2/4/5
  (commitments, artifact-match, run-tests, exclusions), Step 3 (non-test verification), and
  the Plan-Adherence/Scope-Discipline/Success-Criteria grades.
- **Keep running (intrinsic to the diff):** dim 2 (full safety/quality + pattern vs siblings),
  dim-3 step 3 (heuristic uncovered behavior), and the Safety&Quality/Pattern-Consistency grades.
- AGENTS.md/skills absence (FR-010) is an **independent** degradation axis → four combinations
  (context± × plan±). Mark skipped dimensions `SKIPPED (no plan)` so the reviewer sees the
  degraded scope; compute the verdict over surviving dimensions only.

**System-prompt outline (the analysis node's content):** role (non-interactive, read+analyze+emit,
no edits/posts/questions); inputs (diff split source/test, loaded context, plan-or-none,
merge-base range); governing principle (plan = ground truth when present; diff-only when not);
5-target extraction; cross-ref matrix; 3 dimensions; grading; finding shape (Severity +
file:line + rationale, FR-009 mandatory, "N/A" only for MISSING IMPL/TEST); leakage guard
(redact secrets, `SKILL.md:505`); non-generic-actionable rule (`prd.md:96`); determinism note
(`prd.md:97`). Full substance lives in `references/impl-review-instructions.md`.

**OQ#7 provenance — RESOLVED:** the methodology is the `/10x-impl-review-ci` skill
(`references/impl-review-instructions.md` + `SKILL.md` Steps 0–5). **Out of scope (S-02):**
committed `.md` report, `<!-- IMPL-REVIEW-REPORT -->` marker, `Decision: PENDING` field,
git commit/`[skip ci]`, MCP inline comments, summary comment, `gh` CLI/`PR_NUMBER`/
`GITHUB_BASE_REF`, REJECTED→workflow gate. **Tension to resolve (Open Decision
**D-DeterministicChecks**):** dim-3 step 4 + Step 3 *execute* the plan's declared test/lint
commands — the PRD Non-Goal "No own deterministic checks" (`prd.md:118`) says the tool is not a
linter/test-runner. Decide: execute-as-evidence (skill behavior) vs read-and-flag-only.

## Code References

Local (repo has no remote → no permalinks):

- `context/foundation/roadmap.md:51-63` — F-01 outcome, unknowns, risk.
- `context/foundation/roadmap.md:121-123` — OQ#2 (cost ceiling), OQ#3 (severity), OQ#4 (diff cap).
- `context/foundation/prd.md:79-80` — FR-006 (analysis phases, plan-tolerance).
- `context/foundation/prd.md:85-86` — FR-009 (file/line anchor on every finding).
- `context/foundation/prd.md:89-92` — FR-010 (graceful degrade), FR-011 (hardcoded signal mapping).
- `context/foundation/prd.md:96-98` — NFRs (actionable/non-generic; consistent re-runs; ~5-min latency).
- `context/foundation/prd.md:117,127,129,133` — Non-Goal no-merge-blocking; OQ#1 fail-safe; OQ#3 severity; OQ#7 methodology provenance.
- `context/foundation/tech-stack.md:62-64,96-97,137` — OpenRouter locked decision + GHA env (`OPENROUTER_API_KEY`).
- `context/foundation/tech-stack.md:67-71` — LangGraph stateful graph, one node per FR-006 phase.
- `context/foundation/tech-stack.md:112-116` — ast-grep + ripgrep as PATH deps, subprocess-backed `@tool`.
- `context/foundation/tech-stack.md:148-163` — Compensation owed (pin versions, import paths, graph convention, schemas).
- `reviewer-target-o-meter/pyproject.toml:9-13` — baseline: `requires-python=">=3.14"`, `dependencies=[]`, console script.
- `reviewer-target-o-meter/src/reviewer_target_o_meter/__init__.py:1-2` — `main()` Hello stub.
- `/home/krzysztofkruk/.agents/skills/10x-impl-review-ci/SKILL.md:32-152` — Steps 0–5 (the reusable analysis core).
- `/home/krzysztofkruk/.agents/skills/10x-impl-review-ci/SKILL.md:222-496` — Steps 7–9 (S-02, out of scope).
- `/home/krzysztofkruk/.agents/skills/10x-impl-review-ci/references/impl-review-instructions.md` — the review criteria (dimensions, grading, finding grammar).

External (verified live 2026-08-01):
- https://openrouter.ai/api/v1/models — model catalog (deepseek slug verification).
- https://openrouter.ai/deepseek/deepseek-v4-pro — model marketing page.
- https://docs.langchain.com/oss/python/langchain/agents — Agent module (`create_agent`).
- https://docs.langchain.com/oss/python/langgraph — LangGraph (StateGraph, `recursion_limit`).
- https://docs.langchain.com/oss/python/langchain/structured-output — `with_structured_output`.
- https://pypi.org/project/{langchain,langgraph,langchain-openai,langchain-core}/ — version pins.

## Architecture Insights

- **Agent module ⊂ LangGraph.** `create_agent` returns a compiled graph → compose as a sub-graph
  inside the `checks` node. This dissolves the apparent conflict between the user's Agent-module
  directive and the locked LangGraph decision — no `tech-stack.md` re-litigation needed.
- **Deterministic spine + agentic leaf.** `context_load`/`plan_discovery`/`report` are plain
  functions (no LLM loop — cheap, predictable); only `checks` is agentic. This is LangGraph's
  "mix deterministic + agentic" pattern and keeps cost/latency bounded.
- **Pydantic-state is input-validation only.** Re-validate `Finding[]` at the `report` node
  (and via the agent's `response_format=`/`with_structured_output`) — do not rely on per-node
  Pydantic enforcement.
- **The model judges severity; the tool decides signal.** `is_flagged` is a Python `@property`
  not exposed to the LLM — the right boundary for FR-011.
- **Cost ceiling is one knob.** Centralize `recursion_limit` + `max_iterations` + timeouts in a
  single `Config`; emit remaining budget. `GraphRecursionError` → partial report + advisory exit.
- **Cache is a superpower.** OpenRouter's ~99% cached-prompt discount makes repeated repo context
  across agent steps nearly free — design the graph so the heavy context is in a cacheable prefix.
- **Docs churn is the real risk.** langchain/langgraph release ~weekly; the pins will age. AGENTS.md
  must tell future agents to trust `uv.lock` + recorded import paths over web search.

## Historical Context (from `context/`)

- `context/foundation/shape-notes.md:38-39,61` — the seed idea names Python/uv + OpenRouter +
  GitHub + "agentic"; FR-002 originally took "directory AND PR number" (later overridden to
  directory-only in `prd.md:67-68`). The impl-review methodology is named in FR-006 from the start
  (`shape-notes.md:132`).
- `context/foundation/tech-stack.md:39-55` — the stack is **off-registry / `quality_override: true`**
  (3-of-5 self-check not-true: hand-rolled, LangChain docs churn, agent-judgment not yet built).
  F-01 is where that friction is paid down via pinned versions + documented conventions.
- `context/foundation/tech-stack.md:148-163` — "Compensation owed" is the direct ancestry of this
  research's version-pinning, import-path, graph-convention, and schema findings.
- `context/foundation/roadmap.md:51-63` — F-01 is sequenced first because the agent layer is the
  highest-risk, most unfamiliar part; landing the scaffold + typed schema early de-risks the whole
  roadmap and forces the severity-taxonomy decision while it is still cheap to change.

No prior `context/changes/**/research.md` or `context/archive/**` artifacts exist — this is the
first change in the repo.

## Related Research

None yet. `context/changes/` contains only this change and the README. Sibling foundation **F-02
(change-input-pipeline)** will produce its own research when kicked off; it is independent of F-01
and may be researched in parallel (`roadmap.md:58,72`).

## Open Questions

Decisions routed to `/10x-plan agent-runtime-finding-schema`. None is a hard blocker for F-01
except as noted.

- **D-ProviderClient (HIGH):** wire `langchain-openai.ChatOpenAI(base_url=...)` (locked in
  `tech-stack.md`) or switch to `langchain-openrouter.ChatOpenRouter` (native structured output)?
  Lean ChatOpenAI to honor the lock; update tech-stack.md if switching.
- **D-SchemaRichness (HIGH):** adopt the full impl-review finding shape (Severity + Impact +
  7-dimension + Fix-grammar Strength/Tradeoff/Confidence/Blind spot) or the minimal set
  (title + optional dimension + optional fix_hint)? Both sub-agents flagged this; lean minimal for
  v1 cost, revisit on signal-quality feedback. Exclude `Decision: PENDING` (CI-triage-only).
- **D-DeterministicChecks (HIGH):** dim-3 step 4 + Step 3 *execute* the plan's test/lint commands —
  tension with Non-Goal "No own deterministic checks" (`prd.md:118`). Execute-as-evidence vs
  read-and-flag-only.
- **D-ParallelDims (MED):** the 3 impl-review dimensions → 3 parallel LangGraph nodes (fan-out/in)
  or one node ×3 calls? Confirms the F-01 graph shape implied by "one node per phase."
- **D-SubAgentRecursion (MED, verify-in-plan):** does the embedded `create_agent`'s `max_iterations`
  count against the outer `recursion_limit`? Assume shared (size outer = chain + inner×2); confirm
  with a 10-line probe in the first plan phase.
- **D-PlanDiscovery (MED, also F-02):** diff-relative (`SKILL.md:40-48`, needs the diff first) vs
  checkout-relative (newest `plan.md` in the input dir) discovery strategy. Recommend checkout-relative
  with diff-touched as a secondary signal.
- **D-StructuredMethod (MED):** `method="json_schema"` + `strict=True` vs `function_calling` (OpenRouter
  default). Pin one and document (compensation owed).
- **D-ExitCode (LOW):** confirm 0/1 (recommended) vs richer 0/2; advisory either way.
- **D-DimensionEnum (LOW):** `dimension: Dimension | None` (enum, machine-validatable) vs free `str`
  (flexible). Lean enum; revisit if the agent fights it.
- **D-Determinism (LOW, NFR):** temperature 0 / fixed seed / deterministic tool-call order for
  "consistent across re-runs" (`prd.md:97`).
- **D-LeakageRedaction (LOW/MED):** ship schema-level notes + absolute-path guard in F-01; defer the
  regex/entropy secret-scanner to a hardening sub-phase (S-01 stdout writes nothing to the host).
- **D-AstGrepCI (LOW, F-01-adjacent infra):** the GHA install step for `sg` (`tech-stack.md:131-132`
  is "…") + the degrade-to-ripgrep fallback when `sg` is absent.

Advances/closes roadmap Open Questions: **OQ#3 (severity taxonomy) — resolved** (CRITICAL/WARNING/
OBSERVATION, `is_flagged` mapping). **OQ#7 (methodology provenance) — resolved** (impl-review-ci).
**OQ#2 (cost ceiling) — mechanism specified** (`recursion_limit` + `max_iterations` + timeout +
retry; $-cap default suggested $0.50–$1.00). OQ#1 (fail-safe) — direction given
(`include_raw=True` → empty report + exit 0; `GraphRecursionError` → partial report + advisory exit).

---

## Follow-up Research — 2026-08-01T18:44:53+02:00

> **Default model change.** The requester switched the F-01 default from
> `deepseek/deepseek-v4-pro` to a free Nemotron variant. This section **supersedes the model
> choice** in §Summary(1) and §3 (Provider wiring); all other findings (architecture, schema,
> methodology mapping) are unaffected.
>
> **✅ FINAL (2026-08-01):** the default is **`nvidia/nemotron-3-super-120b-a12b:free`** — free,
> and `tools` + `structured_outputs` + `response_format` are all `yes` (262k ctx). The
> `nemotron-3-ultra-550b-a55b:free` analysis below is kept as the reasoning trail for *why* we
> moved off it (it advertises only `tools`, not `structured_outputs`).

### Verification (live, `GET https://openrouter.ai/api/v1/models`, 2026-08-01)

`nvidia/nemotron-3-ultra-550b-a55b:free` **exists** ✅ and is **free** ($0 in / $0 out).

| Attribute | Value | F-01 impact |
|---|---|---|
| `id` | `nvidia/nemotron-3-ultra-550b-a55b:free` | — |
| `context_length` | 1,000,000 | ✅ whole-repo context fits |
| `pricing` | $0 / $0 (per 1M tok) | ✅ OQ#2 spend cap becomes moot |
| `tools`, `tool_choice` | **yes** | ✅ `@tool` analysis node + function-calling structured output work |
| `structured_outputs` | **no** | ⚠️ `with_structured_output(method="json_schema", strict=True)` is **unavailable** |
| `response_format` | **no** | ⚠️ json-mode unavailable too |
| `reasoning` | yes | ⚠️ reasoning tokens count against `max_completion_tokens` |

### The capability gap (load-bearing)

The free Ultra advertises `tools=yes` but **not** `structured_outputs`/`response_format` — a
**free-tier limitation** (the paid `nvidia/nemotron-3-ultra-550b-a55b` variant lists both as
`yes`). Consequences for the schema enforcement (§2):

- **Structured output is still achievable, but only via function-calling mode** —
  `llm.with_structured_output(FindingsReport, method="function_calling")` works because it
  rides the `tools` API. This **resolves Open Decision `D-StructuredMethod` → `function_calling`**
  (json_schema + `strict=True` is off the table for this model).
- Function-calling mode is slightly **less rigid** than json_schema/strict; plan must add a
  host-side `FindingsReport.model_validate(...)` re-validation at the `report` node (already
  recommended in §2 via `include_raw=True`) and tolerate occasional malformed payloads
  (retry/parse-failure → empty + exit 0 per OQ#1).

### Updated wiring snippet

```python
import os
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(
    model="nvidia/nemotron-3-super-120b-a12b:free",     # FINAL default (free; structured_outputs=yes)
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
    default_headers={"HTTP-Referer": "https://github.com/<owner>/reviewer-target-o-meter",
                     "X-Title": "reviewer-target-o-meter"},
)
structured_llm = llm.with_structured_output(FindingsReport, method="json_schema", strict=True)  # Super supports it
```

### Free-tier risk register (additions)

| Risk | Impact | Mitigation |
|---|---|---|
| **Structured-output weakness** (no json_schema/strict) | Malformed/loose `Finding[]` | function-calling mode + re-validate at `report` node + `include_raw=True` fail-safe |
| **Higher output variance / lower priority** | Undermines "consistent across re-runs" NFR (`prd.md:97`) | temperature 0; treat free-tier as dev/default, allow `--model` override to a paid model for CI |
| **Rate limits** | 429s mid-run (free tier is throttled) | advisory exit (FR-008) + retry/skip per OQ#1; keep `--model` escape hatch |
| **Reasoning tokens** inflate `max_completion_tokens` / latency | Slower runs, possible truncation | set generous `max_tokens`; `recursion_limit`/`max_iterations` still bound the loop (latency, not $) |
| **Uptime/backing-provider drift** | Free models are sometimes withdrawn or rerouted | centralize the slug in one `Config` constant; startup `GET /api/v1/models` membership check |

### Cost ceiling (OQ#2) — re-scoped

With a free model the **$-per-review cap is moot**. The recursion/step bounds
(`recursion_limit≈40`, inner `max_iterations≈12`, node `TimeoutPolicy`) are **still required** —
now to enforce the ~5-min latency NFR (`prd.md:98`) and to cap reasoning-token blowup, not spend.

### Alternatives (if strict structured output is later deemed necessary)

Both are **also free** and **do** advertise `structured_outputs=yes` + `response_format=yes` +
`tools=yes` (verified in the same catalog pull):

- **`nvidia/nemotron-3-super-120b-a12b:free`** — 262k ctx, structured output ✅. **Best free
  fit if json_schema/strict matters** (smaller/smarter-than-nano, still free).
- `nvidia/nemotron-nano-9b-v2:free` — 128k ctx, structured output ✅ (smaller fallback).
- Paid escapes: `deepseek/deepseek-v4-pro` (§3 — strongest, $) or paid
  `nvidia/nemotron-3-ultra-550b-a55b` (structured output ✅, $0.60/$3.60 per 1M).

### Net recommendation

Proceed with **`nvidia/nemotron-3-super-120b-a12b:free` as the F-01 default** (free;
`tools`+`structured_outputs`+`response_format` all `yes`; 262k ctx — comfortably above the
~50–120k tokens/review estimate in §3). Wire it via
**`with_structured_output(FindingsReport, method="json_schema", strict=True)`** — now the
preferred path (Super supports it), which **re-resolves `D-StructuredMethod` → `json_schema`**
(function-calling mode is no longer forced). Keep the host-side `FindingsReport.model_validate(...)`
re-check at the `report` node as cheap insurance, and add a **smoke test**
(`with_structured_output(FindingsReport)` returns a validated instance) as the first F-01
verification step. Hold the slug in one `Config` constant with a `--model` override; fallback
ladder (free → paid): `nemotron-3-super-120b-a12b:free` → `nemotron-3-ultra-550b-a55b:free`
(function-calling mode) → `deepseek/deepseek-v4-pro` ($) for CI runs needing the
strongest/most-stable signal.
