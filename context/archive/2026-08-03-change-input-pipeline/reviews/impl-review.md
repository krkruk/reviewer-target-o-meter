<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Change Input Pipeline Implementation Plan

- **Plan**: context/changes/change-input-pipeline/plan.md
- **Scope**: Phase 1–6 of 6 (full plan)
- **Date**: 2026-08-03
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 3 warnings, 8 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

## Findings

### F1 — PR-comment source links point at default branch, not the reviewed PR

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/github.py:134
- **Detail**: `_file_cell` renders links as `https://github.com/{repo}/blob/HEAD/{file}#L{line}`. On github.com `/blob/HEAD/` dereferences the repo's *default-branch* pointer — NOT the PR merge commit that was actually reviewed. For the common case (a finding anchored on a line *added* by the PR), the link resolves to a version of the file where the line may not exist or has shifted, producing a wrong-line or 404 link. Plan §4.2 explicitly allowed "pass `None` to skip the link in v1 if a SHA isn't easily available — keep the plain backtick path"; `blob/HEAD` is a worse default than the plain backtick the plan suggested.
- **Fix A ⭐ Recommended**: Drop the link, emit the plain backtick cell the plan specified (`\`{file}:{line}\``)
  - Strength: Matches the plan's stated v1 contract exactly; removes the wrong-branch footgun; zero new inputs needed.
  - Tradeoff: Loses click-through convenience until SHA threading lands.
  - Confidence: HIGH — plan §4.2 names this exact fallback.
  - Blind spot: None significant.
- **Fix B**: Thread the reviewed commit SHA through `render_comment` and use `blob/{sha}/`
  - Strength: Keeps click-through and points at the exact reviewed version.
  - Tradeoff: Requires plumbing `HEAD` (or `github.event.pull_request.head.sha`) from the workflow → CLI → `render_comment`; larger edit surface across Phase 4/5/6.
  - Confidence: MED — the SHA is available in GHA but the CLI doesn't currently capture it.
  - Blind spot: Haven't verified the local-run path has a meaningful SHA to offer.
- **Decision**: FIXED via Fix A — `_file_cell` now emits the plain backtick `` `{file}:{line}` `` regardless of `repo`; the `blob/HEAD` link path removed. `tests/test_github.py` updated (the "links when repo known" test became "uses backticks even when repo known"). `make check` + `test_github.py` green.

### F2 — Workflow `continue-on-error: true` masks the missing-key fast-fail the plan requires

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Safety & Quality
- **Location**: integration/github-actions-review.yml:63
- **Detail**: The `Run reviewer-target-o-meter` step carries `continue-on-error: true` so the advisory exit 1 (flagged findings) doesn't fail CI. But that flag is broader than the advisory case: it also swallows the ONE failure the plan says *should* fail the step — `OPENROUTER_API_KEY` missing, which `Config.from_env` raises on *before any work* (`config.py:60-63`). The plan's own Progress note 6.5 and `integration/README.md:25-27` flag exactly this masking as an operator footgun ("the operator must confirm the secret is set on first setup"). The plan's stated intent ("missing key fails fast and SHOULD fail this step") is contradicted by the single flag.
- **Fix A ⭐ Recommended**: Drop `continue-on-error`, map the advisory exit explicitly: `reviewer-target-o-meter …; code=$?; test $code -le 1`
  - Strength: Advisory 0/1 pass; the missing-key `ValueError` (typer non-zero, ≥2) or any real crash fails the step — exactly the plan's intent, no masking.
  - Tradeoff: Shell exit-code mapping is a tiny bit cleverer than a one-word flag; needs the one-line `test` guard.
  - Confidence: HIGH — the tool's exit codes are advisory 0/1 vs. the `ValueError`/crash path.
  - Blind spot: Haven't confirmed typer's exit code on the `ValueError` is ≥2 on all platforms (it is on CPython/posix).
- **Fix B**: Split into two steps — a `if: failure()` guard that re-succeeds only on advisory exits
  - Strength: More explicit intent in YAML.
  - Tradeoff: More YAML; two steps where one suffices.
  - Confidence: LOW — GHA step-status plumbing is fiddly.
  - Blind spot: Haven't prototyped the `if:` expression.
- **Decision**: ACCEPTED — user decided the missing-`OPENROUTER_API_KEY` masking is acceptable for this process ("not really a critical process; I can afford not handling the missing env var"). `continue-on-error: true` stays.

### F3 — Broad `except Exception` forwards `str(exc)` to stderr (token-leak fragility)

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/cli.py:64-67
- **Detail**: The post-failure degrade path does `_warn(f"posting failed; falling back to stdout ({exc})")`. `httpx.HTTPStatusError`/`ConnectError` don't put the `Authorization` header value in their default `str()`, so today the token isn't leaked. But this is a broad `except Exception` forwarding the message verbatim, against AGENTS.md §d's "key read at runtime only, never echoed." Relying on every transport exception type to omit the header is fragile.
- **Fix**: Log only the exception *type* + status code (e.g. `f"posting failed ({type(exc).__name__})"`) in the degrade warning, not the full `str(exc)`.
- **Decision**: FIXED — `_warn(f"posting failed; falling back to stdout ({type(exc).__name__})")`. `make check` + `test_cli.py` green (test asserts `"WARNING"` OR `"posting failed"`, still satisfied).

### F4 — `_FIXTURE_DIFF` is now dead code with a stale comment

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/cli.py:89-101
- **Detail**: Plan §1.2 said system tests reach `_FIXTURE_DIFF` by monkeypatching `compute_diff`. No test does; `test_cli.py` mocks `run_review` upstream. The constant is unreferenced dead weight on all paths, with a stale "Phase-3 smoke" comment.
- **Fix**: Either delete `_FIXTURE_DIFF` or add the monkeypatch test the plan promised.
- **Decision**: ACCEPTED — user declined to action; left as-is for a future slice.

