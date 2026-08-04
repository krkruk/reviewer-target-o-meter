---
change_id: graph-bugfixing
title: Fix uncaught model-call TypeError crashing the checks node (misdiagnosed as recursion)
status: archived
created: 2026-08-04
updated: 2026-08-04
archived_at: 2026-08-04T16:33:27Z
---

## Notes

The branch is named `fix/graph-recursion-issue`, but the live stacktrace shows the
crash is **not** a `GraphRecursionError`: it is an uncaught
`TypeError: 'NoneType' object is not iterable` from the OpenAI SDK parser
(`openai/lib/_parsing/_completions.py:98`, `for choice in chat_completion.choices`)
when the model returns `choices: None`, escaping the `checks` node's bare
`await agent.ainvoke(...)` (`agent/nodes.py:211`). `graph.py:72` only catches
`GraphRecursionError`, so the `TypeError` crashes the pipeline — bypassing every
downstream fail-safe (`to_report`, `report`'s `except ValidationError`) and
violating the OQ#1 "never crash the pipeline" contract (AGENTS.md §d).

Reframe confirmed by direct investigation (signatures + source read under bash):
`ModelCallLimitMiddleware(run_limit=...)` signature is correct (not a silent-ignore
bug); the outer graph is a straight line (cannot itself recurse); no `astream`
anywhere. The two `[NOTE] During task with name 'model'/'checks'` lines in the
trace are LangGraph's **nested-task** annotations (inner `create_agent` running as
a task inside the outer `checks` node), not recursion.

Most likely upstream trigger (H-B): the `nvidia/nemotron-3-super-120b-a12b:free`
reasoning model exhausts `_MAX_TOKENS = 8192` before emitting JSON → `choices: None`
(research.md:316-318 explicitly warned reasoning tokens count against the budget).

Decision: fix the real cause; do **not** rename the branch. Robustness + root cause
(error boundary in `checks`, raise `max_tokens`, telemetry). Real-faithful unit test
via the existing DI seam (not the `_BoomGraph` outer-boundary fake).
