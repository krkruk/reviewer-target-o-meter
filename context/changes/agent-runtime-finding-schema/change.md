---
change_id: agent-runtime-finding-schema
title: Agent runtime + typed Finding/Severity schema + OpenRouter wiring
status: impl_reviewed
created: 2026-08-01
updated: 2026-08-01
archived_at: null
---

## Notes

Foundation slice **F-01** from `context/foundation/roadmap.md` (lines 51-63):
scaffold a LangGraph reviewer-agent runtime (one node per FR-006 phase), a typed
Pydantic `Finding`/`Severity` schema (severity + file/line anchor + rationale),
and the OpenRouter provider wiring. Resolves OQ#2 (cost ceiling mechanism),
OQ#3 (severity taxonomy), and advances OQ#7 (methodology provenance).

Research completed 2026-08-01 — see `research.md`. Key findings:
`deepseek/deepseek-v4-pro` is a **real, verified** OpenRouter slug; the LangChain
Agent module and the locked LangGraph decision **coexist** (Agent module = a
sub-agent inside the `checks` node); the impl-review-ci methodology maps 1:1 onto
FR-006 phases; severity taxonomy adopted as CRITICAL/WARNING/OBSERVATION.

Open decisions routed to `/10x-plan` are listed in `research.md` §"Open Questions".
