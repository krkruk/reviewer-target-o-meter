# Lessons Learned

> Append-only register of recurring rules and patterns. Re-read at start by /10x-frame, /10x-research, /10x-plan, /10x-plan-review, /10x-implement, /10x-impl-review.

## Surface tool inputs, cap tool calls, tune reasoning, retry the structured emit

- **Context**: Any phase that integrates external tools (ripgrep/ast-grep/HTTP) into a LangGraph `create_agent` loop, or that tunes an agentic node's cost/latency knobs.
- **Problem**: In fine-tune-context, the agent emitted 0 findings on a large PR across 12 runs because (a) the checkout path was never surfaced to the model so every tool call hit the wrong CWD and returned empty, (b) the agent never self-limited its tool investigation and burned every model call on tool batches, and (c) the reasoning model intermittently emitted empty JSON on the structured-output turn. Each failure mode is silent — the pipeline degrades to an empty report with exit 0, not a crash.
- **Rule**: When wiring tools into an agentic node, always (a) surface every path/identifier the tools need as an explicit field in the prompt, (b) cap tool calls separately from model calls (`ToolCallLimitMiddleware`, `continue`) so the agent is forced to converge and emit, (c) set reasoning effort deliberately (medium for structured emit — low flakes, high over-investigates), and (d) retry the structured emit on empty/parse-failure rather than degrading to empty on the first flaky response.
- **Applies to**: plan, implement, impl-review
