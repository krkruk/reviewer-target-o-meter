---
change_id: stdout-critical-points-report
title: Structured JSON critical-points report to stdout (north star)
status: plan_reviewed
created: 2026-08-03
updated: 2026-08-03
archived_at: null
---

## Notes

Slice S-01 from context/foundation/roadmap.md — the north star. Runs the agent on a checked-out change and emits a structured JSON critical-points report to standard output (FR-007 default mode), with file/line anchors and an advisory exit code. Proves the core product hypothesis (that an automated "critical points in this PR" signal is fillable) with no GitHub posting auth and no posting-format decision required.

Prerequisites F-01 (findings schema/provider/agent harness) and F-02 (diff/context/plan discovery) have landed. This slice consumes the prepared diff + context and carries the analysis methodology + output surface.
