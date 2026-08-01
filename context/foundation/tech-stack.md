---
# ------------------------------------------------------------------
# ⚠️  OFF-REGISTRY / NON-CONFORMING — DO NOT CONSUME WITH /10x-bootstrapper
# ------------------------------------------------------------------
# This file is NOT a schema-conforming tech-stack hand-off. It records a
# manual stack decision made outside the starter registry. There is NO valid
# `starter_id` (the registry has no Python CLI card), so /10x-bootstrapper
# CANNOT scaffold from this file. Running bootstrapper against it will fail
# the registry-sync validator by design.
#
# If registry-backed scaffolding is later required, re-invoke
# /10x-tech-stack-selector and pick a registry cell (Go is the closest fit
# for this product type).
# ------------------------------------------------------------------
project: reviewer-target-o-meter
conforms_to_handoff_schema: false
starter_id: null              # intentionally null — no registry card for python + cli
path_taken: custom            # design-your-own; the (cli, python) cell is <none>
language_family: python
package_manager: uv
team_size: solo
quality_override: true        # proceeded past a Socratic challenge with known friction
bootstrapper_confidence: best-effort   # off-registry; /10x-bootstrapper is skipped
recorded: 2026-08-01
self_check_answers:
  typed: true
  from_official_starter: false
  conventions: true
  docs_current: false
  can_judge_agent: false
feature_flags:
  has_ai: true
  has_auth: false             # machine GitHub token (FR-003), not a user-auth feature
  has_payments: false
  has_realtime: false
  has_background_jobs: false
---

## Why this stack (manual / off-registry)

`reviewer-target-o-meter` is an agentic LLM code-review CLI. Python is the
strongest language fit (dominant AI/agent ecosystem, the user's stated prior,
`uv` for environment management), and **LangChain + LangGraph is the
implementation layer for the reviewer agent and its tools** — the change from
the prior hand-off, which used the bare `openai` SDK. The starter registry has
no Python CLI card: the `cli` recommended-defaults cell is `<none>` for Python,
and the only Python cards (`django`, `fastapi`) are web backends of the wrong
product type. On the design-your-own route the candidate filter
(`language=python ∧ product_type=cli`) returns an empty set, so no registry
`starter_id` can be handed off. The user consciously chose to hand-roll with
`uv` + LangChain rather than switch to a registry-backed language (Go / Rust).
This intentionally breaks the bootstrap chain: `/10x-bootstrapper` is skipped.
A five-point self-check came back 3-of-5 not-true (hand-rolled, LangChain docs
churn, agent-judgment not yet built); the user proceeded with
`quality_override: true`, owning the friction via project instruction files.

## Locked decisions (owned by this step)

- **Git host — GitHub.** Resolves PRD Open Question #5. The tool reads PRs and
  posts Reviews against GitHub; `secrets.GITHUB_TOKEN` is the agent identity
  (FR-003).
- **AI source — OpenRouter.** Resolves PRD Open Question #6. OpenAI-API-
  compatible: drive it via `langchain-openai`'s `ChatOpenAI` with
  `base_url=https://openrouter.ai/api/v1`.
- **Language/runtime — Python, managed with `uv`.** Confirmed from the user's
  seed idea and shape-notes `## Forward: tech-stack`.
- **Agent layer — LangChain + LangGraph (NEW vs prior hand-off).** The reviewer
  runs as a LangGraph stateful graph — a node per FR-006 phase (context-load →
  plan discovery → drift/safety/pattern checks → report) — with `langchain-core`
  `@tool` wrappers around GitHub, ast-grep, and ripgrep. This replaces the bare
  `openai` SDK agent loop.
- **GitHub access — PyGithub + httpx (posting-only).** Reading source and
  computing the diff are LOCAL operations (the checkout + `gitpython`); the tool
  does NOT fetch the PR via the GitHub API. `PyGithub`/`httpx` are used ONLY to
  post findings to the PR when `--github` is set (FR-003/007/009); the PR number
  and `GITHUB_TOKEN` come from the GitHub Actions environment, not CLI args.
- **Code-search tools — ast-grep (structural) + ripgrep (fast text).** Assumed
  present on `PATH` in the runtime environment; wrapped as `@tool` functions the
  agent calls during analysis (subprocess-backed, not pip dependencies).
- **Launch surface — a single console command, run both as a GitHub Actions
  step and as a local CLI (same code path, FR-001).**

## Scaffold recipe

```bash
uv init reviewer-target-o-meter --package
cd reviewer-target-o-meter
```

`--package` yields a `src/` layout + a `[project.scripts]` console entry point —
the single command that serves both the CI step and the local CLI (FR-001).

