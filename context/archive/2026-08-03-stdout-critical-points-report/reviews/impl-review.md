<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: S-01 — Stdout Critical-Points Report (North Star)

- **Plan**: context/changes/stdout-critical-points-report/plan.md
- **Scope**: Full plan (Phases 1–4 of 4)
- **Date**: 2026-08-03
- **Verdict**: NEEDS ATTENTION
- **Findings**: 1 critical · 1 observation · 1 observation-pattern

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | FAIL |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

> One CRITICAL drives Safety & Quality to FAIL. It is narrowly scoped (one
> read site, an obvious fix) but it breaks a locked fail-safe, so it must be
> decided. Everything else the plan asked for is present and faithful.

## Notes from the review

- **Plan-drift sweep: clean.** Every load-bearing requirement across all four
  phases is present and semantically faithful (see "Plan-drift evidence"
  below). No MISSING, no DRIFT, one benign EXTRA (two redundant single-name
  sanity assertions in the diff-scoping smoke, supplementary to the required
  set-difference gate).
- **Automated success criteria: green.** `make check` (ruff + mypy, 17 files)
  clean; `make test` (`-m "not smoke"`) = **110 passed, 13 deselected** — the
  13 are the new opt-in smokes, correctly gated behind `pytest.mark.smoke`.
  New unit modules contributing: `test_nodes.py` (6), `test_plan_loader.py`
  (12).
- **Pre-existing code excluded.** Two sub-agent flags (`cli.py` runtime assert
  under `-O`; `_extract_findings` branch coverage; `base_ref` reaching
  `git diff`) sit in files this change didn't author or modify — they're out
  of scope for an impl review of S-01 and were dropped from the findings.

## Findings

### F1 — Unguarded `read_text` escapes the degrade convention (non-UTF-8 / oversized plan crashes the pipeline)

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/plan_loader.py:70
- **Detail**: `plan_path.read_text(encoding="utf-8")` is wrapped only in
  `except FileNotFoundError` + `except OSError`. Two failure modes that are
  **not** `OSError` subclasses (verified: `issubclass(UnicodeDecodeError,
  OSError)` is `False`; `issubclass(MemoryError, OSError)` is `False`) escape
  and propagate out of `load_plan`, crashing the graph:
  - **`UnicodeDecodeError`** (a `ValueError`) on any non-UTF-8 `plan.md` — a
    Windows-1252 doc, a binary blob, or a truncated UTF-8 sequence.
  - **`MemoryError`** on a multi-GB / hostile `plan.md`: `read_text()` loads
    the whole file into RAM *before* `_cap()` truncates it, so `MAX_PLAN_CHARS`
    bounds the returned string but not peak memory.
  Both break the locked fail-safe (AGENTS.md §d: "Never crash the pipeline")
  and the module's own contract ("never raise"). The sibling `context_loader`
  has the same latent shape, but `plan_loader` concentrates a single unbounded
  read on one diff-discovered path, so it is the higher-priority fix. The
  cap unit test (`test_oversize_plan_is_truncated_with_marker`) uses a ~17 KB
  file and does not exercise either escape.
- **Fix**: Read at most `MAX_PLAN_CHARS + slack` bytes before decoding, and
  broaden the exception to `(OSError, ValueError)`.
  - Strength: Removes both the OOM and the decode-crash classes; restores the
    degrade-on-failure contract the module promises. The byte-bound keeps
    peak memory O(cap) regardless of file size.
  - Tradeoff: A few-line edit + one or two unit tests (non-UTF-8 file → None
    + WARNING; oversize file still caps correctly). Touches one production
    site and its tests only.
  - Confidence: HIGH — `read_bytes()` with a length limit + a `decode(…,
    errors="replace")` (or a size pre-check via `stat().st_size` degrading to
    None) is the standard bounded-read idiom; the tmp-tree fixture idiom in
    `test_plan_loader.py` already supports dropping a non-UTF-8 / oversize
    file.
  - Blind spot: If a binary plan *should* surface as a distinct WARNING vs.
    a plain "skipped", the message wording is a small product call — the
    reviewer can decide at fix time.
- **Decision**: FIXED via Fix. Applied the bounded-read + lenient-decode edit
  at `plan_loader.py:68-90` (open `"rb"`, `read(MAX_PLAN_CHARS + 200)`,
  `decode("utf-8", errors="replace")`). Added two unit tests
  (`test_non_utf8_plan_does_not_raise`, `test_oversize_binary_plan_does_not_oom`)
  covering both escape classes. `make check` clean; `make test` 112 passed
  (was 110; +2). Note: a non-UTF-8 plan now loads with replacement chars rather
  than degrading to None — lenient decode is the cleaner behavior (returns the
  readable prefix instead of dropping the whole plan), so the original "None +
  WARNING" framing in the finding was corrected at fix time.

