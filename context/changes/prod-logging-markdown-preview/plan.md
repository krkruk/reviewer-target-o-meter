# PROD INFO Logging + Markdown Preview — Implementation Plan

## Overview

Add INFO-level observability to the reviewer pipeline so every step is traceable
in PROD (notably the default GitHub Actions run, where the tool is currently
silent on success), and echo the final `render_comment()` Markdown to stderr
just before the CLI exits — giving the reviewer a local view of exactly what is
(or would be) posted to the PR. **Logging only. No existing business logic,
control flow, or output contract changes.**

## Current State Analysis

The pipeline runs `Config.from_env` → `compute_diff` → `load_context` →
`load_plan` → graph (`context_load` → `plan_discovery` → `checks` → `report`)
→ post-or-stdout, all orchestrated in `cli.py:43-81`.

- **No structured logging exists** anywhere (`grep` for `logging`/`getLogger` →
  0 hits). The only observability is `_util.warn()` (`_util.py:15`) — a one-line
  `WARNING: ...` to stderr, used by `diff.py`, `context_loader.py`,
  `plan_loader.py`, `config.py`, `cli.py` solely on degrade paths.
- **The app is silent on success.** In stdout mode the only output is the JSON
  report on stdout; in posting mode stdout is empty (it posts then exits). There
  is no step trace. This is why the GHA step log shows "only the initial few
  lines" today — those are the runner's own headers, not app output.
- **GitHub posting already ships** (`github.py:34` `render_comment`,
  `github.py:94` `post_comment`, wired at `cli.py:58-78`, tested in
  `tests/test_github.py`). This plan does not touch the posting mechanism — it
  only surfaces its rendered output locally.
- **stdout is a machine-readable JSON contract** (FR-007; asserted at
  `test_cli.py:51`, `test_cli.py:159`). The Markdown preview must not corrupt
  it → it goes to stderr.
- **Consumer GHA workflow** (`integration/github-actions-review.yml:73`) runs
  `reviewer-target-o-meter "${{ github.workspace }}"` with no stderr
  redirection; GHA captures stdout+stderr into the step log by default. So INFO
  logs to stderr are visible with **no workflow change**.

### Key Discoveries:

- **typer `CliRunner` stream semantics (verified empirically).** In this typer
  version `result.stdout` is **pure stdout** (stderr excluded), `result.output`
  is **mixed** (stdout+stderr), and the `mix_stderr` parameter has been removed.
  Consequence: writing logs + the Markdown preview to stderr does **not** pollute
  `result.stdout`, so the existing `json.loads(result.stdout)` assertions stay
  green; new log/preview assertions target `result.output`/`result.stderr`.
- **`_warn()` is the single existing output convention** (`_util.py:15`),
  called from 5 modules. Routing it through the new logger (with a format whose
  first token is the level name) preserves the literal `WARNING:` substring that
  `test_cli.py:138` asserts (`assert "WARNING" in result.output`).
- **`render_comment(report, repo=...)` is pure and cheap** — deterministic given
  the same report. It can be called an extra time for the preview with no
  behavioral risk, letting the existing post/emit branches stay byte-for-byte
  untouched (honoring "no business-logic change").

## Desired End State

After this plan, running `reviewer-target-o-meter <dir>` (locally or in the
consumer GHA workflow) produces:

1. A full INFO step trace on **stderr** — config/mode, diff (base + size +
   truncation), context (present/truncated), plan (change-id or none), each graph
   node, checks (start/end), report (findings/flagged/exit-code counts), and the
   post attempt/result. **Metadata only** — never the diff/context/plan/report
   bodies (AGENTS.md §e: no secrets/source leaked).
2. The final **Markdown report on stderr**, just before exit — the exact
   `render_comment()` payload that is (or would be) posted to the PR.
3. **stdout unchanged** — still the pure JSON `FindingsReport` (FR-007).
4. Verbosity via the **`LOG_LEVEL`** env var (default `INFO`); the Markdown
   preview is independent of log level (it is the payload, not noise).

Exit codes, posting behavior, the JSON contract, and all degrade paths are
identical to today.

