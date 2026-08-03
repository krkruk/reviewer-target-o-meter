# Change Input Pipeline — Plan Brief

> Full plan: `context/changes/change-input-pipeline/plan.md`

## What & Why

Build F-02 — the tool accepts a checked-out directory, discovers the target
branch, computes a capped diff, and loads repo context — plus the env-driven
GitHub-comment posting half of S-02, and a per-dimension findings cap. The
consumer repo (`./target-o-meter`) currently has no automated review signal;
this lands one. Motivation: roadmap F-02 (`context/foundation/roadmap.md:65`)
is the foundation both downstream slices consume, and your instruction pulled
the posting half of S-02 forward (resolving OQ#8 as "plain PR comment").

## Starting Point

F-01 (`agent-runtime-finding-schema`, archived) landed the agent runtime +
typed `Finding`/`Severity` schema + OpenRouter provider. The CLI
(`cli.py:35-41`) currently injects an inline `_FIXTURE_DIFF`; `Config.from_env`
reads only the provider vars; `report` caps findings at a flat 10. `gitpython`
is a direct dep; `httpx` is transitive only. `./target-o-meter` (Django
project, `krkruk/target-o-meter`) has CI workflows but no review signal.

## Desired End State

A PR opened on `./target-o-meter` triggers the `review` workflow; the tool
discovers the base, computes a capped diff, loads context, runs analysis, and
posts a Markdown comment (verdict + findings table + collapsible details) —
exiting advisory, never blocking the merge. Run locally without PR env vars,
the same code path emits the FindingsReport JSON to stdout (today's behavior,
unchanged). Findings cap at 5 per Dimension. Degrades loudly, never fails CI.

## Key Decisions Made

| Decision                                       | Choice                                                                              | Why (1 sentence)                                                                                               | Source   |
| ---------------------------------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | -------- |
| Diff base discovery (OQ#9)                     | `BASE_REF` → `GITHUB_BASE_REF` → `git merge-base HEAD main/master` → degrade        | Authoritative in CI, heuristic locally; honours FR-002 "directory as sole input".                              | Plan     |
| Diff cap policy (OQ#4)                         | ~20k-char budget, file-boundary cut, truncation marker                              | One knob, matches the existing 20k-char tool-output convention in AGENTS.md.                                   | Plan     |
| Context loading scope (FR-004)                 | `AGENTS.md` + `context/foundation/*` + current-change docs; ~8k-char cap            | Plan-tolerant, tool-driven design (source fetched by agent tools, not pre-loaded per AGENTS.md §b).            | Plan     |
| Per-category cap                               | Dimension, 5 each, replaces flat 10, enforced in BOTH prompt + `report` node        | Matches the existing 7-dimension taxonomy; host-side guard is load-bearing (prompts are unreliable).           | Plan     |
| Posting format (OQ#8)                          | Plain PR comment — Markdown table + collapsible `<details>`                         | Resolves OQ#8 for this slice; inline annotations deferred to the original S-02.                                | Plan     |
| Posting library                                | `httpx` (already transitive), declared direct                                       | One HTTP client already in the stack; no new heavy dep (PyGithub) for a single POST.                           | Plan     |
| Env-var trigger                                | `PR_NUMBER` + `GITHUB_TOKEN` + `GITHUB_REPOSITORY` all present → post; else stdout  | Verified against GHA docs: `PR_NUMBER`/`GITHUB_TOKEN` are NOT auto-provided — workflow maps them explicitly.    | Research |
| Failure-mode strategy                          | Always degrade to stdout + stderr `WARNING:`, exit advisory; never fail CI          | Honours FR-008 advisory design; reviewer always gets some signal.                                              | Plan     |
| Workflow yaml location                         | Template versioned here under `integration/`; copy landed in `./target-o-meter`     | Workflow must run in the consumer repo to fire on the consumer's PRs; template stays versioned with the tool.   | Plan     |
| `_FIXTURE_DIFF` retained                       | Stays as a system-test asset; production CLI computes the real diff                 | Quick tests still need a known-small diff; `./target-o-meter` is for manual real-life runs.                    | Plan     |

## Scope

**In scope:**
- New `diff.py` (base discovery + capped diff via gitpython).
- New `context_loader.py` (AGENTS.md + foundation + change docs, capped).
- Per-dimension findings cap (5) replacing the flat 10; system-prompt + host-side.
- New `github.py` (`render_comment` + `post_comment` via httpx).
- `Config.from_env` extended; CLI branching stdout-vs-post; `_FIXTURE_DIFF` retained.
- `.env.example` rewritten with the corrected GHA env-var contract.
- `integration/github-actions-review.yml` + `integration/README.md`.
- Workflow copied into `./target-o-meter/.github/workflows/review.yml`.
- Smoke test against `../target-o-meter`.

**Out of scope:**
- Inline review annotations / line-level review comments (future S-02).
- Merge blocking (FR-008 Non-Goal).
- GHA workflow in THIS repo (fires only in the consumer).
- `--github` CLI flag (mode switch is env-driven).
- Pre-loading source into context (agent tools fetch on demand).
- Retry/backoff on posting.
- PyGithub.
- Analysis methodology changes (S-01's job).

## Architecture / Approach

Plain-function libraries (`diff.py`, `context_loader.py`, `github.py`) called
by the CLI — not `@tool`s, not graph nodes. The graph spine stays
`START → context_load → plan_discovery → checks → report → END`; only what the
CLI injects at `START` changes (real diff + real context). Every new module
follows the existing degrade convention (return safe fallback + stderr
`WARNING:`, never raise out). The `report` node keeps the load-bearing
host-side re-check; the per-dimension cap is enforced there AND in the system
prompt (trust-but-verify). CLI branches on `config.post_to_github`; posting
errors fall back to stdout.

## Phases at a Glance

| Phase | What it delivers                                              | Key risk                                                                         |
| ----- | ------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 1     | Real capped diff via gitpython; base-ref discovery chain      | Base heuristic picks wrong ref when default branch is neither main nor master.   |
| 2     | Context loader (AGENTS.md + foundation + change docs), capped | "Current change" discovery globs all non-archived change dirs — may over-include. |
| 3     | Per-dimension cap (5) in prompt + `report` node               | Cap silently distorts signal if model oversubscribes one dimension.              |
| 4     | `github.py`: Markdown render + httpx POST                      | Markdown renders poorly on GitHub if table escapes are wrong.                    |
| 5     | `Config` + CLI mode switch; `.env.example` rewrite            | Posting failure path doesn't degrade cleanly → CI breaks (mitigated by tests).   |
| 6     | Workflow template + consumer integration + smoke              | Workflow doesn't fire / posts broken comment on the live PR.                     |

**Prerequisites:** F-01 (done). Write access to `./target-o-meter` for Phase
6.3. `OPENROUTER_API_KEY` + a `GITHUB_TOKEN` with comment scope on
`./target-o-meter` for the live manual verification.
**Estimated effort:** ~5-7 sessions across 6 phases (solo, after-hours).

## Open Risks & Assumptions

- **Default-branch heuristic** assumes `main` or `master`. If a consumer uses
  another default (e.g. `develop`), `BASE_REF` must be set explicitly. The
  `.env.example` documents this.
- **"Current change" discovery** loads all non-archived `context/changes/*/`
  docs; on repos with many open changes the ~8k context cap will truncate,
  possibly dropping the relevant plan. Acceptable for v1 (cap is visible);
  revisit if signal degrades.
- **`PR_NUMBER`/`GITHUB_TOKEN` not auto-provided** — the workflow MUST map them
  explicitly. If the consumer copies the template but forgets the mapping, the
  tool silently runs in stdout mode inside CI (no post). Mitigated by the
  integration README + the smoke test.
- **httpx as a new direct dep** — re-locking is required; no resolver churn
  expected (it's already transitive).
- **Tool not yet published to PyPI** — the consumer workflow installs it from
  git or a path; the `integration/README.md` documents this with a TODO for a
  future PyPI publish.

## Success Criteria (Summary)

- A `./target-o-meter` PR gets a Markdown review comment automatically;
  workflow exits green even when findings are flagged.
- Locally, the same CLI emits the FindingsReport JSON to stdout (unchanged)
  with a real computed diff + loaded context.
- No dimension exceeds 5 findings; degrade paths emit stderr warnings and
  never fail CI.
