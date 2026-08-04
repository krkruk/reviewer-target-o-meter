---
change_id: fine-tune-reviewer-system-prompts
title: Fine-tune reviewer system prompt for higher recall (more findings, tolerate false positives)
status: archived
created: 2026-08-04
updated: 2026-08-04
archived_at: 2026-08-04T18:36:45Z
---

## Notes

Validation run vs a planted-defect mock change (`rate_limiter.py` + cli wiring)
caught 4 of 6 defects — all CRITICAL/WARNING-tier ones (hardcoded secret,
off-by-one, untested branches, duplicated degrade logic), with accurate causal
detail and sound severity calibration. Two defects slipped: a bare
`except Exception` in `stats()` (swallowed-error maintainability smell) and an
unbounded module-level `_posts` dict (design/perf growth in a long-running
process). Both are subtler, lower-stakes, but a thorough review should at least
flag the swallowed exception.

The operator's directive: ease scrutiny toward HIGHER RECALL — tolerate more
false positives to catch the subtler smells. The current prompt's "Report only
substantive issues" + per-dimension cap may be suppressing these. This change
tunes `_SYSTEM_PROMPT` (and any anchoring) to raise recall on the
safety/maintainability/design lenses without inflating severity or anchoring
on untouched files (diff-scoping stays hard).
