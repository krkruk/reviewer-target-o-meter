---
change_id: prod-logging-markdown-preview
title: PROD INFO logging and Markdown preview before exit
status: archived
created: 2026-08-04
updated: 2026-08-04
archived_at: 2026-08-04T12:31:58Z
---

## Notes

Add INFO logging that tracks every pipeline step in PROD (visible in the default
GHA workflow), and echo the final `render_comment()` Markdown to stderr just
before the CLI exits — so the reviewer sees exactly what is (or would be) posted
to the PR. Logging only; no business-logic change. Split out of the mis-named
`github-review-posting` stub, whose plain-comment posting code already ships.
