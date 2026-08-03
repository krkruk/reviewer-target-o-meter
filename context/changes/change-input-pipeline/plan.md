# Change Input Pipeline Implementation Plan

## Overview

Build F-02 (the tool accepts a checked-out directory, discovers the target
branch, computes a capped diff from local git history, and loads the repo's
review context) plus the env-driven GitHub-comment posting half of S-02 (the
`stdout`-by-default / post-when-PR-env-present branch, resolving roadmap OQ#8 as
"a plain PR comment"), and add a per-dimension findings cap. The GHA workflow
template is versioned in this repo under `integration/`; the workflow itself is
copied into the consumer repo (`./target-o-meter`) so it fires on the consumer's
PRs.

## Current State Analysis

F-01 (`agent-runtime-finding-schema`, archived) landed the agent runtime, the
typed `Finding`/`Severity` schema, and the OpenRouter provider. The CLI
(`cli.py:35-41`) currently *accepts* `diff`/`context`/`plan` as fixture inputs
— `_FIXTURE_DIFF` is inlined at `cli.py:57-66`. The graph spine
(`START → context_load → plan_discovery → checks → report → END`) is in place;
only `checks` is agentic. The `report` node (`agent/nodes.py:149-170`) already
re-validates findings host-side, sorts by severity, and caps at a flat
`_MAX_REPORTED = 10` (`agent/nodes.py:54`). `Config.from_env()`
(`config.py:43-58`) reads only `OPENROUTER_API_KEY` / `MODEL` /
`OPENROUTER_BASE_URL`. `.env.example` stubs `GITHUB_TOKEN` (commented) with a
stale "`--github` flag" framing that no longer matches the env-driven decision.

Dependencies already present: `gitpython` (direct — `pyproject.toml:17`),
`httpx` (transitive via `openai`/`langchain-openai`, NOT declared direct).
`PyGithub` is absent. Tests are offline by default; the `smoke` marker gates
live OpenRouter runs (`conftest.py`, `make llm-test`).

### Key Discoveries:

- **`./target-o-meter` is the consumer repo** (`git remote: krkruk/target-o-meter`),
  a Django project with existing `.github/workflows/{ci,cd}.yml` and composite
  actions under `.github/actions/`. Its `feature/test-pull-request` branch is a
  realistic 8-file PR (AGENTS.md, a plan move, a geometry regression test) — the
  manual real-life test fixture. `git merge-base master feature/test-pull-request`
  resolves cleanly.
- **`PR_NUMBER` and `GITHUB_TOKEN` are NOT default runner env vars** (verified
  against GHA docs). The workflow must map `PR_NUMBER: ${{ github.event.pull_request.number }}`
  and `GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}` explicitly. Auto-provided and
  useful to us: `GITHUB_REPOSITORY` (`owner/repo`), `GITHUB_API_URL`
  (`https://api.github.com`), `GITHUB_BASE_REF` (target branch — **PR events
  only**), `CI`/`GITHUB_ACTIONS`.
- **`Finding.file` already rejects absolute paths** (`findings.py:95-100`,
  FR-009) — the diff/anchor pipeline must emit repo-relative paths.
- **The degrade philosophy is a convention** (`AGENTS.md` §b): tools catch
  `subprocess.TimeoutExpired`/`FileNotFoundError` and return an error string;
  the graph catches `GraphRecursionError` → partial report + advisory exit
  (`graph.py:67-72`). Every new module follows the same never-raise-out shape.
- **`_FIXTURE_DIFF` is retained** (NOT removed). Production CLI computes the
  real diff; the fixture stays as a system-test asset. `test_cli.py` already
  mocks `run_review`, so the fixture is only exercised by unmocked/system runs.

## Desired End State

