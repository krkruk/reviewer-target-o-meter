<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Agent runtime + typed Finding/Severity schema + OpenRouter wiring

- **Plan**: `context/changes/agent-runtime-finding-schema/plan.md`
- **Scope**: Phase 1 to 4 of 4 (Full Plan Review)
- **Date**: 2026-08-01
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 3 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — Duplicate system prompt injection in agent loop

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py:107
- **Detail**: In `build_checks_node()`, `system_prompt=_SYSTEM_PROMPT` is configured when calling `create_agent()`. Inside the returned `checks()` async function, `messages` also prepends `SystemMessage(content=_SYSTEM_PROMPT)`. Because `create_agent` automatically injects its configured `system_prompt` into the execution messages, adding `SystemMessage(content=_SYSTEM_PROMPT)` directly inside `messages` causes the system prompt to be sent twice to the model on every invocation, wasting context budget and inflating token costs.
- **Fix A ⭐ Recommended**: Remove `SystemMessage(content=_SYSTEM_PROMPT)` from `messages` in `checks()`
  - Strength: Keeps prompt definition centered in `create_agent`; eliminates duplicate prompt tokens on every invocation.
  - Tradeoff: None.
  - Confidence: HIGH — standard LangChain agent pattern.
  - Blind spot: None.
- **Fix B**: Omit `system_prompt` argument in `create_agent()`
  - Strength: Explicitly controls system message in the `messages` array in `checks()`.
  - Tradeoff: `create_agent` instance loses system prompt if reused elsewhere.
  - Confidence: MEDIUM — non-standard `create_agent` setup.
  - Blind spot: None.
- **Decision**: FIXED via Fix A

### F2 — Option flag injection & uncaught `OSError` in `text_search` tool

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/agent/tools/text_search.py:38
- **Detail**: `text_search` passes `query` directly as a positional CLI argument to `rg`. If `query` starts with `-` (e.g., `-i` or `--regexp`), `rg` will interpret it as a CLI option flag rather than a search pattern. Additionally, `subprocess.run` catches `TimeoutExpired` and `FileNotFoundError` but not general `OSError` (e.g. `PermissionError`), violating the requirement that `@tool` functions must never raise.
- **Fix**: Pass `-e` before `query` (`["rg", "--no-heading", "-n", "--max-count", str(max_count), "-e", query, repo_path]`) and catch `OSError` to return a degraded error string.
- **Decision**: FIXED

### F3 — `change.md` status updated to `implemented` instead of `planned`

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: context/changes/agent-runtime-finding-schema/change.md:4
- **Detail**: Plan Phase 4.2 specified setting `change.md` header `status: planned`. Instead, `status` was set directly to `implemented`.
- **Fix**: Keep `status: impl_reviewed` (stamped by review process) since all implementation phases are completed and verified.
- **Decision**: FIXED

### F4 — Uncaught `OSError` in `structural_search` tool

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/agent/tools/structural_search.py:47
- **Detail**: `structural_search` catches `subprocess.TimeoutExpired` and `FileNotFoundError` but does not catch general `OSError` (e.g. `PermissionError`). If `subprocess.run` raises `PermissionError`, it will escape the tool function and break the agent execution loop.
- **Fix**: Expand exception handling to catch `OSError` and return a degraded error string pointing to `text_search`.
- **Decision**: FIXED

### F5 — Plain-text `api_key` attribute in `Config` Pydantic model

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/config.py:28
- **Detail**: `Config.api_key` is defined as a plain `str` on `Config(BaseModel)`. Evaluating `repr(config)` or string formatting `config` during logging will print the raw `OPENROUTER_API_KEY` in plain text.
- **Fix**: Set `Field(..., repr=False)` on `Config.api_key`.
- **Decision**: FIXED