## What We're NOT Doing

- **No business-logic / control-flow changes.** The post-vs-stdout branching, the
  degrade strategy, exit codes, and the JSON serialization are untouched.
- **No stdout contract change.** stdout stays the JSON report; the Markdown
  preview lives on stderr only.
- **No posting changes** — `post_comment`, the comment endpoint, inline review
  annotations (OQ#8) are all out of scope. The real S-02 gap (inline annotations
  vs plain comments) is a separate future change.
- **No structured/JSON log format, no correlation ids, no log shipping.** Plain
  `%(levelname)s: %(message)s` lines for human reading in a CI log.
- **No logging of input bodies.** Diff / context / plan / report text is never
  logged; only sizes, counts, refs, node names, and finding counts. The report
  body is shown once via the dedicated Markdown preview (intended).
- **No new CLI flags.** Verbosity is env-driven (`LOG_LEVEL`), matching the
  existing env-only `Config` convention.

## Implementation Approach

Use the Python stdlib `logging` module with one logger per module
(`logging.getLogger(__name__)`), configured once at the start of the CLI
command. Centralize setup in `_util.py` (which already owns the `_warn`
convention) and route `_warn()` through the logger so there is a single output
channel. Add a `log_level` field to `Config` (read from `LOG_LEVEL`,
default `INFO`). Sprinkle INFO breadcrumbs (metadata only) across the pipeline,
and add the Markdown preview as a single stderr echo right after `run_review`
returns. Three incremental phases: (1) logging foundation + `_warn` routing +
`LOG_LEVEL` knob; (2) INFO breadcrumbs across the pipeline + the Markdown
preview; (3) docs (`.env.example`, README/integration notes).

## Critical Implementation Details

- **Logger capture under tests + idempotency.** `configure_logging` MUST run at
  command runtime (inside `review()`), not at import time, so its
  `StreamHandler(sys.stderr)` binds to the **current** `sys.stderr` — which
  typer's `CliRunner` redirects. If it ran at import time the handler would hold
  the real stderr and tests could not assert on log output. It MUST also be
  idempotent: the CLI is invoked once per `CliRunner.invoke`, but the package
  logger persists across the test session, so repeated `configure_logging` calls
  must not append duplicate handlers (duplicate log lines). Guard with a flag or
  clear existing handlers first.
- **Log format is load-bearing for a test contract.** The format string's first
  token must be the level name (e.g. `%(levelname)s: %(message)s`) so `_warn`
  output reads `WARNING: <msg>` and `test_cli.py:138` (`assert "WARNING" in
  result.output`) stays green. Do not put a timestamp or logger name first.
