# Integrating reviewer-target-o-meter into a consumer repo

`reviewer-target-o-meter` reviews a checked-out PR and posts its findings as a
Markdown PR comment (verdict + findings table + collapsible details). It runs
read-and-flag only — it never executes the reviewed project's test/lint/build
commands (PRD Non-Goal) — and its exit code is advisory: it never blocks a merge
(FR-008).

This guide wires the tool into a consumer repo's GitHub Actions so a review
comment appears automatically on every pull request.

## What this does

When a PR opens or updates on the consumer repo, the `review` workflow:

1. Checks out the PR with full history (`fetch-depth: 0` — the merge-base needs it).
2. Installs `uv`, the tool, and `ast-grep`.
3. Runs `reviewer-target-o-meter .` over the workspace.
4. The tool discovers the base ref, computes a capped diff, loads the repo's
   review context (AGENTS.md + foundation + current change docs), runs the
   analysis, and posts a Markdown comment on the PR.

The step exits green even when findings are flagged (advisory — the run step
carries `continue-on-error: true` so the advisory exit 1 doesn't fail CI; FR-008).
A missing `OPENROUTER_API_KEY` raises before any work; with `continue-on-error`
that's masked too, so confirm the secret is set on first setup (the tool's
stderr WARNING + empty report are the visible signal if it isn't).

## Env vars

| Var | GitHub Actions source | Required? |
|---|---|---|
| `OPENROUTER_API_KEY` | `${{ secrets.OPENROUTER_API_KEY }}` | **yes** — set this secret in the consumer repo |
| `PR_NUMBER` | `${{ github.event.pull_request.number }}` | yes (to post) — map explicitly |
| `GITHUB_TOKEN` | `${{ secrets.GITHUB_TOKEN }}` | yes (to post) — auto-provided, but map explicitly |
| `GITHUB_REPOSITORY` | auto-provided by the runner (`owner/repo`) | auto |
| `GITHUB_API_URL` | auto-provided (`https://api.github.com`) | auto |
| `GITHUB_BASE_REF` | auto-provided on `pull_request` (the target branch) | auto |
| `BASE_REF` | set to force a base (overrides the chain) | optional |

Mode switching is env-driven (no `--github` flag): the tool posts a comment
ONLY when `PR_NUMBER` + `GITHUB_TOKEN` + `GITHUB_REPOSITORY` are all present;
otherwise it emits the FindingsReport JSON to stdout.

## Setup

1. **Copy the workflow** into the consumer repo:

   ```bash
   cp integration/github-actions-review.yml ../<consumer>/.github/workflows/review.yml
   ```

2. **Set the `OPENROUTER_API_KEY` secret** in the consumer repo (Settings →
   Secrets and variables → Actions → New repository secret). `GITHUB_TOKEN` is
   auto-provided — do not create it.

3. **Point the install source at the tool.** The workflow template installs
   from a git URL by default (Option A); switch to a sibling editable checkout
   (Option B) for local development. The tool is not yet on PyPI — a TODO in the
   workflow marks the switch point once published.

4. **Open/update a PR** — the `review` workflow fires and posts the comment.

## Local testing

Run the same code path locally without posting (stdout JSON mode):

```bash
# from the reviewer-target-o-meter package dir
make run DIR=../<consumer>
```

To exercise the posting path locally against a real PR:

```bash
PR_NUMBER=<n> GITHUB_TOKEN=<tok> GITHUB_REPOSITORY=<owner>/<repo> \
  make run DIR=../<consumer>
```

A bad token degrades to stdout JSON + a `WARNING:` on stderr; the exit stays
advisory (no crash, no broken comment).

## What streams where (stdout vs stderr)

The tool keeps stdout and stderr strictly separate, so the GHA step log shows
both with no workflow edit:

- **stdout** — the machine-readable `FindingsReport` JSON (FR-007). Never parse
  stderr for the report.
- **stderr** — the human-readable **INFO step trace** (review start/mode → diff
  computed → context/plan loaded → each graph node → review-complete findings/
  flagged/exit-code counts → post attempt/result), **and**, just before exit, a
  **Markdown preview** of the exact comment that is (or would be) posted to the
  PR. The preview is the payload, not a log line, so it is always shown.

Set `LOG_LEVEL=WARNING` to silence the step trace and keep just the preview, or
`LOG_LEVEL=DEBUG` for everything (default `INFO`). Logs are metadata-only — they
never carry the diff/context/plan/report bodies; the report body is shown once,
via the dedicated preview.

## Degrade behavior

The tool never fails CI on its own output:

- A non-integer `PR_NUMBER` disables posting (WARNING on stderr) rather than crashing.
- A posting failure falls back to stdout JSON + a WARNING; exit stays advisory.
- A missing `OPENROUTER_API_KEY` fails the step fast — before any work — so it
  never posts a broken comment. Set the secret to fix it.
- A recursion/timeout/parse failure degrades to a partial or empty report with
  an advisory exit (FR-008).