A reviewer opens a PR on `./target-o-meter`; the `review.yml` workflow fires,
checks out the PR, installs `reviewer-target-o-meter`, and runs it. The tool
discovers the base ref, computes a capped diff, loads the consumer repo's
context, runs the analysis, and posts a Markdown comment (verdict + findings
table + collapsible details) on the PR — returning an advisory exit code that
never blocks the merge. Run locally without PR env vars, the same code path
emits the same FindingsReport JSON to stdout (today's behavior, unchanged).
Findings are capped at 5 per Dimension. Missing/invalid env vars degrade
loudly on stderr and never fail CI.

Verify by: `make check` + `make test` green; `make run DIR=../target-o-meter`
emits a real computed diff + loaded context in the stdout JSON; a manually
triggered run with `PR_NUMBER` + `GITHUB_TOKEN` + `GITHUB_REPOSITORY` set posts
a comment on `./target-o-meter`'s `feature/test-pull-request` PR.

## What We're NOT Doing

- **No inline review annotations / line-level review comments.** OQ#8 is
  resolved for this slice as a *plain PR comment* (Markdown table + collapsible
  details). Inline annotations remain a future slice (the original S-02 shape).
- **No merge blocking.** Exit code stays advisory (FR-008, Non-Goal).
- **No GHA workflow in THIS repo.** The workflow fires on the *consumer's* PRs,
  so it lives in `./target-o-meter/.github/workflows/`. This repo ships only the
  versioned template + integration recipe under `integration/`.
- **No `--github` CLI flag.** Mode switching is env-driven only (`PR_NUMBER` +
  `GITHUB_TOKEN` + `GITHUB_REPOSITORY` present → post; else stdout). The stale
  `.env.example` reference to `--github` is corrected.
- **No pre-loading of source code into context.** Source is fetched on demand
  by the agent's `text_search`/`structural_search` tools (`AGENTS.md` §b). The
  loader only reads `AGENTS.md` + foundation docs + the current change docs.
- **No retry/backoff on posting.** A single POST; failures degrade to stdout +
  stderr warning + exit 0 (the analysis is the slow part, not the POST).
- **No PyGithub.** `httpx` (already transitive) becomes a direct dep for the
  single POST endpoint.
- **No change to the `checks` agentic node's analysis methodology.** That is
  S-01's job; the system prompt is extended only with the per-dimension cap
  instruction.

## Implementation Approach

Six phases, each independently verifiable, ordered by dependency: diff →
context → per-dim cap → poster → config+CLI wiring → workflow+integration.
Each new module (`diff.py`, `context_loader.py`, `github.py`) is a plain
function library (not a `@tool`, not a graph node) called by the CLI; it
follows the existing degrade convention (return an error string / empty result
+ stderr warning, never raise out). The `report` node keeps the load-bearing
host-side re-check; the per-dimension cap is enforced BOTH in the system prompt
AND host-side in `report` (trust-but-verify, `AGENTS.md` §b). The CLI keeps
`_FIXTURE_DIFF` as a retained constant for system tests.

## Critical Implementation Details

- **Degrade-to-stderr convention (cross-phase).** Every recoverable failure in
  `diff.py` / `context_loader.py` / `github.py` writes a one-line
  `WARNING: …` to `stderr` and returns a safe fallback (empty diff / `None`
  context / falls back to stdout). Only `OPENROUTER_API_KEY` missing exits
  non-zero, and it does so BEFORE any work (`config.py:50-53`). Posting
  failures never fail CI (FR-008 advisory).
- **Token/context budgets.** Diff cap ≈ 20k chars (matches the tool-output cap
  in `AGENTS.md`); context cap ≈ 8k chars. Both cut at a clean boundary and
  append a visible `… [truncated: N more chars]` marker so the model is never
  silently fed a truncation. These are module-level constants (not env-driven
  in v1).

## Phase 1: Diff & base-ref discovery

### Overview

Compute a real, capped diff from local git history against a discovered base
ref, replacing the inline fixture on the production CLI path. `_FIXTURE_DIFF`
is retained for system tests.

### Changes Required:

#### 1.1 Diff computation module

**File**: `src/reviewer_target_o_meter/diff.py` (NEW)

**Intent**: Provide a single function that turns a checkout path into the
capped diff text the analysis consumes. Follow the existing degrade convention:
on any git failure, write a `WARNING:` to stderr and return an empty string
(diff-based review still runs on context alone — FR-010 spirit).

**Contract**: `def compute_diff(repo_path: str | Path, base_ref: str | None = None) -> str`.
Base-ref discovery is a non-obvious ordered chain (the ordering is
load-bearing — override wins, CI var next, heuristics last):

```python
def _resolve_base(repo: git.Repo, override: str | None) -> str | None:
    if override:                                   # 1. explicit arg / BASE_REF env
        return override
    ci_base = os.environ.get("GITHUB_BASE_REF")    # 2. GHA pull_request events
    if ci_base:
        return ci_base
    for cand in ("origin/main", "main", "origin/master", "master"):  # 3. heuristic
        try:
            repo.commit(cand)
            return cand
        except Exception:                          # gitpython: BadName/CommandError
            continue
    return None                                     # caller degrades
```

Diff text comes from `repo.git.diff(base, "HEAD", "--patch", "--no-color")`
(or `repo.git.diff(base, commit_tree)` if `HEAD` is the merge commit). Cap is a
module constant `MAX_DIFF_CHARS = 20_000`; truncate at the next `\ndiff --git`
boundary after the budget and append
`"\n\n… [diff truncated: {remaining} more chars]\n"`. All file paths in the
emitted diff are repo-relative by construction (`git diff` output).

#### 1.2 CLI wiring (production path)

**File**: `src/reviewer_target_o_meter/cli.py`

**Intent**: The production `review()` path calls `compute_diff(repo_path,
config.base_ref)` instead of injecting `_FIXTURE_DIFF`. `_FIXTURE_DIFF` stays
as a module constant (system tests reach it by monkeypatching `compute_diff`,
not via the production path).

**Contract**: `inputs["diff"]` is now `compute_diff(repo_path, config.base_ref)`.
The `_FIXTURE_DIFF` constant and its comment are retained unchanged. `config`
is the `Config` built from env (Phase 5 adds `base_ref`); until Phase 5 lands,
pass `base_ref=None` (heuristic-only) so the phase is independently testable.

#### 1.3 Diff unit tests

**File**: `tests/test_diff.py` (NEW)

**Intent**: Cover base-resolution, capping, and the degrade path. NOTE:
`tests/fixtures/sample-repo` is plain files (no `.git`) — it is NOT a usable
git fixture, so build a tmp git repo via `gitpython` in the test (commit a
base, branch off, add a change) to exercise `compute_diff` against a real
base. Do NOT depend on `./target-o-meter` (that's manual verification only).

**Contract**: Assert (a) `compute_diff` returns a non-empty string with
`diff --git` when given a repo with a real base; (b) a diff larger than
`MAX_DIFF_CHARS` is truncated and ends with the truncation marker; (c)
`_resolve_base` honors an explicit override over `GITHUB_BASE_REF` and the
heuristic; (d) a non-git directory returns `""` and emits a `WARNING:` to
stderr (capfd fixture), never raises.

### Success Criteria:

#### Automated Verification:

- `make test` — new `test_diff.py` green; existing tests unaffected.
- `make check` — ruff + mypy clean on the new module.

#### Manual Verification:

- `make run DIR=../target-o-meter` (run from the consumer checkout's parent)
  produces stdout JSON whose `diff` field is a real diff of
  `feature/test-pull-request`-vs-`master` (not the fixture), with repo-relative
  paths.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Phase 2: Context loading

### Overview

Load the repo's review context (AGENTS.md + foundation docs + the current
change's plan/frame/research) from the checkout, capped, None-tolerant.

### Changes Required:

#### 2.1 Context-loader module

**File**: `src/reviewer_target_o_meter/context_loader.py` (NEW — named
`context_loader`, not `context`, to avoid confusion with the planning
`context/` dir at the git root)

**Intent**: Build the `context` string the `checks` node splices into its
prompt. None-tolerant: missing files contribute nothing; total absence returns
`None` so the existing `context_load` node sets `context_present=False`
(`agent/nodes.py:57-62`), preserving FR-010 graceful degradation.

**Contract**: `def load_context(repo_path: str | Path) -> str | None`.
Discovery scope (in priority order, concatenated with `---` separators):

1. `<repo>/AGENTS.md` (root) — highest signal.
2. `<repo>/context/foundation/*.md` (prd, roadmap, tech-stack, lessons if present).
3. `<repo>/context/changes/*/plan.md`, `frame.md`, `research.md` for each
   non-archived change dir (exclude `context/archive/`).

Module constant `MAX_CONTEXT_CHARS = 8_000`; truncate at the boundary and
append `… [context truncated: {remaining} more chars]`. Return `None` if the
concatenation is empty. Missing-dir / unreadable-file are swallowed with a
`WARNING:` to stderr (degrade convention).

#### 2.2 CLI wiring

**File**: `src/reviewer_target_o_meter/cli.py`

**Intent**: `inputs["context"]` is `load_context(repo_path)` instead of the
hardcoded `None` (`cli.py:38`).

**Contract**: `inputs["context"] = load_context(repo_path)`. The rest of the
spine already tolerates `None` (`plan_discovery`, the `checks` prompt assembly
at `agent/nodes.py:100-101`).

#### 2.3 Context-loader unit tests

**File**: `tests/test_context_loader.py` (NEW)

**Intent**: Cover scope, cap, and None-tolerance with a tmp directory fixture.

**Contract**: Assert (a) a tmp tree with `AGENTS.md` + `context/foundation/x.md`
+ `context/changes/c/plan.md` yields a concatenation containing all three (in
priority order); (b) `context/archive/old/plan.md` is excluded; (c) a tree with
no context files returns `None`; (d) an over-budget concat is truncated with
the marker; (e) an unreadable file (chmod 000, where the test can) emits a
`WARNING:` and is skipped, not raised.

### Success Criteria:

#### Automated Verification:

- `make test` — new `test_context_loader.py` green.
- `make check` — ruff + mypy clean.

#### Manual Verification:

- `make run DIR=../target-o-meter` — the stdout JSON's effective context (seen
  by re-running with `--debug` or via a smoke-instrumented run) includes the
  consumer's `AGENTS.md` + its `context/foundation/*`, capped.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Phase 3: Per-dimension findings cap

### Overview

Replace the flat `_MAX_REPORTED = 10` total cap with a per-Dimension cap of 5,
enforced BOTH in the system prompt AND host-side in the `report` node. The cap
is a single module constant.

### Changes Required:

#### 3.1 Cap constant + report-node enforcement

**File**: `src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Make the cap a configurable-from-within-code knob (per the user's
requirement) and enforce it host-side — the load-bearing check, since prompts
are unreliable.

**Contract**: Replace `_MAX_REPORTED = 10` (`agent/nodes.py:54`) with
`MAX_FINDINGS_PER_DIMENSION: int = 5`, defined ABOVE `_SYSTEM_PROMPT`
(lines 31-47) — NOT at line 54 — because 3.2 splices the constant into the
module-level prompt string (evaluated at import time; defining it at line 54
would raise `NameError`). Rewrite the capping in `report()`
(`agent/nodes.py:161-162`): after sorting `ordered` by severity, group by
`Finding.dimension`, keep the first `MAX_FINDINGS_PER_DIMENSION` of each group,
flatten preserving the severity order. The cap feeds the `findings_out` list
and the stamped `report` copy identically.

#### 3.2 System-prompt instruction

**File**: `src/reviewer_target_o_meter/agent/nodes.py`

**Intent**: Tell the model the cap so it prioritizes within each dimension;
keep the host-side enforcement as the backstop.

**Contract**: Extend `_SYSTEM_PROMPT` (`agent/nodes.py:31-47`) with a rule line
that names the cap using the constant (f-string or `.format`), e.g.
`"Emit at most {MAX_FINDINGS_PER_DIMENSION} findings per dimension."`. Do NOT
hardcode `5` — reference the constant so a future change is one edit.

#### 3.3 Update graph tests for the new cap

**File**: `tests/test_graph.py`

**Intent**: `test_report_sorts_by_severity_and_caps_at_ten` (`test_graph.py:69-74`)
asserts the OLD flat cap and must be rewritten for the per-dimension cap.

**Contract**: Rename to `test_report_caps_per_dimension`; construct findings
spanning multiple dimensions (e.g. 7 security + 3 correctness) and assert
security is capped at `MAX_FINDINGS_PER_DIMENSION`, correctness is unchanged,
and severity sort is preserved within each dimension. Add an assertion that
total findings can exceed the old flat 10 when spread across dimensions.

### Success Criteria:

#### Automated Verification:

- `make test` — rewritten cap test green; all other graph tests unaffected.
- `make check` — ruff + mypy clean.

#### Manual Verification:

- Inspect a smoke run's `findings` (via `make llm-test`): no dimension exceeds
  5 entries; severity ordering within each dimension is preserved.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Phase 4: GitHub posting (httpx)

### Overview

Render the FindingsReport as a Markdown PR comment (verdict + findings table +
collapsible details) and POST it to the pull request via `httpx`. Posting
failures raise; the CLI (Phase 5) catches and degrades.

### Changes Required:

#### 4.1 Declare httpx as a direct dependency

**File**: `pyproject.toml`

**Intent**: `httpx` is already in the lockfile transitively (via
`langchain-openai`/`openai`); make it direct so the posting module has a
declared, stable surface (`AGENTS.md` — "check the library is in the
codebase").

**Contract**: Add `"httpx"` to `dependencies` (`pyproject.toml:10-18`).
Re-lock with `uv lock` so `uv.lock` records the direct edge.

#### 4.2 Markdown renderer

**File**: `src/reviewer_target_o_meter/github.py` (NEW)

**Intent**: Turn a validated `FindingsReport` into the Markdown body the PR
comment will display. Pure function — no I/O, trivially testable.

**Contract**: `def render_comment(report: FindingsReport, repo: str | None = None) -> str`.
Body shape:

- H1 `## reviewer-target-o-meter` + a one-line `overall_verdict` (or "N
  findings (M flagged)" if verdict is None).
- A findings table: columns `ID | Severity | Dim | File:Line | Title`. The
  `File:Line` cell is a Markdown link to the source —
  `[src/app.py:42](https://github.com/{repo}/blob/{sha}/{file}#L{line})` when
  `repo` is known, else plain `` `src/app.py:42` ``. (`sha` is optional; pass
  `None` to skip the link in v1 if a SHA isn't easily available — keep the
  plain backtick path.)
- A collapsible `<details><summary>Details & fixes</summary>` block with each
  finding's `detail` + its `FixOption` list (approach/strength/tradeoff,
  marking `recommended`).
- A trailing `---` + the advisory disclaimer: `_Advisory exit code: {n} — this
  review never blocks a merge (FR-008)._`.

Severity renders as an emoji-ish badge text (e.g. `🔴 critical`,
`🟡 warning`, `🔵 observation`) — OR plain text if emoji is undesirable; pick
plain text to respect the "no emojis unless requested" repo convention. Use
uppercase severity labels.

#### 4.3 httpx POST function

**File**: `src/reviewer_target_o_meter/github.py`

**Intent**: Post the rendered body as a PR comment. Raise on HTTP error so the
caller (CLI) owns the degrade strategy.

**Contract**: `def post_comment(*, owner: str, repo: str, pr_number: int, token: str, body: str, api_url: str = "https://api.github.com") -> None`.
Endpoint + headers (load-bearing — non-obvious API shape):

```python
url = f"{api_url}/repos/{owner}/{repo}/issues/{pr_number}/comments"
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
httpx.post(url, json={"body": body}, headers=headers, timeout=30).raise_for_status()
```

`raise_for_status()` surfaces 4xx/5xx as `httpx.HTTPStatusError`; the CLI
catches it in Phase 5. `GITHUB_REPOSITORY` arrives as `owner/repo` — the CLI
splits it into `owner`/`repo` before calling.

#### 4.4 Posting unit tests

**File**: `tests/test_github.py` (NEW)

**Intent**: Cover rendering and the POST without touching the network.
Renderer tests are pure; POST tests use `httpx.MockTransport`.

**Contract**: Assert (a) `render_comment` produces the H1 + table +
`<details>` + disclaimer, with a row per finding and `id` injected as `F{n}`;
(b) an empty report renders the "0 findings" verdict + disclaimer; (c)
`post_comment` against a `MockTransport` that returns 201 does not raise and
hits the right URL/headers/body; (d) a `MockTransport` returning 404 raises
`httpx.HTTPStatusError` (so the CLI can catch it).

### Success Criteria:

#### Automated Verification:

- `make test` — `test_github.py` green (offline, via `MockTransport`).
- `make check` — ruff + mypy clean; `uv.lock` records the direct `httpx` edge.

#### Manual Verification:

- (Defer the live POST to Phase 6's end-to-end manual step.) Locally, call
  `render_comment` in a REPL against a flagged `FindingsReport` and eyeball
  the Markdown in a previewer.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Phase 5: Config + CLI wiring (env-driven mode switch)

### Overview

Extend `Config.from_env()` with the PR/GitHub/base-ref vars and a
`post_to_github` property; wire diff + context + posting into the CLI; rewrite
`.env.example` with the corrected GHA env-var contract.

### Changes Required:

#### 5.1 Config extension

**File**: `src/reviewer_target_o_meter/config.py`

**Intent**: One place reads every env var the tool consumes. `pr_number`
parsing is forgiving (invalid → `None` + a `WARNING:`); the `post_to_github`
property is the single switch the CLI checks.

**Contract**: Add fields (all optional, default `None`/sentinel):
`base_ref: str | None`, `pr_number: int | None`, `github_token: str | None`
(`repr=False`), `github_repository: str | None`, `github_api_url: str = "https://api.github.com"`.
`from_env()` reads `BASE_REF`, `PR_NUMBER` (parse with `int()`; on
`ValueError` warn + set `None`), `GITHUB_TOKEN`, `GITHUB_REPOSITORY`,
`GITHUB_API_URL`. Add property `post_to_github -> bool`:
`return self.pr_number is not None and bool(self.github_token) and bool(self.github_repository)`.
Keep `api_key` the only REQUIRED var (unchanged).

#### 5.2 CLI branching

**File**: `src/reviewer_target_o_meter/cli.py`

**Intent**: Replace the fixture-injection block (`cli.py:35-41`) with real
diff + context, and branch stdout-vs-post on `config.post_to_github`. Posting
errors degrade — never fail CI.

**Contract**:

```
inputs = {
    "repo_path": str(repo_path),
    "diff": compute_diff(repo_path, config.base_ref),
    "context": load_context(repo_path),
    "plan": None,            # unchanged — real plan discovery is S-01
    "findings": [],
}
report = run_review(config, inputs)
if config.post_to_github:
    # mypy can't narrow Optional fields through the `post_to_github` property;
    # both are guaranteed non-None here — narrow explicitly so the typed
    # post_comment call passes `uv run mypy src`.
    assert config.pr_number is not None and config.github_token is not None
    try:
        owner, _, repo_name = (config.github_repository or "").partition("/")
        post_comment(owner=owner, repo=repo_name, pr_number=config.pr_number,
                     token=config.github_token,
                     body=render_comment(report, repo=config.github_repository))
    except Exception as exc:                       # degrade — never fail CI
        _warn(f"posting failed; falling back to stdout ({exc})")
        _emit_stdout(report); sys.exit(report.exit_code)
    sys.exit(report.exit_code)                     # advisory, even after a successful post
_emit_stdout(report)
sys.exit(report.exit_code)
```

`_emit_stdout` is the existing JSON-emit block (`cli.py:44-51`) extracted into
a helper; `_warn` writes `WARNING: …` to stderr. Keep `_FIXTURE_DIFF` (system
tests). The F{n} id injection stays in `_emit_stdout` (the posted Markdown path
also injects F{n} inside `render_comment`).

#### 5.3 Rewrite `.env.example`

**File**: `.env.example`

**Intent**: Replace the stale "`--github` flag" framing with the corrected
env-driven contract and the full GHA mapping (verified against the GHA docs in
this plan's Research).

**Contract**: Sections — (1) `OPENROUTER_API_KEY` (REQUIRED, unchanged); (2)
`MODEL` / `OPENROUTER_BASE_URL` (OPTIONAL, unchanged); (3) NEW "Diff base
discovery" section documenting `BASE_REF` + the
`GITHUB_BASE_REF` → merge-base fallback chain; (4) NEW "GitHub PR posting"
section listing `PR_NUMBER` / `GITHUB_TOKEN` / `GITHUB_REPOSITORY` /
`GITHUB_API_URL`, all commented, with the explicit GHA mapping expressions
(`PR_NUMBER: ${{ github.event.pull_request.number }}`,
`GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}`) and the note that
`GITHUB_REPOSITORY` / `GITHUB_API_URL` / `GITHUB_BASE_REF` are auto-provided by
the runner. Remove the old `#GITHUB_TOKEN=` stub block at `.env.example:24-31`.

#### 5.4 Config + CLI tests

**File**: `tests/test_config.py`, `tests/test_cli.py`

**Intent**: Cover the mode switch and the missing-var fallbacks deterministically.

**Contract**: In `test_config.py` — assert `post_to_github` is False when any
of `PR_NUMBER`/`GITHUB_TOKEN`/`GITHUB_REPOSITORY` is missing, True when all
three are set; assert a non-integer `PR_NUMBER` parses to `None` (+ a captured
`WARNING:`) and leaves `post_to_github` False. In `test_cli.py` — (a) with
`PR_NUMBER`+`GITHUB_TOKEN`+`GITHUB_REPOSITORY` set and `post_comment`
monkeypatched to record the call, assert the CLI called it once with the
rendered body and exited with the advisory code; (b) with `post_comment`
monkeypatched to raise, assert the CLI fell back to stdout JSON + a `WARNING:`
and still exited advisory (not a crash); (c) with no PR env, assert stdout JSON
(today's behavior, unchanged).

### Success Criteria:

#### Automated Verification:

- `make test` — `test_config.py` + `test_cli.py` green, including the
  post/fallback paths via monkeypatching.
- `make check` — ruff + mypy clean.

#### Manual Verification:

- `PR_NUMBER= GITHUB_TOKEN= GITHUB_TOKEN= make run DIR=../target-o-meter` →
  stdout JSON only (no post attempt).
- `PR_NUMBER=<n> GITHUB_TOKEN=<tok> GITHUB_REPOSITORY=krkruk/target-o-meter
  make run DIR=../target-o-meter` (manual, against a real PR) → a Markdown
  comment appears on PR `<n>`; the CLI exits advisory.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Phase 6: GHA workflow template + consumer integration

### Overview

Ship the versioned workflow template + integration recipe in this repo, then
copy the workflow into `./target-o-meter/.github/workflows/` so it fires on the
consumer's PRs. End-to-end smoke against the consumer's
`feature/test-pull-request`.

### Changes Required:

#### 6.1 Workflow template

**File**: `integration/github-actions-review.yml` (NEW)

**Intent**: A drop-in workflow consumers can copy. Triggers on `pull_request`,
checks out with full history (merge-base needs it), installs `uv` + the tool +
`ast-grep`, maps the PR env vars from contexts/secrets, and runs the CLI.

**Contract**: `on: { pull_request: {} }`, `runs-on: ubuntu-latest`. Steps:
`actions/checkout@v4` with `fetch-depth: 0`; `astral-sh/setup-uv@v3`; install
the tool (from PyPI when published, else `uv pip install git+https://github.com/<owner>/reviewer-target-o-meter`
— leave a TODO, since the tool isn't published yet; for the consumer
integration use a path/editable install documented in `integration/README.md`);
install `ast-grep` per `AGENTS.md` §f (recipe already recorded); set `env:` —
`OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}`,
`PR_NUMBER: ${{ github.event.pull_request.number }}`,
`GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}` (`GITHUB_REPOSITORY`,
`GITHUB_API_URL`, `GITHUB_BASE_REF` flow through auto-provided). Run
`reviewer-target-o-meter .` from `${{ github.workspace }}`. No
`continue-on-error` — the tool's advisory exit + internal degrade already
guarantee the step never fails CI on the tool's own output.

#### 6.2 Integration recipe

**File**: `integration/README.md` (NEW)

**Intent**: The consumer-facing integration guide: copy the workflow, set the
two secrets (`OPENROUTER_API_KEY`, `GITHUB_TOKEN` is auto-provided), point at
the tool install source. Mirrors the GHA env-var table from this plan's
Research so the consumer doesn't need to re-derive it.

**Contract**: Sections — (1) "What this does" (one paragraph); (2) "Env vars"
table (var → GHA source → required?); (3) "Setup" steps (copy yaml, set
secrets, first run); (4) "Local testing" (the manual CLI invocation from Phase
5's manual verification); (5) "Degrade behavior" (stderr warnings, advisory
exit, never blocks merge).

#### 6.3 Copy workflow into the consumer repo

**File**: `../target-o-meter/.github/workflows/review.yml` (in the consumer
repo)

**Intent**: The template only fires when committed to the consumer repo. This
step lands it there as a tracked file.

**Contract**: Identical content to `integration/github-actions-review.yml`,
adjusted for the consumer's install source (path/editable install of
`reviewer-target-o-meter` from a sibling checkout, or a git URL). This is the
one step that crosses repo boundaries — do it as a single, clearly-described
manual/scripted copy, not as silent cross-repo writes elsewhere in the plan.

#### 6.4 Smoke test against the consumer checkout

**File**: `tests/test_smoke_consumer.py` (NEW, `@pytest.mark.smoke`)

**Intent**: A live, opt-in (`SMOKE=1`) test proving the input pipeline works
against a real, diffable checkout. Does NOT post (no token in CI); asserts the
diff + context are non-empty and the graph runs to completion.

**Contract**: Skip unless `SMOKE=1` (the existing gate in `conftest.py`).
Point at `os.environ.get("CONSUMER_REPO", "../target-o-meter")`; assert
`compute_diff` returns a non-empty diff containing `diff --git`, that
`load_context` returns a non-None string containing the consumer's `AGENTS.md`
heading, and that `arun_review` returns a `FindingsReport` (the analysis
itself is the same smoke already covered by `test_smoke_provider.py`). This is
the bridge between automated tests and the manual "post a real comment" step.

### Success Criteria:

#### Automated Verification:

- `make check` — ruff + mypy clean (the workflow yaml is not linted by ruff;
  validate it manually with `actionlint` if available, else by `python -c "import yaml; yaml.safe_load(...)"`).
- `make test` — unaffected (the new smoke test is skipped without `SMOKE=1`).
- `SMOKE=1 OPENROUTER_API_KEY=… make llm-test` — the new consumer smoke test
  runs green against `../target-o-meter`.

#### Manual Verification:

- Open/update the `feature/test-pull-request` PR on `./target-o-meter` (or push
  a tiny commit to retrigger). Observe the `review` workflow run, the tool
  executing, and a Markdown comment appearing on the PR with the verdict +
  findings table. Confirm the workflow run exits green (advisory) even when
  findings are flagged.
- Re-run the same PR with `OPENROUTER_API_KEY` deliberately unset in the
  consumer's secrets — confirm the workflow degrades (step fails ONLY on the
  missing required var, before any work) and does not post a broken comment.

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that the
manual testing was successful before proceeding to the next phase.

---

## Testing Strategy

### Unit Tests:

- `test_diff.py` — base-resolution chain, diff capping + truncation marker,
  non-git degrade.
- `test_context_loader.py` — scope priority, archive exclusion, cap,
  None-when-empty, unreadable-file skip.
- `test_github.py` — `render_comment` shape (H1/table/`<details>`/disclaimer,
  empty-report path, F{n} injection) and `post_comment` via `MockTransport`
  (201 ok / 404 raises).
- `test_graph.py` — rewrite the flat-cap test to the per-dimension cap; keep
  all pure-node + ordering + recursion-probe tests.
- `test_config.py` — `post_to_github` truth table; `PR_NUMBER` non-integer
  parse-to-None.
- `test_cli.py` — post path (monkeypatched `post_comment`), post-failure
  fallback to stdout, no-env stdout path.

### Integration Tests:

- `test_cli.py`'s post/fallback paths (above) are the offline integration
  coverage for the mode switch.

### Manual Testing Steps:

1. `make run DIR=../target-o-meter` (no PR env) → real diff + loaded context
   in stdout JSON; paths repo-relative; no fixture.
2. `PR_NUMBER=<n> GITHUB_TOKEN=<tok> GITHUB_REPOSITORY=krkruk/target-o-meter
   make run DIR=../target-o-meter` → Markdown comment appears on PR `<n>`.
3. Repeat (2) with a deliberately bad token → confirm `WARNING:` on stderr,
   stdout JSON emitted, exit advisory (no crash, no broken comment).
4. Push to `feature/test-pull-request` on `./target-o-meter` → the `review`
   workflow runs end-to-end and posts the comment; workflow exits green even
   when findings are flagged.
5. `SMOKE=1 OPENROUTER_API_KEY=… make llm-test` → the consumer smoke test is
   green.

## Performance Considerations

- The ~20k-char diff cap and ~8k-char context cap bound the `checks` node's
  prompt size (the analysis is the cost/latency bottleneck, not the input
  prep). Both are module constants.
- `post_comment` uses a 30s `httpx` timeout — well under the `run_timeout`
  budget the graph already enforces (`config.py:35`), and a single POST.
- No retry/backoff — the analysis dominates wall-clock; a transient POST
  failure degrades to stdout rather than retrying under CI.

## Migration Notes

- **Behavior change (intended):** the production CLI now computes a real diff
  and loads real context. Existing CLI tests that monkeypatch `run_review` are
  unaffected (they never exercised the diff/context code path). The
  `_FIXTURE_DIFF` constant is retained for system tests.
- **`.env.example` rewrite:** the stale `#GITHUB_TOKEN=` block is removed and
  replaced with the full env-driven posting section. Anyone who copied the old
  stub needs to re-copy — documented in the new section.
- **New direct dep:** `httpx` (already transitive). `uv.lock` is re-locked;
  no resolver churn expected.
- **Per-dimension cap replaces flat 10:** downstream consumers of the stdout
  JSON who assumed `<= 10` findings must tolerate up to
  `5 × (number of dimensions touched)`.

## References

- Roadmap F-02 + OQ#4/OQ#8/OQ#9: `context/foundation/roadmap.md:65-78,118-128`
- PRD FR-002/003/004/005/007/008/010/011: `context/foundation/prd.md:62-92`
- Graph convention + degrade philosophy: `AGENTS.md` §b
- ast-grep GHA install recipe: `AGENTS.md` §f
- GHA default env vars + `github` context (verified 2026-08-03):
  https://docs.github.com/en/actions/reference/workflows-and-actions/variables
  https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#github-context
- Existing wiring touched: `cli.py:35-51,57-66`, `config.py:43-58`,
  `agent/nodes.py:31-47,54,149-170`, `findings.py:95-100`, `.env.example:24-31`
- Test patterns to follow: `tests/test_graph.py:94-136` (DI `_FakeAgent`),
  `tests/test_cli.py:46` (`monkeypatch.setattr(cli_mod, "run_review", …)`),
  `tests/conftest.py:16-22` (smoke gate)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Diff & base-ref discovery

#### Automated

- [x] 1.1 `make test` green incl. new `tests/test_diff.py` — 7a1e7e4
- [x] 1.2 `make check` clean on new `src/reviewer_target_o_meter/diff.py` — 7a1e7e4

#### Manual

- [x] 1.3 `make run DIR=../target-o-meter` shows a real diff (not the fixture) in stdout JSON — verified as the live system smoke `test_compute_diff_feeds_real_diff_to_live_reviewer` (a planted SQLi in a built-from-scratch repo is surfaced by the real LLM through the real `compute_diff` path) — 7a1e7e4

### Phase 2: Context loading

#### Automated

- [x] 2.1 `make test` green incl. new `tests/test_context_loader.py` — 6e25eeb
- [x] 2.2 `make check` clean on new `src/reviewer_target_o_meter/context_loader.py` — 6e25eeb

#### Manual

- [x] 2.3 `make run DIR=../target-o-meter` shows the consumer's AGENTS.md + foundation docs in the effective context — verified as the live system smoke `test_load_context_feeds_real_context_to_live_reviewer` (real `load_context` output carries AGENTS.md + foundation, and the live agent still surfaces the planted defect over diff+context) — 6e25eeb

### Phase 3: Per-dimension findings cap

#### Automated

- [x] 3.1 `make test` green incl. rewritten `test_report_caps_per_dimension` — 7a8a31f
- [x] 3.2 `make check` clean on `agent/nodes.py` — 7a8a31f

#### Manual

- [x] 3.3 Smoke run (`make llm-test`): no dimension exceeds 5 findings; severity order preserved within each — verified as the live system smoke `test_live_review_respects_per_dimension_cap` (a multi-defect diff reviewed by the real LLM; the host-side cap holds on real model output, no dimension > 5) — 7a8a31f

### Phase 4: GitHub posting (httpx)

#### Automated

- [x] 4.1 `make test` green incl. new `tests/test_github.py` (MockTransport)
- [x] 4.2 `make check` clean on new `src/reviewer_target_o_meter/github.py`
- [x] 4.3 `uv.lock` records `httpx` as a direct dependency

#### Manual

- [x] 4.4 `render_comment` output eyeballed in a Markdown previewer against a flagged report — verified as the live system smoke `test_render_comment_renders_live_findings_as_valid_markdown` (the renderer produces well-formed header/table/details/disclaimer Markdown over the live reviewer's findings, with the planted SQLi reflected)

### Phase 5: Config + CLI wiring (env-driven mode switch)

#### Automated

- [ ] 5.1 `make test` green incl. `test_config.py` post_to_github truth table + `test_cli.py` post/fallback paths
- [ ] 5.2 `make check` clean on `config.py` + `cli.py`
- [ ] 5.3 `.env.example` rewritten with the corrected GHA env-var contract

#### Manual

- [ ] 5.4 No-PR-env run → stdout JSON only (no post attempt)
- [ ] 5.5 PR-env run against `./target-o-meter` → Markdown comment appears on the PR

### Phase 6: GHA workflow template + consumer integration

#### Automated

- [ ] 6.1 `make check` clean; workflow yaml parses (`yaml.safe_load` / `actionlint`)
- [ ] 6.2 `make test` unaffected — new consumer smoke test skipped without `SMOKE=1`
- [ ] 6.3 `SMOKE=1 OPENROUTER_API_KEY=… make llm-test` green incl. new consumer smoke test

#### Manual

- [ ] 6.4 Push to `feature/test-pull-request` on `./target-o-meter` → `review` workflow posts the comment; workflow exits green even when findings flagged
- [ ] 6.5 Re-run with `OPENROUTER_API_KEY` unset → step fails fast (before work); no broken comment posted
