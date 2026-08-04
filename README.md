# reviewer-target-o-meter

> An automated **"what are the critical points in this PR?"** signal. An LLM
> agent reads the diff, runs a structured implementation-review methodology,
> and emits file/line-anchored findings — to stdout as JSON, or as a Markdown
> comment on the PR. Read-and-flag only; never blocks a merge.

---

## Table of contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [System requirements](#system-requirements)
- [Environment variables](#environment-variables)
- [Run locally](#run-locally)
- [GitHub Actions integration](#github-actions-integration)
- [Limitations & non-goals](#limitations--non-goals)
- [Contributing](#contributing)
- [License](#license)

---

## What it does

`reviewer-target-o-meter` reviews a checked-out pull request and produces a
structured `FindingsReport`: a set of findings, each anchored to a real
**repo-relative file + 1-based line**, classified by **severity**
(CRITICAL / WARNING / OBSERVATION) and **dimension** (correctness, security,
maintainability, testability, performance, design, documentation), each with a
rationale and up to two fix *directions* (never an applied patch).

The analysis is driven by an established **implementation-review methodology** —
three review lenses (plan drift / safety-quality-pattern / test-coverage) mapped
to the seven dimensions — not a generic "find issues" sweep. Findings are
**diff-scoped**: every one anchors on a file the PR actually changed (the one
exception is a plan-drift finding on a planned-but-absent file), so the agent
never becomes a repo-wide linter emitting noise on untouched code.

The output contract has three surfaces:

- **stdout JSON** — the full `FindingsReport` (the default mode).
- **PR Markdown comment** — verdict + findings table + collapsible details,
  posted when the GitHub env vars are present.
- **Advisory exit code** — `0` if nothing is flagged, `1` otherwise. It **never
  blocks a merge** (FR-008); CI integrations use `continue-on-error`.

## How it works

The tool is a four-node LangGraph state machine:

```
START → context_load → plan_discovery → checks → report → END
```

- **`context_load`** — computes the diff, loads the repo's review context
  (`AGENTS.md` + foundation docs + the current change's docs).
- **`plan_discovery`** — discovers the change's `plan.md` from the diff (or a
  single active change dir), else `None`. Plan-dependent checks are skipped when
  no plan is found (the methodology is *plan-tolerant* — FR-006).
- **`checks`** — the agentic node: a single `create_agent` sub-graph with two
  search `@tool`s (`text_search` via ripgrep, `structural_search` via ast-grep),
  driven by the methodology system prompt, emitting a strictly-typed
  `FindingsReport`.
- **`report`** — re-validates the findings, injects `F{n}` ids, renders the
  comment, and computes the exit code.

The spine is deterministic; only `checks` is agentic. The pipeline degrades
gracefully — a recursion/timeout/parse failure yields a partial or empty report
with an advisory exit, never a crash.

## System requirements

### Python

- **Python `>= 3.14`** (declared in
  [`reviewer-target-o-meter/pyproject.toml`](reviewer-target-o-meter/pyproject.toml)).
- **[`uv`](https://docs.astral.sh/uv/)** — the project is `uv`-managed. All
  developer commands run through `uv run`, so install it first:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
  `uv` resolves and pins the full dependency set
  ([LangChain/LangGraph stack](reviewer-target-o-meter/uv.lock)) automatically —
  there is no `requirements.txt` to install by hand.

### External tooling (optional but recommended)

These power the agent's two search `@tool`s. If either is missing the pipeline
still runs — the tool returns an error string and the agent adapts (degrade
philosophy, `AGENTS.md` §b):

- **[`ripgrep`](https://github.com/BurntSushi/ripgrep)** (`rg`) — backs
  `text_search`. Pre-installed on `ubuntu-latest` in GitHub Actions.
- **[`ast-grep`](https://ast-grep.github.io)** — backs
  `structural_search`. Not pre-installed on GHA runners; see the
  [install recipe](#github-actions-integration) below.

### OpenRouter access (required)

The analysis runs on an LLM via **[OpenRouter](https://openrouter.ai/)**'s
OpenAI-compatible endpoint. You need:

1. An **OpenRouter account** and an **API key** (create one at
   <https://openrouter.ai/keys>). The key is read at runtime from the
   `OPENROUTER_API_KEY` env var — it is never hardcoded or echoed into output.
2. Network egress to `https://openrouter.ai/api/v1` (or your custom
   `OPENROUTER_BASE_URL`).

**Cost model:** the default model is a paid DeepSeek slug
(`deepseek/deepseek-v4-flash-0731`) that honors the strict structured-output
contract and gives a stable signal on large diffs. Override `MODEL` to swap it
(e.g. a free slug for zero-cost runs — the free Nemotron variant supports tools
+ structured-outputs but exhausts its token budget on large diffs). The system
prompt is large but amortized across agent steps via OpenRouter's cached-prompt
discount; the cost/latency bounds (`recursion_limit=40`, `max_iterations=12`,
`run_timeout=120s`) hold. The diff input is capped at `MAX_DIFF_CHARS=45000`
and the model's completion budget at `_MAX_TOKENS=128000` (reasoning + emitted
JSON both fit).

## Environment variables

The tool is **env-driven** — there are no `--flags` for mode switching. It posts
a PR comment **only when** `PR_NUMBER` + `GITHUB_TOKEN` + `GITHUB_REPOSITORY`
are all present; otherwise it emits the `FindingsReport` JSON to stdout.

Copy [`reviewer-target-o-meter/.env.example`](reviewer-target-o-meter/.env.example)
to `.env` and fill in the values. `.env` is gitignored.

| Var | Required | Default | Purpose |
|---|---|---|---|
| `OPENROUTER_API_KEY` | **yes** | — | OpenRouter API key. Read at runtime; never echoed into output (leakage guardrail, FR-003). A missing key fails the step **before any work**. |
| `MODEL` | no | `deepseek/deepseek-v4-flash-0731` | OpenRouter model slug. Override to swap the analysis model (e.g. a free slug for zero-cost runs). |
| `OPENROUTER_BASE_URL` | no | `https://openrouter.ai/api/v1` | OpenAI-compatible endpoint. Override only to point at a self-hosted gateway / local server. |
| `BASE_REF` | no | *(heuristic chain)* | Base ref to diff `HEAD` against. Resolution order: `BASE_REF` → `GITHUB_BASE_REF` → `origin/main` → `main` → `origin/master` → `master`. Set explicitly to force a base. |
| `PR_NUMBER` | no (to post) | — | PR number to comment on. **Local:** set with a token to post. **GHA:** map from `${{ github.event.pull_request.number }}`. A non-integer disables posting (WARNING) rather than crashing. |
| `GITHUB_TOKEN` | no (to post) | — | Token with `pull-requests: write`. **Local:** set explicitly. **GHA:** auto-provided by the runner, but map explicitly. |
| `GITHUB_REPOSITORY` | no (to post) | — | `owner/repo`. **GHA:** auto-provided — do not set manually. **Local:** set to post. |
| `GITHUB_API_URL` | no | `https://api.github.com` | GitHub API root. **GHA:** auto-provided — do not set manually. |
| `GITHUB_BASE_REF` | no | — | Target branch on `pull_request`. **GHA:** auto-provided. Ignored if `BASE_REF` is set. |
| `LOG_LEVEL` | no | `INFO` | Stderr step-trace verbosity: `DEBUG`/`INFO`/`WARNING`/`ERROR`. Governs the INFO trace on stderr only — stdout JSON is never affected. The Markdown preview of the report is always shown (it is the payload, not a log line). |

> **Mode switching summary** — stdout JSON is the default; PR posting activates
> only when `PR_NUMBER` + `GITHUB_TOKEN` + `GITHUB_REPOSITORY` are all present.
> Reading source and computing the diff are local operations and need **no**
> token.

> **stdout vs stderr** — stdout is the machine-readable `FindingsReport` JSON
> (FR-007); never parse stderr. stderr carries the human-readable INFO step trace
> (review start/mode → diff/context/plan → each graph node → review-complete
> counts → post attempt/result) **and**, just before exit, a Markdown preview of
> the exact `render_comment()` payload that is (or would be) posted to the PR.
> In the GitHub Actions step log both stream by default (no workflow edit). Set
> `LOG_LEVEL=WARNING` to silence the trace and keep just the preview.

## Run locally

All commands run from the package directory (where `pyproject.toml lives`):
[`reviewer-target-o-meter/`](reviewer-target-o-meter).

### 1. Configure the environment

```bash
cd reviewer-target-o-meter
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY=sk-or-...
```

### 2. Review a checked-out repo (stdout JSON — the default)

```bash
make run DIR=/path/to/some/checked-out-repo
```

This runs `uv run reviewer-target-o-meter "$DIR"` and prints the
`FindingsReport` JSON to stdout. Exit code is advisory: `0` = nothing flagged,
`1` = findings flagged.

<details>
<summary><b>Equivalent commands (without <code>make</code>)</b></summary>

```bash
# from reviewer-target-o-meter/
uv run reviewer-target-o-meter /path/to/some/checked-out-repo

# the thin wrapper lets `run` take a positional dir:
./make.sh run /path/to/some/checked-out-repo
```

</details>

### 3. (Optional) Exercise the PR-posting path locally

```bash
PR_NUMBER=<n> GITHUB_TOKEN=<tok> GITHUB_REPOSITORY=<owner>/<repo> \
  make run DIR=/path/to/some/checked-out-repo
```

A bad token degrades to stdout JSON + a `WARNING:` on stderr; the exit stays
advisory (no crash, no broken comment).

### Other developer commands

```bash
make check      # ruff + mypy src            (linters + static type verification)
make test       # uv run pytest -m "not smoke"  (unit tests; excludes live LLM smoke)
make llm-test   # SMOKE=1 uv run pytest -m smoke  (live OpenRouter; needs OPENROUTER_API_KEY)
make help       # list all targets
```

## GitHub Actions integration

`reviewer-target-o-meter` runs as a **drop-in review workflow** in any consumer
repo. On each pull request it checks out the PR, installs the tool + `ast-grep`,
runs the analysis, and posts a Markdown comment.

### Quick setup

1. **Copy the workflow template** into the consumer repo:

   ```bash
   cp integration/github-actions-review.yml \
      ../<consumer-repo>/.github/workflows/review.yml
   ```

2. **Set the `OPENROUTER_API_KEY` secret** in the consumer repo
   (Settings → Secrets and variables → Actions → New repository secret).
   `GITHUB_TOKEN` is auto-provided by the runner — do **not** create it.

3. **Open or update a PR** — the `review` workflow fires and posts the comment.

### What the workflow does

```yaml
on: pull_request
permissions:
  contents: read
  pull-requests: write   # needed to post the comment (least privilege)
```

It checks out the PR with `fetch-depth: 0` (the merge-base needs full history),
installs `uv`, the tool, and `ast-grep`, maps the PR env vars from contexts and
secrets, and runs `reviewer-target-o-meter "$GITHUB_WORKSPACE"`. The run step
carries `continue-on-error: true` so the advisory exit `1` (the normal case when
findings are flagged) never fails CI.

### ast-grep install recipe

`ast-grep` is not pre-installed on GHA runners. The workflow installs the
prebuilt binary — note the asset carries an `app-` prefix (the unprefixed URL
404s):

```yaml
- name: Install ast-grep (structural_search tool)
  run: |
    curl -L https://github.com/ast-grep/ast-grep/releases/latest/download/app-x86_64-unknown-linux-gnu.zip -o ast-grep.zip
    unzip ast-grep.zip && install -m 0755 ast-grep /usr/local/bin/ast-grep
```

If `ast-grep` is unavailable at runtime, `structural_search` degrades to an error
string pointing the agent at `text_search` — the pipeline still runs.

### Install source

The tool is not yet on PyPI. The template installs from a git URL (note the
`#subdirectory=reviewer-target-o-meter` fragment — the `pyproject.toml` lives in
the nested package dir, not the git root):

```yaml
uv tool install "git+https://github.com/krkruk/reviewer-target-o-meter#subdirectory=reviewer-target-o-meter"
```

Point at a branch/tag with `@<ref>` to pick up unreleased code. The template
includes a TODO marking the switch to `uv tool install reviewer-target-o-meter`
once published.

**Full integration guide** — env-var mapping, local testing of the posting path,
and the complete degrade behavior table — lives in
[`integration/README.md`](integration/README.md).

## Limitations & non-goals

- **Read-and-flag only.** The tool never executes the reviewed project's
  test/lint/build commands (PRD Non-Goal). MISSING-TEST / UNCOVERED-BEHAVIOR
  findings come from static / presence evidence (diff + plan), never execution.
- **Advisory exit, never blocking.** Exit `1` means findings were flagged; it
  does not gate a merge (FR-008).
- **No secret/entropy scanner.** Stdout mode writes nothing to the host; the
  schema-level absolute-path guard rejects host paths in findings
  (`findings.py`).
- **Plan-tolerant.** Plan-dependent checks (the drift lens) run only when a
  plan is discoverable from the diff or a single active change dir (FR-006).
  Repos without the `context/changes/` structure see no change in behavior.
- **No LLM-as-judge.** Signal verification is the targeted + negative-control
  smoke suite, not a second model call.
- **Single `checks` node.** No per-lens parallel sub-nodes (a locked F-01
  decision; revisit only if per-lens depth proves shallow).

## Contributing

The repo follows the **10x** planning convention (`context/changes/`,
`context/foundation/`, `context/archive/`). Before contributing, read
**[`AGENTS.md`](AGENTS.md)** — it's the single onboarding doc for both humans
and AI coding agents: where things live, the pinned LangChain/LangGraph versions
and canonical import paths, the graph convention, the severity taxonomy + anchor
rules, the review-output checklist, and developer commands.

## License

[MIT](LICENSE) © Krzysztof Kruk
