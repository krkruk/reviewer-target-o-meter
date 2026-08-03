---
change_id: ast-grep-fix
title: Deprecate the `sg` call in favor of `ast-grep`
status: archived
created: 2026-08-03
updated: 2026-08-03
archived_at: 2026-08-03T20:56:20Z
---

## Notes

Deprecate `sg` call in favor of `ast-grep`.

The `sg` binary is deprecated as of ast-grep 0.45.0 — invoking it prints a
deprecation banner advising `ast-grep` instead. `ast-grep` is a verified
drop-in: same `run --json=compact -p` interface, identical JSON output
(verified locally on v0.45.0). This change switches every `sg` reference in
the repo to `ast-grep`, with no `sg` fallback (clean break — the canonical
name going forward).
