# ast-grep-fix — Plan Brief

> Full plan: `context/changes/ast-grep-fix/plan.md`

## What & Why

The `sg` binary (ast-grep's short alias) is deprecated as of ast-grep 0.45.0 —
every invocation prints a deprecation banner ("`sg` is deprecated. Use
`ast-grep` instead."). `structural_search` still resolves and invokes `sg`,
so the tool trips its own deprecation warning on every structural search. We
switch every `sg` reference to the canonical `ast-grep` binary — a verified
drop-in (same `run --json=compact -p` CLI, identical JSON output).

## Starting Point

One production caller (`structural_search.py`), one unit-test file, one GHA
workflow template, and two top-level docs name the `sg` alias. `ast-grep` is
already installed locally alongside `sg` and answers the same CLI identically,
so the rename is string-literal only — no logic change.

## Desired End State

`structural_search` resolves and invokes `ast-grep` (never `sg`); the
consumer GHA workflow installs `/usr/local/bin/ast-grep`; `AGENTS.md` §f and
`README.md` document `ast-grep`. The full test matrix — including the live-LLM
smoke set (`make llm-test`) and a **real consumer-GHA smoke PR** on
`../target-o-meter` (Phase 5) — passes, proving the rename works both locally
and in the deployed pipeline.

## Key Decisions Made

| Decision                | Choice                     | Why (1 sentence)                                                                              | Source |
| ----------------------- | -------------------------- | --------------------------------------------------------------------------------------------- | ------ |
| Fallback to `sg`?       | No — `ast-grep` only       | Clean break matches the deprecation; `ast-grep` is the canonical name going forward.          | Plan   |
| GHA install target      | `/usr/local/bin/ast-grep`  | Matches the production lookup exactly; no legacy alias on the runner.                         | Plan   |
| CLI compatibility check | Reuse existing `run -p`    | `ast-grep` is a verified drop-in (same subcommand/flags/JSON), so no invocation logic changes. | Plan   |
| Archive doc edits       | Leave `context/archive/**` | Those describe past decisions, not current code — editing them rewrites history.              | Plan   |

## Scope

**In scope:** the `sg` → `ast-grep` rename in `structural_search.py`,
`test_tools.py`, `integration/github-actions-review.yml`, `AGENTS.md` §f, and
`README.md`; running `make check`, `make test`, and `make llm-test`; a
**consumer-GHA smoke PR** on `../target-o-meter` (Phase 5) that temporarily
points the consumer workflow at the unmerged feature branch to validate the
rename end-to-end before merge.

**Out of scope:** a `sg` fallback path; binary-version pinning; any change to
`text_search` (uses `rg`); edits to `context/archive/**` historical docs;
merging the smoke PR (it's a throwaway trigger, closed without merge).

## Architecture / Approach

Scoped find-and-replace across four surfaces, each independently verifiable:
(1) production code — the actual bug, (2) the unit test that pins it, (3) CI
+ docs, (4) the full verification run incl. live LLM smoke. The CLI
interface is identical, so only string literals change (binary name in
`which`/cmd, `(sg)` in degrade strings, `cmd="sg"` in a test exception, the
GHA install target path, prose in docs). The `app-x86_64-unknown-linux-gnu.zip`
**download URL is unchanged** — that's the release-asset filename (an ast-grep
artifact quirk), not the installed binary name.

## Phases at a Glance

| Phase | What it delivers                                        | Key risk                                                                        |
| ----- | ------------------------------------------------------- | ------------------------------------------------------------------------------- |
| 1. Production code     | `structural_search` calls `ast-grep`            | Missing an embedded `sg` string in a degrade path.                              |
| 2. Tests               | Updated + new name-pinning assertion            | Assertion too loose to catch a regression.                                      |
| 3. Integration + docs  | GHA installs `ast-grep`; docs match             | Accidentally editing the `app-`-prefix download URL (must stay).                |
| 4. Verification        | `make check` + `make test` + `make llm-test` green | Smoke flakiness masking a real rename failure (re-run once before investigating). |
| 5. Consumer GHA smoke  | Real PR on `../target-o-meter` proves the rename in the deployed pipeline | Forgetting to revert the consumer workflow's `@feature-branch` pointer after the smoke. |

**Prerequisites:** `OPENROUTER_API_KEY` set in `.env` (present) for
`make llm-test`; `ast-grep` binary on PATH (present, v0.45.0); push access to
both `krkruk/reviewer-target-o-meter` and `krkruk/target-o-meter` (present,
`gh` authed as `krkruk`); the feature branch pushed to `origin` before Phase 5.
**Estimated effort:** ~1 short session — mechanical rename + test runs + one
throwaway consumer PR.

## Open Risks & Assumptions

- **Cross-repo ordering coupling (Phase 5):** the consumer workflow installs
  from master, which doesn't carry the rename yet. Phase 5 temporarily points
  it at `@feature/update-ast-grep-configuration` — if that pointer isn't
  reverted, the consumer keeps tracking an unmerged branch. The plan makes the
  revert an explicit success criterion (5.8).
- **Consumer GHA workflows already deployed** still install `/usr/local/bin/sg`
  (copied pre-fix). They keep working until upstream removes `sg`, but should
  be re-copied from the updated template to silence the deprecation banner —
  a consumer-side action, no migration on this repo.
- **Smoke flakiness** from the live LLM could mask a rename-caused failure;
  mitigate by re-running once before investigating a smoke failure.

## Success Criteria (Summary)

- `structural_search` invokes `ast-grep` (no `sg` anywhere in production/tests/CI/docs).
- `make check`, `make test`, and `make llm-test` all pass — the live smoke run
  confirms the real `ast-grep` binary answers the agent's structural searches.
- The consumer GHA workflow installs `/usr/local/bin/ast-grep`.
- **Phase 5:** a real consumer-GHA run on `../target-o-meter` posts a review
  comment with no `sg` deprecation banner, then the smoke PR is closed and the
  consumer workflow reverted to the master install URL.
