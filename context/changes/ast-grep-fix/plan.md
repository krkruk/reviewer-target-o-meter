# ast-grep-fix Implementation Plan

## Overview

The `sg` binary (ast-grep's short alias) is deprecated as of ast-grep 0.45.0 —
invoking it prints a deprecation banner ("`sg` is deprecated. Use `ast-grep`
instead."). Replace every `sg` reference in the repo with the canonical
`ast-grep` binary so the tool stops invoking a deprecated alias and the
docs/CI match production.

## Current State Analysis

`structural_search` is the only production caller of the binary. It resolves
the binary with `shutil.which("sg")` and builds the command as
`["sg", "run", "--json=compact", "-p", pattern]`
(`reviewer-target-o-meter/src/reviewer_target_o_meter/agent/tools/structural_search.py:34,37`).
The error/degrade strings embed `(sg)` too (lines 35, 50). `ast-grep` is a
verified drop-in: the same `run --json=compact -p` invocation against a
sample `a + b` produced identical JSON locally (v0.45.0).

`sg` also appears in tests, the consumer GHA workflow, and docs:

- `tests/test_tools.py:102` — `subprocess.TimeoutExpired(cmd="sg", ...)` in the
  structural-search timeout test; `:85,:94` — comment/test-name mentioning `sg`.
- `integration/github-actions-review.yml:54-55` — downloads the prebuilt zip
  and `install -m 0755 ast-grep /usr/local/bin/sg` (installs the binary under
  the deprecated name). Comment at `:51` references `sg`.
- `AGENTS.md` §f (lines 142, 155, 158, 228) and `README.md` (lines 95, 244-245,
  248) document the `sg` name.
- `integration/README.md` mentions only `ast-grep` already (no change needed).

Both `ast-grep` and `sg` are present locally (`/usr/local/sbin/`), so the
unit tests' `shutil.which` mock continues to drive behavior; the live smoke
set (`make llm-test`) exercises the real binary end-to-end.

### Key Discoveries:

- `ast-grep` is a true CLI drop-in for `sg`: same subcommand (`run`), same
  flags (`--json=compact`, `-p`, `-l`), same JSON shape — verified locally
  (`ast-grep run --json=compact -p '$X + $Y' app.py` → identical match JSON).
- The decision is a **clean break**: `ast-grep` only, no `sg` fallback
  (user-confirmed). The GHA install lands the binary as `ast-grep` only.
- `text_search` is unaffected — it invokes `rg` (ripgrep), a separate binary.
- The test suite mocks `shutil.which`/`subprocess.run`
  (`tests/test_tools.py:20-45`), so the unit tests assert the binary-name
  string the tool passes through `which`/the cmd list — that's the load-bearing
  assertion to update.
- The live-LLM smoke set (`make llm-test`, `-m smoke`) is gated by `SMOKE=1`
  and `OPENROUTER_API_KEY` (set in `.env`); it exercises the real `ast-grep`
  binary via the `checks` agent's `structural_search` calls.

## Desired End State

- `structural_search` resolves and invokes `ast-grep` (never `sg`); its
  degrade strings name `ast-grep`.
- No occurrence of the `sg` alias remains in production code, tests, the GHA
  workflow, or top-level docs (`AGENTS.md`, `README.md`).
- `make check`, `make test`, and `make llm-test` all pass — the live smoke
  run confirms the real `ast-grep` binary answers the agent's structural
  searches end-to-end.
- The consumer GHA workflow installs the binary as `/usr/local/bin/ast-grep`.

## What We're NOT Doing

- **No `sg` fallback.** A clean break to `ast-grep` only; consumer
  environments with only the legacy `sg` alias will degrade to `text_search`
  (the intended end state per the deprecation).
- **No binary-version pin.** We consume whatever `ast-grep` release is current
  (presently 0.45.0); the CLI interface is stable across the versions we use.
- **No change to `text_search`** (it uses `rg`, unrelated to this fix).
- **No change to the tool's external contract** — same `structural_search`
  signature, same JSON-shape output, same degrade behavior; only the binary
  name changes.
- **No archive-doc edits.** `context/archive/**` references to `sg` are
  historical records of prior plans and are left untouched (they describe
  past decisions, not current code).

## Implementation Approach

A scoped find-and-replace across four surfaces, ordered so each phase is
independently verifiable: production code first (the actual bug), then the
unit test that pins it, then CI + docs, then the full verification run
(unit + live LLM smoke). The CLI interface is identical, so no logic changes
— only string literals (binary name in `which`/cmd, `(sg)` in degrade
strings, `cmd="sg"` in a test exception, the GHA install target path, and
prose in docs).

## Phase 1: Production code — switch `structural_search` to `ast-grep`

### Overview

Change the binary the tool resolves and invokes from `sg` to `ast-grep`, and
update the embedded degrade strings so they no longer name the deprecated alias.

### Changes Required:

#### 1. `structural_search` binary lookup + invocation

**File**: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/tools/structural_search.py`

**Intent**: The tool currently resolves and calls the deprecated `sg` alias;
switch it to the canonical `ast-grep` binary so invocations no longer trigger
the deprecation banner and the tool matches the docs going forward.

**Contract**: `shutil.which(...)` and the `cmd` list binary element change from
`"sg"` to `"ast-grep"`. The module docstring's "Wraps the ``sg`` (ast-grep)
binary." and the function docstring's "using ast-grep (sg)" both drop the `sg`
aliasing, naming only `ast-grep`. The two degrade strings (missing-binary and
the `OSError`/`FileNotFoundError` branch) change from
`"ast-grep (sg) unavailable on PATH; use text_search instead."` to
`"ast-grep unavailable on PATH; use text_search instead."`.

The `run --json=compact -p` invocation, the `lang` flag, the timeout, and the
output cap are unchanged — `ast-grep` is a verified drop-in for these args.

### Success Criteria:

#### Automated Verification:

- `make check` (ruff + mypy) passes from the package dir.
- `make test` (unit tests, `-m "not smoke"`) passes — in particular
  `test_structural_search_*` in `tests/test_tools.py`.

#### Manual Verification:

- `grep -rn '\bsg\b' src/` returns no hits (only `ast-grep` references remain).
- `ast-grep run --json=compact -p '$X + $Y' <file>` still returns match JSON
  locally (already verified during planning; re-confirm if the local binary
  changes).

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Tests — update `test_tools.py` `sg` references

### Overview

Update the structural-search test's `sg` references to `ast-grep` and add an
explicit assertion that the tool passes `"ast-grep"` (not `"sg"`) through to
`shutil.which` and the `subprocess.run` cmd list — pinning the fix against
regression.

### Changes Required:

#### 1. Timeout-test exception + comment + test name

**File**: `reviewer-target-o-meter/tests/test_tools.py`

**Intent**: The timeout test raises `subprocess.TimeoutExpired(cmd="sg", ...)`
and the section header + a test name mention `sg`; align them with the
renamed binary so the tests describe what the tool actually invokes.

**Contract**: `test_structural_search_catches_timeout` raises
`TimeoutExpired(cmd="ast-grep", ...)`; the `# --- structural_search (ast-grep) ---`
section header already names `ast-grep` (keep); the
`test_structural_search_degrades_when_sg_missing` test is renamed to
`..._degrades_when_ast_grep_missing` (and its body is unchanged — it asserts
the degrade string contains `"ast-grep"` and `"text_search"`, which the new
string still satisfies).

#### 2. Pin the binary name in the command

**File**: `reviewer-target-o-meter/tests/test_tools.py`

**Intent**: Guard against a silent regression back to `sg` by asserting the
recorded `subprocess.run` cmd starts with `"ast-grep"`.

**Contract**: Extend `test_structural_search_returns_stdout` (or add a focused
test) to read the recorded `calls[0][0]` cmd list and assert
`calls[0][0][0] == "ast-grep"` (the binary is the first element). This is the
load-bearing assertion: the existing `_patch_subprocess` helper already
records every `(cmd, kw)` pair, so no new infrastructure is needed.

### Success Criteria:

#### Automated Verification:

- `make test` passes with the renamed/updated structural-search tests.
- The new/extended assertion fails if the tool is reverted to `sg`
  (verified by temporarily reverting — optional, implementer's discretion).

#### Manual Verification:

- `grep -rn '"sg"' tests/` returns no hits.

---

## Phase 3: Integration + docs — GHA install path + AGENTS.md/README

### Overview

Align the consumer GHA workflow and the top-level docs with the renamed
binary: the workflow installs `/usr/local/bin/ast-grep`, and the docs name
`ast-grep` (not `sg`) as the binary.

### Changes Required:

#### 1. Consumer GHA install step

**File**: `integration/github-actions-review.yml`

**Intent**: The workflow currently installs the downloaded binary as
`/usr/local/bin/sg` (the deprecated name); install it as
`/usr/local/bin/ast-grep` so the runner matches what `structural_search` now
looks up.

**Contract**: In the `Install ast-grep (structural_search tool)` step, change
`install -m 0755 ast-grep /usr/local/bin/sg` →
`install -m 0755 ast-grep /usr/local/bin/ast-grep`. The `curl ... app-x86_64-unknown-linux-gnu.zip`
download URL is **unchanged** — that's the release asset filename (the `app-`
prefix is an ast-grep release-artifact quirk, not the installed binary name;
AGENTS.md §f documents this). The inline comment's "If `sg` is unavailable…"
reworded to name `ast-grep`.

#### 2. AGENTS.md §f recipe + prose

**File**: `AGENTS.md`

**Intent**: §f records the ast-grep GHA install recipe so S-02 doesn't
re-discover it; the recipe and prose still name `sg`, which would lead a
future maintainer to reinstall the deprecated alias.

**Contract**: In §f, the install recipe's
`install -m 0755 ast-grep /usr/local/bin/sg` →
`install -m 0755 ast-grep /usr/local/bin/ast-grep`. The recipe's
`curl ... app-x86_64-unknown-linux-gnu.zip` URL and the `app-` prefix note
stay (still accurate). Prose references "`ast-grep` (`sg`)" → "`ast-grep`"
where they describe the runtime binary (the `(sg)` aliasing is no longer
relevant). Keep the "asset carries an `app-` prefix" NOTE verbatim — it's
about the release zip, not the installed binary. The §(g)/(h) line references
to "`sg` is unavailable" → "`ast-grep` is unavailable".

#### 3. README.md binary references

**File**: `README.md`

**Intent**: The README documents the runtime deps and the GHA install recipe;
its `sg` references would mislead a consumer setting up the tool.

**Contract**: `README.md:95` "`ast-grep` (`sg`)" → "`ast-grep`". The
`README.md:244-245` install recipe `install -m 0755 ast-grep /usr/local/bin/sg`
→ `install -m 0755 ast-grep /usr/local/bin/ast-grep`, and the `README.md:248`
"If `sg` is unavailable…" → "If `ast-grep` is unavailable…". The
`app-x86_64-unknown-linux-gnu.zip` download URL stays.

### Success Criteria:

#### Automated Verification:

- `grep -rn 'sg' integration/github-actions-review.yml AGENTS.md README.md`
  returns no hits naming the runtime binary (the `app-`-prefix download URL
  and `sg.zip` temp filename may remain if the implementer keeps them — they
  are not the installed binary name; prefer renaming `sg.zip` → `ast-grep.zip`
  for clarity, but it's optional).
- YAML still parses (the workflow file is valid).

#### Manual Verification:

- Read the updated §f recipe top-to-bottom — the `app-` prefix NOTE still
  makes sense and the install target is `ast-grep`.

---

## Phase 4: Verification — full test run incl. live LLM smoke

### Overview

Run the entire verification matrix the AGENTS.md §g prescribes, **including
the live-LLM smoke set** the task explicitly requires, to confirm the rename
is correct end-to-end (the smoke set drives the real `ast-grep` binary through
the agent's `structural_search` calls).

### Changes Required:

#### 1. Run `make check`

**File**: `reviewer-target-o-meter/` (package dir)

**Intent**: Static verification (ruff + mypy) catches lint/type regressions
from the string-literal edits.

**Contract**: `make check` exits 0.

#### 2. Run `make test`

**File**: `reviewer-target-o-meter/` (package dir)

**Intent**: The mocked unit suite (incl. the updated structural-search tests
and the diff-scoping smoke-signal guard) confirms the rename didn't change
behavior where the binary is mocked.

**Contract**: `make test` (`uv run pytest -m "not smoke"`) exits 0 — all
non-smoke tests pass.

#### 3. Run `make llm-test` (live OpenRouter smoke set)

**File**: `reviewer-target-o-meter/` (package dir)

**Intent**: The task explicitly requires running the tests that rely on LLM
calls for the review. The smoke set (`-m smoke`, gated by `SMOKE=1`) drives
the real `ast-grep` binary through the `checks` agent's `structural_search`
invocations against the fixtures — this is the only verification that
exercises the actual renamed binary end-to-end.

**Contract**: `make llm-test` (`SMOKE=1 uv run pytest -m smoke`) exits 0.
Requires `OPENROUTER_API_KEY` (present in `.env`). If a smoke test fails due
to transient LLM/provider flakiness (not the rename), re-run once before
investigating; a rename-caused failure would surface as a
`structural_search`-related error in the smoke output.

### Success Criteria:

#### Automated Verification:

- `make check` — ruff + mypy pass.
- `make test` — unit suite (excl. smoke) passes.
- `make llm-test` — live-LLM smoke set passes (real `ast-grep` binary
  exercised end-to-end).

#### Manual Verification:

- Final sweep: `grep -rn --exclude-dir=.git --include='*.py' --include='*.yml' --include='*.md' '\bsg\b' .`
  returns no production/test/integration/top-level-doc hits (archive docs are
  expected to retain historical `sg` references and are excluded).

---

## Phase 5: Consumer GHA smoke — end-to-end via a real PR on `../target-o-meter`

### Overview

Prove the rename works on the real consumer GitHub Actions pipeline, not just
under `make llm-test` locally. Modeled on the archived change-input-pipeline
Phase 6: create a **mock change** (a trivial, throwaway commit) on the
consumer repo purely to trigger the `review` workflow, and confirm the runner
installs `/usr/local/bin/ast-grep` and the `checks` agent's
`structural_search` answers without any deprecation banner.

### CRITICAL — cross-repo coupling (ordering):

The fix lives on `feature/update-ast-grep-configuration` in THIS repo and is
**not yet on master**. The consumer workflow installs from
`git+https://github.com/krkruk/reviewer-target-o-meter` (default branch =
master). So the smoke runs in three sub-steps that MUST be done in this order:

1. **Land the fix first** (Phases 1-4 done; the rename is on the feature branch).
2. **Temporarily point the consumer workflow at the feature branch** so the
   GHA runner picks up the renamed `structural_search` before it's on master.
3. **Run the smoke PR**, observe the green run + posted comment, then
   **revert the consumer workflow** to the master install URL (cleanup).

This mirrors the archived Phase 6's "@<ref>" install-pointer technique. Once
the fix merges to master (a later PR), the consumer workflow's default URL
already points at master and no temporary edit is needed.

### Changes Required:

#### 5.1 Push the feature branch (so the consumer can install from it)

**File**: `feature/update-ast-grep-configuration` (this repo)

**Intent**: The consumer's GHA install step will pin `@feature/update-ast-grep-configuration`;
that branch must be on `origin` for the runner to fetch it.

**Contract**: `git push -u origin feature/update-ast-grep-configuration`. The
branch already exists locally as the working branch; push it after Phases 1-4
land (the commit carrying the rename must be on the pushed branch). No PR to
master is opened in this change — the smoke validates the branch directly.

#### 5.2 Temporarily point the consumer workflow at the feature branch

**File**: `../target-o-meter/.github/workflows/review.yml` (CONSUMER repo — temporary edit)

**Intent**: The consumer workflow currently installs from the default branch
(master), which does NOT yet carry the rename. Point the `uv tool install` URL
at `@feature/update-ast-grep-configuration` so the runner exercises the
renamed `structural_search`. Also update the `Install ast-grep` step to install
`/usr/local/bin/ast-grep` (the production lookup now expects that name).

**Contract**: In the consumer's `review.yml`:

```yaml
# BEFORE (master, no rename)
uv tool install "git+https://github.com/krkruk/reviewer-target-o-meter#subdirectory=reviewer-target-o-meter"
...
install -m 0755 ast-grep /usr/local/bin/sg

# AFTER (temporary, points at the feature branch + renamed install target)
uv tool install "git+https://github.com/krkruk/reviewer-target-o-meter@feature/update-ast-grep-configuration#subdirectory=reviewer-target-o-meter"
...
install -m 0755 ast-grep /usr/local/bin/ast-grep
```

This edit is committed to a **throwaway consumer branch** (e.g.
`feature/test-ast-grep-rename`), NOT master — it's reverted/abandoned after
the smoke. Document in the commit message that this is a temporary
smoke-trigger pointing at an unmerged feature branch. This is the one
cross-repo edit; it's clearly described and scoped to the smoke.

#### 5.3 Create a mock change on the consumer to trigger the workflow

**File**: `../target-o-meter` (consumer repo, on the throwaway branch)

**Intent**: The `review` workflow fires on `pull_request`. A mock change
(trivial commit) on a throwaway branch + an opened PR is the trigger — its
content is irrelevant; it exists only to exercise the pipeline. Mirrors the
archived Phase 6's `feature/test-pull-request` mechanism.

**Contract**: On a fresh branch off consumer `master` (e.g.
`feature/test-ast-grep-rename`), make a trivial, clearly-throwaway commit —
e.g. touch an empty `SMOKE_TRIGGER.txt` or add a one-line comment to a
non-critical file. The commit message MUST mark it as a smoke trigger, e.g.
`chore: smoke trigger for ast-grep rename (throwaway)`. Include the §5.2
workflow edit in the same branch. Push the branch and open a PR against the
consumer's `master` with a body noting it's a throwaway smoke trigger to be
closed without merge.

#### 5.4 Observe the workflow run + posted comment

**File**: (observation — `gh run watch` / the PR's Actions tab)

**Intent**: Confirm the end-to-end path: the runner installs the renamed tool
from the feature branch, installs `/usr/local/bin/ast-grep`, runs the review,
and posts a Markdown comment. Critically: **no `sg` deprecation banner** in
the run logs (the whole point of the fix), and `structural_search` answers
(the agent's structural queries return JSON, not the degrade string).

**Contract**: The `review` workflow run concludes `success` (advisory exit +
`continue-on-error: true` keeps it green even when findings are flagged). A
real Markdown comment from `github-actions[bot]` appears on the smoke PR. The
"Install ast-grep" step log shows `install -m 0755 ast-grep /usr/local/bin/ast-grep`
and the run step shows no `sg is deprecated` warning. Use
`gh run list --workflow=review.yml --limit 1` + `gh run view <id> --log` to
inspect; `gh pr view <n> --comments` to confirm the comment landed.

#### 5.5 Cleanup — revert the consumer workflow + close the smoke PR

**File**: `../target-o-meter` (consumer repo)

**Intent**: The §5.2 workflow edit and the smoke branch are throwaway. Close
the PR without merging and revert the consumer workflow to its master
install URL so the consumer is left clean. The permanent `ast-grep` install
target lands on the consumer only when THIS fix merges to master and the
consumer re-copies the template (a later, separate action).

**Contract**: Close the smoke PR (do not merge). If the §5.2 edit was
committed directly to a consumer branch, delete that branch. Restore the
consumer's `review.yml` to the master install URL
(`git+https://github.com/krkruk/reviewer-target-o-meter#subdirectory=reviewer-target-o-meter`)
if it was changed on a long-lived branch; if it only ever lived on the
throwaway smoke branch, deleting the branch suffices. Leave a note in the PR
body / a comment recording the run URL for the change record.

### Success Criteria:

#### Automated Verification:

- `gh run list --workflow=review.yml --branch <smoke-branch> --limit 1`
  shows the run with conclusion `success`.
- `gh pr view <smoke-pr> --comments` shows a comment from
  `github-actions[bot]` (the review was posted).

#### Manual Verification:

- The run's "Install ast-grep" step log installs to
  `/usr/local/bin/ast-grep` (not `/usr/local/bin/sg`).
- The run step log contains **no** `sg is deprecated` warning — the rename
  silenced it end-to-end.
- The posted review comment shows `structural_search` produced real findings
  anchored on diff-touched lines (not the "ast-grep unavailable, use
  text_search" degrade string) — i.e. the renamed binary actually answered.
- Smoke PR closed without merging; consumer workflow left on the master
  install URL (or the throwaway branch deleted).

**Implementation Note**: After completing this phase and all automated
verification passes, pause here for manual confirmation from the human that
the manual testing was successful before proceeding to the next phase.

---

## Testing Strategy

### Unit Tests:

- `test_structural_search_returns_stdout` — extended to assert the recorded
  cmd's first element is `"ast-grep"` (pins the binary name).
- `test_structural_search_degrades_when_ast_grep_missing` (renamed from
  `..._sg_missing`) — asserts the degrade string still contains `"ast-grep"`
  and `"text_search"`.
- `test_structural_search_catches_timeout` — `TimeoutExpired(cmd="ast-grep", ...)`.
- `test_structural_search_caps_output` — unchanged (output cap is binary-agnostic).

### Integration Tests:

- `make llm-test` (live smoke) is the in-repo integration check: it runs the
  full `checks` agent against fixtures with the real `ast-grep` binary on
  PATH, exercising `structural_search` end-to-end.
- Phase 5 is the **cross-repo integration check**: the consumer GHA pipeline
  installs the renamed tool + `ast-grep` and runs the review against a real
  PR, proving the rename works in the deployed consumer environment (not just
  locally). It's the analog of the archived change-input-pipeline Phase 6.

### Manual Testing Steps:

1. `grep -rn '\bsg\b' src/ tests/ integration/ AGENTS.md README.md` — clean.
2. `ast-grep run --json=compact -p '$X + $Y' <some file>` — returns JSON.
3. Read the updated GHA install step + AGENTS.md §f top-to-bottom.
4. **Phase 5 consumer smoke**: open the throwaway PR on `../target-o-meter`,
   watch the `review` run, confirm no `sg` deprecation banner and a posted
   comment, then close the PR + revert the consumer workflow (Phase 5).

## Performance Considerations

None. The rename is string-literal only; the binary's CLI, output shape, and
latency are identical (verified: `ast-grep` and `sg` are the same binary —
`sg` is a deprecated alias that dispatches to `ast-grep`).

## Migration Notes

- **Consumer GHA workflows already deployed** (copied from the template before
  this fix) install `/usr/local/bin/sg`. They keep working until the installed
  `sg` binary is itself removed upstream — but they should be re-copied from
  the updated template to install `ast-grep` and silence the deprecation banner
  in their run logs. This is a consumer-side action, documented in the updated
  `integration/README.md` recipe (no code migration needed on this repo's side).
- **The Phase 5 smoke is the migration dry-run for the consumer.** It
  temporarily points the consumer workflow at the unmerged feature branch
  (`@feature/update-ast-grep-configuration`) and lands the `ast-grep` install
  target on a throwaway branch — proving the consumer pipeline works with the
  rename before this fix reaches master. Once the fix merges to master, the
  consumer re-copies the template (default master URL) and gets the rename
  permanently; the Phase 5 throwaway branch is discarded.
- No database/state/config migration — the change is code/docs only.

## References

- Deprecated alias warning: `sg` invocation prints
  "WARNING: `sg` is deprecated. Use `ast-grep` instead." (ast-grep 0.45.0).
- Production caller: `reviewer-target-o-meter/src/reviewer_target_o_meter/agent/tools/structural_search.py:34,37`
- Tests: `reviewer-target-o-meter/tests/test_tools.py:85,94,102`
- GHA install: `integration/github-actions-review.yml:49-55`
- Docs recipe: `AGENTS.md` §f (lines 140-160), `README.md:235-248`
- Degrade philosophy (FR-010): `AGENTS.md` §(d) "Both tools degrade"

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Production code — switch `structural_search` to `ast-grep`

#### Automated

- [x] 1.1 `make check` (ruff + mypy) passes
- [x] 1.2 `make test` (unit tests, `-m "not smoke"`) passes

#### Manual

- [x] 1.3 `grep -rn '\bsg\b' src/` returns no hits
- [x] 1.4 `ast-grep run --json=compact -p '$X + $Y' <file>` returns match JSON locally

### Phase 2: Tests — update `test_tools.py` `sg` references

#### Automated

- [ ] 2.1 `make test` passes with the renamed/updated structural-search tests
- [ ] 2.2 New/extended cmd-name assertion (`calls[0][0][0] == "ast-grep"`) present and passing

#### Manual

- [ ] 2.3 `grep -rn '"sg"' tests/` returns no hits

### Phase 3: Integration + docs — GHA install path + AGENTS.md/README

#### Automated

- [ ] 3.1 `grep` sweep over `integration/github-actions-review.yml AGENTS.md README.md` returns no runtime-binary `sg` hits
- [ ] 3.2 Workflow YAML still parses

#### Manual

- [ ] 3.3 Read updated §f recipe top-to-bottom — `app-` prefix NOTE intact, install target is `ast-grep`

### Phase 4: Verification — full test run incl. live LLM smoke

#### Automated

- [ ] 4.1 `make check` — ruff + mypy pass
- [ ] 4.2 `make test` — unit suite (excl. smoke) passes
- [ ] 4.3 `make llm-test` — live-LLM smoke set passes (real `ast-grep` binary exercised end-to-end)

#### Manual

- [ ] 4.4 Final sweep: `grep -rn ... '\bsg\b' .` clean for production/test/integration/top-level docs (archive excluded)

### Phase 5: Consumer GHA smoke — end-to-end via a real PR on `../target-o-meter`

#### Automated

- [ ] 5.1 `feature/update-ast-grep-configuration` pushed to `origin` (Phases 1-4 landed on the branch)
- [ ] 5.2 Consumer `review.yml` temporarily pointed at `@feature/update-ast-grep-configuration` + `ast-grep` install target, on a throwaway branch
- [ ] 5.3 Mock-change PR opened on `../target-o-meter` (throwaway smoke trigger)
- [ ] 5.4 `gh run list --workflow=review.yml` shows the run `success`; `gh pr view <n> --comments` shows the `github-actions[bot]` comment

#### Manual

- [ ] 5.5 "Install ast-grep" step log installs to `/usr/local/bin/ast-grep` (not `sg`)
- [ ] 5.6 Run step log contains no `sg is deprecated` warning (the rename silenced it end-to-end)
- [ ] 5.7 Posted comment shows `structural_search` produced real anchored findings (not the degrade string)
- [ ] 5.8 Smoke PR closed without merging; consumer workflow reverted to master install URL / throwaway branch deleted