### F2 — `_FIXTURE_DIFF` is dead code (zero references; plan's "stays for system tests" justification does not hold)

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/cli.py:97
- **Detail**: The plan (§2.2) said "`_FIXTURE_DIFF` stays (system tests)", but
  a repo-wide grep finds **no references** beyond its own definition — not in
  the CLI, not in tests, not in system tests. The inline comment ("Kept inline
  so the CLI is self-contained for the Phase-3 smoke; F-02 replaces this") is
  now stale (F-02 has landed; the real diff is computed at cli.py:48 and fed
  to `load_plan`). This is the one genuine leftover from the prior slice.
- **Fix**: Delete `_FIXTURE_DIFF` and its comment.
- **Decision**: FIXED via Fix. Deleted the constant + its stale comment block
  at `cli.py`. `make check` clean; `make test` 112 passed.

### F3 — Path-traversal guard relies on an unannotated regex char class + pathlib normalization

- **Severity**: OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: reviewer-target-o-meter/src/reviewer_target_o_meter/plan_loader.py:46-49
- **Detail**: `change_id` is captured by `(?P<id>[^/]+)`, which blocks `/` so
  `../etc/passwd`-style multi-segment traversal can't fit in one capture.
  `Path(root / "context" / "changes" / ".." / "plan.md")` also normalizes `..`
  away rather than escaping, so *today* there is no working exploit through
  either branch. The catch: this safety depends on two implicit invariants
  (the regex's `[^/]` char class and pathlib's normalization) that are
  **unannotated** — a future loosening to `.*` (or a different join idiom)
  would silently open a path-traversal on a diff-discovered, attacker-shaped
  path. This is defense-in-depth, not a present defect.
- **Fix**: Add an explicit reject on `change_id` — `re.fullmatch(
  r"[A-Za-z0-9._-]+", change_id)` or a `change_id in {".", ".."}` guard — with
  WARNING + None on rejection, and a one-line comment that the regex char
  class is the traversal guard.
  - Strength: Removes the dependence on regex/pathlib internals; a future edit
    can't silently widen the accepted charset.
  - Tradeoff: ~2 lines + one unit test (a diff with `id=..` → None). Low cost.
  - Confidence: HIGH — the `sess_*` / change-id charset is already `[A-Za-z0-9._-]`
    across the 10x convention.
  - Blind spot: None significant — the guard is additive; existing tests pass.
- **Decision**: FIXED via Fix. Added `_validate_change_id` as a single chokepoint
  in `_discover_change_id` (covers both diff-driven and single-active branches),
  annotated the regex char class as the traversal guard, and — critically —
  added an explicit `change_id in {".", ".."}` reject. At fix time I found the
  charset alone was *insufficient*: `.` and `..` both match `[A-Za-z0-9._-]+`,
  and `Path(root/"context"/"changes"/".."/"plan.md")` normalizes up to
  `root/context/plan.md` — so the explicit `.`/`..` reject is load-bearing, not
  redundant. Added two unit tests (`test_path_traversal_change_id_is_rejected`,
  `test_shell_metachar_change_id_is_rejected`). `make check` clean; `make test`
  114 passed.

## Plan-drift evidence (all MATCH — recorded for the audit trail)

**Phase 1 — `agent/nodes.py` `_SYSTEM_PROMPT`**: six sections in load-bearing
order (Role L45 → Hard rules L52 → Three lenses L90 → Emit mapping L116 →
Severity/impact/verdict L125 → Grammar+caps L132); diff-scoping present as
BOTH the anchor rule (L63, L75) AND the active-investigation protocol
(L61–70, with the passive "confirm a concern" phrase deliberately removed);
plan-tolerance conditional (L94/L97/L113); no-execution rule (L50/L82);
`{MAX_FINDINGS_PER_DIMENSION}` spliced via module-level f-string (L137,
constant at L34). `tests/test_nodes.py` asserts all six invariants offline.

**Phase 2 — `plan_loader.py`**: `load_plan(repo_path, diff) -> str|None` (L52);
discovery chain diff-driven → single-active → None (L86–100); `MAX_PLAN_CHARS
= 12_000` (L36) with visible truncation marker (L38, applied L120–125);
`context/archive/` excluded (L108–117); WARNING+None degrade on every failure
path (L60/71/76); plain library call with `__all__`. `cli.py` wires
`load_plan(repo_path, diff)` with the diff computed **once** and reused
(L48/L53), old `"plan": None` replaced, import + comment updated.
`test_plan_loader.py` covers all eight contract cases (a–h) plus extras.

**Phase 3 — `test_smoke_signal.py`**: `pytestmark = pytest.mark.smoke`;
three targeted smokes each asserting BOTH the specific keyword blob AND the
expected `dimension`; negative control asserts `exit_code == 0` + tolerates
≤2 OBSERVATION; diff-scoping guard uses the required **set-difference** form
(`bad = {f.file} - (changed | planned_missing)`, L409–411). The two
supplementary single-name asserts (L415–417, labeled "Sanity") are a benign
EXTRA.

**Phase 4 — `AGENTS.md`**: `## (h)` section records methodology provenance
(OQ#7) — source `/10x-impl-review-ci`, three adaptations (plan-tolerance /
no-command-execution / diff-scoping), soft lens→dimension mapping,
narrative-only verdict + host-side dimension grid, pointing at
`_SYSTEM_PROMPT` as the single source of truth.