### F5 — `_warn` duplicated across four modules

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/context_loader.py:95-97 (also diff.py:118-120, cli.py:84-86, config.py:110)
- **Detail**: Four copies of the same one-liner `_warn`. Low divergence risk (it's one line) but the degrade-to-stderr convention is cross-phase per the plan; a shared helper would pin it.
- **Fix**: Extract a shared `_warn` into a small `_util.py` (or findings.py-adjacent) in a future slice; not blocking.
- **Decision**: FIXED — extracted `warn` into a new `src/reviewer_target_o_meter/_util.py`; the three module-local `_warn` defs (cli/diff/context_loader) replaced with `from ._util import warn as _warn`, config.py's inline `print(..., file=sys.stderr)` swapped for `warn(...)`, now-unused `import sys` dropped from diff/context_loader/config. `make check` clean (16 files, +1 for `_util`); 92 tests pass.

### F6 — Diff cap is "soft" (can exceed budget by one file hunk)

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/diff.py:107-115
- **Detail**: `_cap` cuts at the next `\ndiff --git` boundary *after* `MAX_DIFF_CHARS`. When one large file hunk spans the boundary, the emitted diff can exceed the budget by up to one file's diff. Plan §"Critical Implementation Details" explicitly specifies "cut at the next boundary," so this is intended; the test (`test_oversize_diff_is_truncated_with_marker`) only covers the no-boundary single-file case.
- **Fix**: Accept as-documented, OR add a hard upper bound and a test for the far-boundary case.
- **Decision**: ACCEPTED — user reviewed in bulk; the deviation is plan-documented or a defensible refinement, not a happy-path defect. No action.

### F7 — `github_api_url` is configurable with no scheme/host validation (SSRF surface)

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/config.py:75
- **Detail**: `github_api_url` is env-configurable with no allow-list. The token is sent as `Bearer` to whatever host it points at. In the GHA template `GITHUB_API_URL` is auto-provided (not mapped from operator input), so the attack surface is local `.env` only — and anyone editing `.env` already has the token. Risk is low; noting for completeness.
- **Fix**: Optional — validate `https://` scheme and reject RFC1918/link-local hosts before the POST; only worth it if `.env` is ever treated as lower-trust.
- **Decision**: ACCEPTED — user reviewed in bulk; the deviation is plan-documented or a defensible refinement, not a happy-path defect. No action.

### F8 — Smoke test relaxes the `diff --git` assertion to tolerate an empty diff

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: reviewer-target-o-meter/tests/test_smoke_consumer.py:64-70
- **Detail**: Plan §6.4 contract said "compute_diff returns a non-empty diff containing `diff --git`." The implementation only asserts `compute_diff` returns a `str`, then *conditionally* checks `diff --git` if non-empty — tolerating an empty diff when the consumer's HEAD equals its base (e.g. master). Defensible (the consumer checkout at master genuinely has no diff); documented in the test docstring; minor relaxation of the written contract.
- **Fix**: Accept as-documented, or point the smoke at a branch that actually diverges.
- **Decision**: ACCEPTED — user reviewed in bulk; the deviation is plan-documented or a defensible refinement, not a happy-path defect. No action.

### F9 — `render_comment` header is H1 (`#`) where plan wording said "H1 `## …`"

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/github.py:44
- **Detail**: The plan's §4.2 wording was self-contradictory ("H1 `## reviewer-target-o-meter`"). The implementation chose the true-H1 reading (`# reviewer-target-o-meter`), pinned by smoke test `test_smoke_input_pipeline.py:340`. Benign ambiguity resolution.
- **Fix**: None — pick whichever the team prefers; document the choice in the plan if H1 stands.
- **Decision**: ACCEPTED — user reviewed in bulk; the deviation is plan-documented or a defensible refinement, not a happy-path defect. No action.

### F10 — `post_comment` adds an `_client` test seam not in the plan contract

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/github.py:102
- **Detail**: Plan §4.3 specified `httpx.post(...)`; implementation uses `with httpx.Client()` plus a `_client: httpx.Client | None = None` test seam (underscore-prefixed, docstring-labeled test-only). Functionally equivalent for the contract; matches the codebase's DI-seam convention (`build_checks_node(..., agent=None)`). Benign testability refactor.
- **Fix**: None — acceptable deviation; noting for plan/code alignment.
- **Decision**: ACCEPTED — user reviewed in bulk; the deviation is plan-documented or a defensible refinement, not a happy-path defect. No action.

### F11 — `GITHUB_BASE_REF` non-local-ref fall-through is a post-plan refinement

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/diff.py:89-91
- **Detail**: Plan §1.1's `_resolve_base` chain reads `GITHUB_BASE_REF` then heuristics. Implementation additionally tries `origin/<base>` when the bare `GITHUB_BASE_REF` name isn't a local ref (GHA detached checkouts leave only `origin/<base>` resolvable). Priority ordering preserved; refinement documented in Progress 6.4 + commit 9a8077b; it's the fix for a real consumer-PR bug. The plan's `_resolve_base` pseudocode didn't include this step.
- **Fix**: Backfill the plan's §1.1 pseudocode with the `origin/<base>` fall-through so the source of truth matches the code.
- **Decision**: ACCEPTED — user declined to backfill the plan pseudocode; the refinement stays documented in Progress 6.4 + commit 9a8077b.