- **Markdown preview is a raw stderr write, not a logger call.** Emit it via
  `typer.echo(rendered, err=True)` so it is (a) never suppressed by `LOG_LEVEL`
  (it is the payload, not a log line) and (b) clean, copy-pasteable Markdown
  without a per-line level prefix. Call it once right after `run_review` returns,
  before the post-vs-stdout branch — a pure addition that leaves the existing
  branches (including the post path's own `render_comment` call) untouched.

## Phase 1: Logging foundation — `configure_logging`, `get_logger`, route `_warn`, `LOG_LEVEL`

### Overview

Stand up the single logging channel, route the existing `_warn` convention
through it, and add the env-driven verbosity knob. No breadcrumbs yet — this
phase is independently unit-testable.

### Changes Required:

#### 1.1 Logging setup + `_warn` routing

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/_util.py`

**Intent**: Add the central logging configuration and a per-module logger helper;
reimplement `warn()` as a thin wrapper over the logger so all output (existing
warnings + future INFO breadcrumbs) flows through one channel with one format.

**Contract**: Add `configure_logging(level: str) -> None` that configures the
`reviewer_target_o_meter` package logger exactly once (idempotent across repeated
calls — no duplicate handlers) with a `logging.StreamHandler(sys.stderr)` and
format `"%(levelname)s: %(message)s"` at the given level. Add
`get_logger(name: str) -> logging.Logger` returning `logging.getLogger(name)`.
Reimplement `warn(message)` to call
`get_logger("reviewer_target_o_meter._util").warning(message)` — emitted output
stays `WARNING: <message>`. The idempotency guard is the one non-obvious piece;
a short snippet is warranted because the duplicate-handler trap is the likely
failure mode:

```python
_LOGGER_NAME = "reviewer_target_o_meter"

def configure_logging(level: str) -> None:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(_coerce_level(level))
    if not getattr(logger, "_rtom_configured", False):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
        logger._rtom_configured = True  # idempotent across repeated invokes
```

#### 1.2 `LOG_LEVEL` knob on Config

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/config.py`

**Intent**: Let PROD escalate verbosity without a redeploy, consistent with the
existing env-driven `Config` pattern.

**Contract**: Add `log_level: str = "INFO"` to `Config`; populate it in
`from_env()` from `os.environ.get("LOG_LEVEL", "INFO").upper()`. Forgive unknown
values by falling back to `"INFO"` (a `_warn` via the routed logger is fine). No
other `Config` behavior changes.

#### 1.3 Wire `configure_logging` into the CLI

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/cli.py`

**Intent**: Ensure logging is bound to the runtime `sys.stderr` (for CliRunner
capture in tests) before any pipeline step runs.

**Contract**: In `review()`, immediately after `config = Config.from_env()`, call
`configure_logging(config.log_level)`. No other change in this file this phase.

#### 1.4 Unit tests for the logging channel

**File**: `reviewer-target-o-meter/tests/test_logging.py` (new)

**Intent**: Lock the contract that makes Phases 2–3 safe — idempotency, the
`WARNING:` format token, and per-module logger naming.

**Contract**: Assert (a) calling `configure_logging` twice leaves exactly one
handler on the package logger; (b) `warn("x")` emits a line containing the
literal `WARNING`; (c) `get_logger(__name__)` is a child of the package logger
(inherits the handler). Use `caplog` or assert on a captured stderr stream.

### Success Criteria:

#### Automated Verification:

- `make check` passes (ruff + mypy src)
- `make test` is green: new `tests/test_logging.py` passes and the existing suite is unchanged
- `configure_logging` is idempotent (one handler after repeated calls) — asserted
- `warn()` output contains the literal `WARNING` token — asserted

#### Manual Verification:

- `make run DIR=tests/fixtures/sample-repo` (with `OPENROUTER_API_KEY` set) shows
  INFO/`configure_logging`-level output on stderr; stdout is unchanged JSON

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Phase 2: INFO breadcrumbs across the pipeline + the Markdown preview

### Overview

Add metadata-only INFO lines at every pipeline step (CLI, diff, context, plan,
graph nodes, report, post) and the Markdown preview echo. This is where "fully
track in PROD the steps" is realized.

### Changes Required:

#### 2.1 CLI step breadcrumbs + Markdown preview

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/cli.py`

**Intent**: Emit the top-level step trace (config/mode, diff/context/plan loaded,
review complete, post attempt/result) and the final Markdown preview on stderr.

**Contract**: Add INFO lines after each existing step using
`get_logger(__name__)`: review start (posting vs stdout mode, model, base_ref),
diff computed (base ref + char count + truncated flag, from `compute_diff`
return + its module constants), context loaded (present yes/no), plan discovered
(change-id or none), review complete (findings/flagged counts + exit code), and
around the post (attempt with owner/repo#pr, success, or fail+degrade). Add the
Markdown preview exactly once — right after `run_review` returns, before the
post-vs-stdout branch — via `typer.echo(render_comment(report,
repo=config.github_repository), err=True)`. The existing post/emit branches are
left untouched (the post path keeps its own `render_comment` call; the duplicate
render is pure and cheap). **Metadata only**: log counts/sizes/refs, never the
report body (the preview already shows it once, intentionally).

#### 2.2 Diff breadcrumb

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/diff.py`

**Intent**: Make diff resolution (which base, how big, truncated?) traceable.

**Contract**: One INFO line in `compute_diff` after `_resolve_base` + `_cap`,
naming the resolved base (or the degrade path the existing `_warn` already
covers), `len(raw)`, and whether `_cap` truncated. No change to the return value
or degrade behavior.

#### 2.3 Context breadcrumb

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/context_loader.py`

**Intent**: Make context loading (how many chunks, truncated?) traceable.

**Contract**: One INFO line in `load_context` reporting chunk count and whether
`_cap` truncated (or that nothing loaded → `None`). No change to the return
value or degrade behavior.

#### 2.4 Plan breadcrumb

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/plan_loader.py`

**Intent**: Make plan discovery (which change-id, or why none) traceable — this
is the single most useful line when a run produces no findings.

**Contract**: One INFO line in `load_plan` (or `_discover_change_id`) reporting
the discovered change-id, or the reason none was found (ambiguous diff / zero or
many active changes / missing plan.md). No change to the return value or degrade
behavior.

#### 2.5 Graph + node breadcrumbs

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/graph.py`,
`reviewer-target-o-meter/src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Make the four-node spine + the agentic `checks` leaf visible as it
runs.

**Contract**: One INFO line at entry of each node (`context_load`,
`plan_discovery`, `checks`, `report`) in `agent/nodes.py` (node name; for
`checks`, also log start and end of the agent invoke). In `graph.py`, one INFO
line in `arun_review` at graph start (recursion limit) and on the
`GraphRecursionError` degrade path. **Metadata only** — never log the
diff/plan/context content spliced into the `checks` messages.

#### 2.6 CLI tests for breadcrumbs + preview

**File**: `reviewer-target-o-meter/tests/test_cli.py`

**Intent**: Lock the new observability without weakening the existing JSON
contract.

**Contract**: Extend the existing offline tests (the graph is already mocked) to
assert: (a) representative INFO breadcrumbs appear in `result.output` (e.g.
`"review start"`, `"diff computed"`, `"review complete"`); (b) the Markdown
preview appears in `result.output` (the `# reviewer-target-o-meter` header and a
finding title from the fixture report); (c) `result.stdout` is still pure JSON
(`json.loads(result.stdout)` succeeds across the existing cases — no assertion
edits needed there); (d) a metadata-only invariant — assert that a known
diff/context body string does **not** appear in the log lines. No edits to
existing assertions.

### Success Criteria:

#### Automated Verification:

- `make check` passes (ruff + mypy src)
- `make test` is green: new breadcrumb/preview assertions pass; existing
  assertions (including `json.loads(result.stdout)`) unchanged
- stdout-is-pure-JSON invariant holds across all `test_cli.py` cases — asserted
- metadata-only invariant (no input body text in log lines) — asserted

#### Manual Verification:

- `make run DIR=tests/fixtures/sample-repo` — stderr shows the full step trace
  **and** the Markdown report; stdout emits the unchanged JSON report
- A posting-mode run (locally with PR env, or via the consumer GHA workflow)
  shows the step trace + the preview in the GHA step log

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Phase 3: Docs — `.env.example` + GHA/README visibility notes

### Overview

Make the new knob and the GHA streaming behavior discoverable.

### Changes Required:

#### 3.1 `.env.example`

**File**: `reviewer-target-o-meter/.env.example`

**Intent**: Document the verbosity knob next to the other env vars.

**Contract**: Add a `LOG_LEVEL=INFO` line with a one-line comment (levels:
DEBUG/INFO/WARNING/ERROR; default INFO; governs the stderr step trace only — the
Markdown preview is always shown).

#### 3.2 Integration / README notes

**File**: `integration/README.md`, `README.md`

**Intent**: Tell the consumer (and the local user) that the step trace + Markdown
preview stream to the GHA step log by default, with no workflow edit.

**Contract**: Short note that stderr now carries the INFO step trace and a
Markdown preview of the report; stdout remains the machine-readable JSON
contract; set `LOG_LEVEL` to quiet (WARNING) or escalate (DEBUG). No code.

### Success Criteria:

#### Automated Verification:

- `make check` passes (no code changes this phase; markdown/prose only)

#### Manual Verification:

- `.env.example` documents `LOG_LEVEL`; a reader of `integration/README.md` or
  `README.md` can learn the stderr/stdout split and how to toggle verbosity in
  under a minute

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Phase 4: Real-pipeline validation (live consumer GHA + live smoke)

### Overview

Validate, in the REAL pipeline, that the new observability lands where it must:
the INFO step trace and the Markdown preview actually appear in the consumer GHA
step log (the original "I see no logs but the initial few lines" pain), stdout
stays the pure JSON contract, the comment still posts, and the fail-fast path is
preserved. The offline assertions in Phases 1–2 use a mocked graph; this phase
bridges them to the live agentic run and the end-to-end consumer workflow. No
production code changes — only a live smoke test and manual GHA verification,
mirroring the structure of the archived `change-input-pipeline` Phase 6.

### Changes Required:

#### 4.1 Live logging smoke test

**File**: `reviewer-target-o-meter/tests/test_smoke_logging.py` (NEW,
`@pytest.mark.smoke`)

**Intent**: Prove the breadcrumbs + Markdown preview fire in the **real agentic
run**, not only against the mocked graph in `test_cli.py`. This is the automated
bridge between the offline assertions and the manual GHA run.

**Contract**: Skip unless `SMOKE=1` (the existing gate in `conftest.py`). Invoke
the real CLI via `CliRunner` against `os.environ.get("CONSUMER_REPO",
"tests/fixtures/sample-repo")` with a live `OPENROUTER_API_KEY`; assert (a)
representative INFO breadcrumbs appear in `result.output` (e.g. `"review start"`,
`"diff computed"`, `"review complete"`); (b) the Markdown preview header
(`"# reviewer-target-o-meter"`) appears in `result.output`; (c) `result.stdout`
is valid JSON (`json.loads` succeeds) and is uncontaminated by the stderr trace.
Does NOT post (no `GITHUB_TOKEN`).

### Success Criteria:

#### Automated Verification:

- `make check` — ruff + mypy clean
- `make test` — unaffected (the new smoke test is skipped without `SMOKE=1`)
- `SMOKE=1 OPENROUTER_API_KEY=… make llm-test` — the new logging smoke test runs
  green against the consumer/sample checkout

#### Manual Verification:

- [ ] Push to `./target-o-meter` → `review` workflow fires; the GHA **step log
  now shows the full INFO step trace** (review start/mode, diff computed, context
  + plan loaded, each graph node, review complete with findings/flagged/exit-code
  counts, post attempt/result) **AND the Markdown preview** (the
  `# reviewer-target-o-meter` header + findings table + advisory disclaimer) —
  confirming the original "I see no logs but the initial few lines" pain is
  resolved; the comment posts from `github-actions[bot]` exactly as before; the
  workflow run concludes `success` (green) even when findings are flagged
  (`continue-on-error: true` on the advisory exit). Record the PR number and run
  id. NOTE: confirm the consumer's `review.yml` does not redirect stderr (the
  shipped template doesn't) — the trace is the visible signal.
- [ ] Re-run with `OPENROUTER_API_KEY` unset in the consumer's secrets → the tool
  fails fast **before any work** (`ValueError: OPENROUTER_API_KEY is required`,
  exit 1, no comment posted, no Markdown preview emitted, no step trace beyond
  config load). NOTE: with the run step's `continue-on-error: true`, this failure
  is masked as green in GHA — the operator must confirm the secret is set on
  first setup; the **absence** of the step trace + preview in the log is the
  visible "nothing ran" signal (the inverse of the happy-path check above).

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before the change is considered done.

---

## Testing Strategy

### Unit Tests:

- `tests/test_logging.py` (new): `configure_logging` idempotency; `warn()`
  routes through the logger and emits the `WARNING` token; `get_logger` returns a
  child of the package logger.
- `tests/test_cli.py` (extended): INFO breadcrumbs + the Markdown preview appear
  in `result.output`; `result.stdout` stays pure JSON; a metadata-only invariant
  (no input body in log lines). The graph is already mocked offline.

### Integration Tests:

- No new integration test. The posting flow is already covered by
  `tests/test_github.py` (offline `MockTransport`) and `test_cli.py`'s posting
  cases; this plan changes neither.

### Manual Testing Steps:

1. `make run DIR=tests/fixtures/sample-repo` (with `OPENROUTER_API_KEY`) —
   confirm the full step trace + Markdown report appear on stderr and the JSON
   report on stdout is unchanged.
2. `LOG_LEVEL=DEBUG make run DIR=tests/fixtures/sample-repo` — confirm DEBUG
   lines appear; `LOG_LEVEL=WARNING` — confirm the step trace is silenced but
   the Markdown preview is still shown.
3. In a consumer PR (or a dry posting-mode run with `PR_NUMBER`/`GITHUB_TOKEN`/
   `GITHUB_REPOSITORY` set) — confirm the step trace + preview appear in the GHA
   step log, the comment posts as before, and the exit code is advisory.

## Performance Considerations

Negligible. INFO logging emits a handful of one-line stderr writes per run; the
Markdown preview is a single bounded string (≤ a few KB for the max 35-findings
report). `configure_logging` runs once. No hot path is affected; the LLM-bound
`checks` node dominates wall-clock by orders of magnitude.

## Migration Notes

None. This is additive: stderr gains content, stdout and exit codes are
identical. Any consumer parsing stdout JSON is unaffected; any consumer relying
on stderr being empty on success (none known — GHA captures it) now sees the
trace, which is the intended outcome.

## References

- Posting renderer reused for the preview: `github.py:34` (`render_comment`)
- Existing output convention routed through the logger: `_util.py:15` (`warn`)
- CLI orchestration where breadcrumbs land: `cli.py:43-81`
- Consumer workflow (stderr already captured): `integration/github-actions-review.yml:73`
- Verified test-runner stream semantics: `result.stdout` pure / `result.output`
  mixed / `mix_stderr` removed (empirically confirmed against the pinned typer)
- Related: `context/changes/prod-logging-markdown-preview/change.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step
> lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Logging foundation — `configure_logging`, `get_logger`, route `_warn`, `LOG_LEVEL`

#### Automated

- [ ] 1.1 `make check` passes (ruff + mypy src)
- [ ] 1.2 `make test` green: new `tests/test_logging.py` passes + existing suite unchanged
- [ ] 1.3 `configure_logging` idempotent (single handler after repeated calls)
- [ ] 1.4 `warn()` output contains the literal `WARNING` token

#### Manual

- [ ] 1.5 `make run DIR=tests/fixtures/sample-repo` shows INFO output on stderr; stdout unchanged JSON

### Phase 2: INFO breadcrumbs across the pipeline + the Markdown preview

#### Automated

- [ ] 2.1 `make check` passes (ruff + mypy src)
- [ ] 2.2 `make test` green: breadcrumb + Markdown-preview assertions pass; existing assertions unchanged
- [ ] 2.3 stdout-is-pure-JSON invariant holds across all `test_cli.py` cases
- [ ] 2.4 metadata-only invariant (no input body text in log lines)

#### Manual

- [ ] 2.5 `make run DIR=tests/fixtures/sample-repo` — stderr shows full step trace + Markdown report; stdout unchanged JSON
- [ ] 2.6 posting-mode run shows the step trace + preview in the GHA step log

### Phase 3: Docs — `.env.example` + GHA/README visibility notes

#### Automated

- [ ] 3.1 `make check` passes (prose/markdown only, no code)

#### Manual

- [ ] 3.2 `.env.example` documents `LOG_LEVEL`; integration/README note the stderr/stdout split + GHA streaming

### Phase 4: Real-pipeline validation (live consumer GHA + live smoke)

#### Automated

- [ ] 4.1 `make check` — ruff + mypy clean
- [ ] 4.2 `make test` unaffected (new smoke test skipped without `SMOKE=1`)
- [ ] 4.3 `SMOKE=1 OPENROUTER_API_KEY=… make llm-test` — logging smoke green against the consumer/sample checkout

#### Manual

- [ ] 4.4 Push to `./target-o-meter` → `review` workflow fires; GHA step log shows the full INFO step trace AND the Markdown preview; comment posts as before; run exits green even when findings flagged (record PR + run id)