```bash
# agent layer (the change from the prior hand-off: LangChain + LangGraph)
uv add langchain langgraph langchain-openai langchain-core
# OpenRouter is driven via the OpenAI-compatible ChatOpenAI client:
#   ChatOpenAI(model="...", base_url="https://openrouter.ai/api/v1", api_key=...)

# GitHub read + inline Review write
uv add pygithub          # read PR files/diff; post Review w/ inline annotations (FR-003/007/009)
uv add httpx             # direct REST where PyGithub lags (line-level review comments)

# typed schemas, config, context-budget model, CLI
uv add pydantic          # typed Finding/Severity schema (FR-011), config, context-budget model
uv add typer             # typed CLI: `reviewer-target-o-meter <path> [--github]`
uv add gitpython         # compute/segment the diff at the PR revision (FR-005)

# dev
uv add --dev pytest ruff mypy
```

`ast-grep` and `ripgrep` are **not** pip dependencies — they are assumed to be
on `PATH` in the runtime environment (the GitHub Actions runner and the
developer's machine). They are wrapped as `@tool` functions that shell out via
`subprocess`. On `ubuntu-latest`, `rg` ships by default; `ast-grep` needs a
setup step in the workflow (see below).

Rationale: LangChain + LangGraph give an explicit, typed agent loop that maps
1:1 to FR-006's methodology, with tools (GitHub / ast-grep / rg) provisioned
declaratively. `typer` + `pydantic` + `mypy` + `ruff` keep the project typed
and convention-based — the two agent-friendly gates that matter most for an
agent-assisted codebase. `ChatOpenAI` against OpenRouter's `base_url` is the
documented OpenAI-compatible path; `PyGithub`/`httpx` cover the GitHub read and
inline-Review write that FR-007/009 require.

## GitHub Actions wiring (FR-001, FR-002, FR-003)

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }        # full history needed for the local diff (FR-005)
- name: Install ast-grep          # rg is preinstalled on ubuntu-latest
  run: ...                        # e.g. cargo install ast-grep, or a setup-action
# Default: emit the JSON report to stdout (no host write, no token needed).
- run: uv run reviewer-target-o-meter ${{ github.workspace }} --github
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}        # only used because --github is set (posts findings to the PR)
    OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

`${{ github.workspace }}` is the checked-out directory — the tool's sole input
param (FR-002). `--github` toggles posting to the PR; omit it for the JSON report
on stdout (the default). The PR number and token are read from the Actions
environment, not passed as args.

Locally, the same command on a local checkout — `--github` with a personal token,
or omit it for stdout JSON. Identical code path (FR-001).

## Compensation owed (because `quality_override: true`)

The five-point self-check came back 3-of-5 not-true. `AGENTS.md` / `CLAUDE.md`
MUST carry:

- **Pinned `langchain` / `langgraph` versions** — API churn is the #1 agent-
  confusion source in this stack; pin and document the exact import paths the
  project uses.
- **An explicit graph convention** — one node per FR-006 phase, a typed
  Pydantic state object passed edge-to-edge, tools grouped by capability
  (GitHub / structural-search / text-search).
- **A review-output checklist** the developer uses to sanity-check agent
  findings before they are posted — this builds the "can judge agent output"
  muscle the self-check flagged as not-yet-there.
- **The severity taxonomy + line-anchor rules (FR-009/011) encoded as Pydantic
  schemas** so the agent's output shape is machine-validatable, not free-form.

## Still-open product questions (deferred to /10x-plan)

From the PRD's `## Open Questions`, these shape the core analysis loop and
should be resolved before the engine is built:

1. Fail-safe behavior when OpenRouter / GitHub errors mid-run (advisory exit
   code means the step should likely not fail CI, but the exact behavior is
   undecided).
2. Per-review cost ceiling — actual $-per-review cap and enforcement mechanism
   (max tokens / max agent steps / max model calls). Guardrail-load-bearing;
   LangGraph's recursion/step limit is a natural enforcement point.
3. Severity taxonomy for the hardcoded severity-to-signal mapping (FR-011).
4. Diff cap policy — cap size and segmentation strategy (FR-005).
5. Posting format under `--github` (PRD OQ #8) — plain PR comment vs. inline
   review with line-level annotations (FR-009 anchors). Affects which GitHub API
   path `PyGithub`/`httpx` use to post.
6. Target-branch / diff-base discovery (PRD OQ #9) — with no `--pr` input, how
   the tool learns the target branch to diff against (Actions env var?
   `git merge-base`? default-branch name?).
