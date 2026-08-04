# PROD INFO Logging + Markdown Preview — Plan Brief

> Full plan: `context/changes/prod-logging-markdown-preview/plan.md`
> Change: `context/changes/prod-logging-markdown-preview/change.md`

## What & Why

The tool is **silent on success**: in posting mode it posts and exits (empty
stdout, no step trace); in stdout mode the only output is the JSON report. So in
the default GitHub Actions run the step log shows "only the initial few lines"
(the runner's headers), with no way to see what the tool did or what it posted.
This plan adds INFO-level step tracking to stderr and echoes the final
`render_comment()` Markdown to stderr just before exit — so the reviewer gets
full PROD visibility into the process and the exact report payload. **Logging
only; no business-logic change.**

## Starting Point

No structured logging exists today (`grep` for `logging` → 0 hits); the only
observability is `_util.warn()` (`_util.py:15`) — a `WARNING:` line to stderr on
degrade paths, used by `diff.py`/`context_loader.py`/`plan_loader.py`/`config.py`/
`cli.py`. The GitHub posting mechanism already ships (`github.py`, wired in
`cli.py:58-78`), and `render_comment()` already produces the exact Markdown to
reuse as the preview. stdout is a machine-readable JSON contract (FR-007).

## Desired End State

Running `reviewer-target-o-meter <dir>` (locally or in the consumer GHA
workflow) emits: (1) a metadata-only INFO step trace on stderr at every pipeline
step; (2) the final Markdown report on stderr just before exit (the exact PR
payload); (3) unchanged pure-JSON stdout. Verbosity is controlled by `LOG_LEVEL`
(default `INFO`); the Markdown preview is always shown (it is the payload, not
noise). Exit codes, posting behavior, the JSON contract, and all degrade paths
are identical to today.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Change identity | Rename `github-review-posting` → `prod-logging-markdown-preview` | The posting code already ships; a logging-only task needs an honest folder name for the impl-review pass. | Plan |
| Markdown preview destination | stderr, in both posting and stdout modes | Keeps stdout the pure JSON contract (FR-007) while giving humans/CI logs the exact PR payload. | Plan |
| Verbosity control | `LOG_LEVEL` env var, default `INFO` | Matches the env-driven `Config` pattern; enables PROD escalation to DEBUG without a redeploy. | Plan |
| Event granularity | Comprehensive — INFO at every pipeline step | Directly satisfies "fully track in PROD the steps"; metadata only. | Plan |
| Payload safety | Metadata only — never log diff/context/plan/report bodies | Honors AGENTS.md §e (no secrets/source leaked); the report body shows once via the preview. | Plan |
| `_warn()` fate | Route through the new logger (no call-site churn) | One unified output channel; preserves the `WARNING:` token the existing tests assert on. | Plan |
| Logger capture under tests | `configure_logging` runs at runtime + is idempotent | Binds to the `CliRunner`-redirected stderr; avoids duplicate handlers across invokes. | Plan |

## Scope

**In scope:**
- stdlib `logging` setup in `_util.py` + per-module loggers
- Route `_warn()` through the logger; add `Config.log_level` (`LOG_LEVEL` env)
- INFO breadcrumbs (metadata only) across cli/diff/context/plan/graph/nodes
- Markdown preview via `typer.echo(render_comment(...), err=True)`
- New `tests/test_logging.py`; extended `tests/test_cli.py`
- `.env.example` + README/integration notes

**Out of scope:**
- Any business-logic / control-flow / exit-code / posting change
- stdout contract change (stays JSON)
- Inline review annotations / the real S-02 posting-format gap (separate change)
- Structured/JSON logs, correlation ids, log shipping, input-body logging

## Architecture / Approach

stdlib `logging`, one logger per module, configured once inside `review()` (runtime,
so the handler binds to the `CliRunner`-redirected stderr; idempotent so repeated
invokes don't duplicate handlers). Format `"%(levelname)s: %(message)s"` — first
token is the level name so routed `_warn` output still reads `WARNING: <msg>`
(`test_cli.py:138` stays green). Breadcrumbs report sizes/counts/refs/change-ids
only. The preview is a single `typer.echo(..., err=True)` of `render_comment()`
right after `run_review` returns, before the untouched post-vs-stdout branch.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Logging foundation | `configure_logging`/`get_logger`, `_warn` routed, `LOG_LEVEL` knob | Duplicate handlers across test invokes (mitigated by idempotency guard) |
| 2. Breadcrumbs + preview | INFO at every step + Markdown preview on stderr | Polluting stdout JSON (mitigated: preview is stderr-only; verified CliRunner stream semantics) |
| 3. Docs | `.env.example` + GHA/README visibility notes | None |
| 4. Real-pipeline validation | Live smoke test + consumer GHA run confirming the trace + preview land in the step log | Live-run flakiness / cost (mitigated: smoke is `SMOKE=1`-gated) |

**Prerequisites:** none beyond the shipped S-01/F-01/F-02 pipeline.
**Estimated effort:** ~2 sessions; small, additive, 4 phases (Phase 4 needs a live OpenRouter + consumer-PR run).

## Open Risks & Assumptions

- **Assumption:** no consumer currently relies on stderr being empty on success
  (GHA captures it; the trace is the intended outcome). None known.
- **Verified fact, not risk:** typer's `CliRunner` exposes pure-stdout via
  `result.stdout` and mixed-via `result.output` (`mix_stderr` removed) — so
  `json.loads(result.stdout)` survives the stderr preview/logs unchanged.
- **Assumption:** the consumer GHA workflow does not redirect stderr away from
  the step log. The shipped template (`integration/github-actions-review.yml:73`)
  does not; a custom consumer that does would hide the trace (out of our hands).

## Success Criteria (Summary)

- Every pipeline step emits a metadata-only INFO line on stderr (visible in the
  default GHA step log, no workflow edit).
- The final Markdown report appears on stderr just before exit, identical to what
  is (or would be) posted to the PR.
- stdout remains the unchanged JSON report; exit codes and posting behavior
  identical to today; `make check` and `make test` green.
