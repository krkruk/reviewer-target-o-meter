---
change_id: fine-tune-context
title: Make the reviewer finish on large PRs
status: archived
created: 2026-08-04
updated: 2026-08-05
archived_at: 2026-08-05T11:56:06Z
---

## Notes

Started as "fine-tune context directory dismissal" but /10x-frame split it into
two independent problems. This plan addresses Problem A: the reviewer emits 0
findings on large PRs because the checks node times out (diff-driven, not
context-driven — see frame.md). Approach is diagnose-first: instrument heavily,
measure against krkruk/target-o-meter#28, identify the real bottleneck, fix it,
then remove the instrumentation. Problem B (change-aware load_context — a
relevance problem, not a latency one) is deferred to a follow-up change.
