---
project: reviewer-target-o-meter
version: 1
status: draft                    # draft | active | locked
created: 2026-08-01
updated: 2026-08-03
prd_version: 1
main_goal: speed                 # ship the must-have path to the 2026-08-29 deadline; park the rest
top_blocker: capacity            # solo + after-hours + 4 weeks + 11 must-have FRs + unfamiliar agent stack
---

# Roadmap: reviewer-target-o-meter

> Derived from `context/foundation/prd.md` (v1) + auto-researched codebase baseline (2026-08-01).
> Edit-in-place; archive when superseded.
> Slices below are listed in dependency order. The "At a glance" table is the index.

## Vision recap

A developer assigned to review pull requests must judge — under time pressure, often on unfamiliar code — which parts of a diff are genuinely risky. Today humans are the only assessor, so risk gets re-derived from scratch on every PR; on large diffs that is decision paralysis plus a missing capability (no machine signal at all). reviewer-target-o-meter turns the recently-viable capability of agentic LLM code review into a focused critical-point map the reviewer acts on — not another noisy style linter. The distinguishing trait, the one thing that makes this more than a generic AI tool, is that findings are produced by an agent that loads the repo's own context (its AGENTS.md, skills, source) and characterizes each risk by severity and file/line location.

## North star

**S-01: Run the tool on a checked-out change and get a structured JSON critical-points report to standard output** — the default mode (FR-007) that proves the core product hypothesis (that an automated "critical points in this PR" signal is finally fillable) with no GitHub posting auth and no posting-format decision required.

> What "north star" means here: the smallest end-to-end slice whose successful delivery would prove the core product hypothesis — placed as early as Prerequisites allow because everything else only matters if this works. It is the project's validation milestone — the first moment a real reviewer could read the output and decide whether the signal is worth acting on.

## At a glance

| ID | Change ID | Outcome (user can …) | Prerequisites | PRD refs | Status |
|---|---|---|---|---|---|
| F-01 | agent-runtime-finding-schema | (foundation) reviewer agent runtime, typed Finding/Severity schema, and OpenRouter provider wiring in place | — | FR-006, FR-009, FR-011 (scaffold) | done |
| F-02 | change-input-pipeline | (foundation) the tool accepts a checked-out directory, discovers the target branch, computes a capped diff, and loads repo context | — | FR-002, FR-004, FR-005 (scaffold) | done |
| S-01 | stdout-critical-points-report | run the tool on a checked-out change and get a structured JSON critical-points report to stdout, with file/line anchors and an advisory exit code | F-01, F-02 | US-01, FR-001, FR-002, FR-004, FR-005, FR-006, FR-007, FR-008, FR-009, FR-010, FR-011 | proposed |
| S-02 | github-review-posting | open a PR and see the findings posted automatically as a GitHub Review with inline, jump-to-location annotations (advisory exit) | S-01 | US-01, FR-001, FR-003, FR-007, FR-008, FR-009 | blocked |

## Baseline

What's already in place in the codebase as of `2026-08-01` (auto-researched + user-confirmed).
Foundations below assume these are present and do NOT re-scaffold them.

- **Frontend:** N/A — CLI product (`product_type: cli`); the console command + output formats are the only interface.
- **Backend / API:** partial — `uv init --package` skeleton: `pyproject.toml` + `src/reviewer_target_o_meter/__init__.py` with a `main()` console script wired, but `main()` is a "Hello" stub; no CLI parsing, no agent graph, no analysis logic. Stack chosen per `tech-stack.md` (Python/uv, LangChain + LangGraph, typer, pydantic) — none installed (`dependencies = []`).
- **Data:** absent — no diff computation, no context loading, no Finding schema yet. Per `tech-stack.md`: gitpython (diff) + pydantic (Finding/Severity) chosen but not implemented. No persistence (the tool reads the local checkout).
- **Auth:** absent (not a user-auth product; `has_auth: false`) — the only credential path is the CI `GITHUB_TOKEN` used solely to post findings (FR-003); no code yet.
- **Deploy / infra:** absent — repo is git-initialized but no GitHub Actions workflow in the repo (`tech-stack.md` documents a *proposed* recipe only), no Dockerfile, no CI config.
- **Observability:** absent — no logging library, no error tracking, no metrics.

## Foundations

### F-01: Agent runtime + typed Finding/Severity schema + provider wiring

- **Outcome:** (foundation) a LangGraph reviewer-agent runtime is scaffolded (one node per FR-006 phase: context-load → plan discovery → drift/safety/pattern checks → report), a typed Pydantic `Finding`/`Severity` schema exists (each finding carries severity + file/line anchor + rationale), and the OpenRouter provider is wired (`ChatOpenAI` with `base_url=https://openrouter.ai/api/v1`).
- **Change ID:** agent-runtime-finding-schema
- **PRD refs:** FR-006 (analysis phases the graph implements), FR-009 (anchor field in schema), FR-011 (hardcoded severity-to-signal mapping encoded in schema). Also carries `tech-stack.md` "Compensation owed": pinned langchain/langgraph versions, explicit graph convention, severity taxonomy + line-anchor rules as Pydantic schemas.
- **Unlocks:** S-01 (the north star — the agent runs analysis and emits typed findings); reduces Open Roadmap Question "Severity taxonomy" (the schema forces a decision on severity levels); enables verification (agent output is machine-validatable, not free-form).
- **Prerequisites:** —
- **Parallel with:** F-02 (independent — agent/output vs. input pipeline; separate agent runs can build both concurrently).
- **Blockers:** —
- **Unknowns:**
  - Severity levels for the hardcoded mapping are not yet defined (PRD OQ "Severity taxonomy") — Owner: user. Block: no (planning adopts a working default, e.g. critical/warning/info, and the user confirms).
- **Risk:** Sequenced first because the agent layer is the highest-risk, most unfamiliar part (`quality_override: true` — LangChain docs churn, agent-judgment not yet built). Landing the scaffold + typed schema early de-risks the whole roadmap and forces the severity-taxonomy decision while it is still cheap to change.
- **Status:** done

### F-02: Change input pipeline (directory → capped diff + loaded context)

- **Outcome:** (foundation) the tool accepts a checked-out project directory as its sole input (typer CLI entrypoint), discovers the target branch to diff against, computes a capped/segmented diff from local git history, and loads the repo's review context (AGENTS.md, skills, source) — emitting a prepared (diff, context) the analysis consumes. No findings are produced yet.
- **Change ID:** change-input-pipeline
- **PRD refs:** FR-002 (directory as sole input), FR-004 (load AGENTS.md/skills/source), FR-005 (capped diff from local history).
- **Unlocks:** S-01 and S-02 (both consume the prepared diff + context); reduces Open Roadmap Questions "Diff cap policy" and "Target-branch / diff-base discovery" (the pipeline is where these decisions land).
- **Prerequisites:** —
- **Parallel with:** F-01 (independent — input pipeline vs. agent/output; separate agent runs can build both concurrently).
- **Blockers:** —
- **Unknowns:**
  - Diff cap size and segmentation strategy (per-file? by hunk? by changed-lines budget?) (PRD OQ "Diff cap policy") — Owner: user. Block: no (planning picks a strategy within the context budget).
  - How the target branch is determined with no PR number passed as input (CI env var? `git merge-base`? default-branch name?) (PRD OQ "Target-branch / diff-base discovery") — Owner: user. Block: no (planning picks a heuristic).
- **Risk:** Kept as a foundation (not folded into S-01) because it is consumed by both downstream slices and carries two load-bearing input-policy decisions; splitting it out keeps S-01 focused on analysis + output rather than cramming the entire workflow into one unplannable unit.
- **Status:** done

## Slices

### S-01: Stdout critical-points report (north star)

- **Outcome:** user can run `reviewer-target-o-meter <checked-out-dir>` locally and receive a structured JSON report of critical-point findings to standard output — each finding carrying a file/line anchor, severity, and rationale — with an advisory exit code; plan-tolerant (skips plan-dependent checks when no plan.md exists) and graceful (degrades to a diff-based review when repo context is absent).
- **Change ID:** stdout-critical-points-report
- **PRD refs:** US-01; FR-001 (local-CLI half of "CI step or local CLI, same code path"), FR-002, FR-004, FR-005, FR-006, FR-007 (stdout default), FR-008, FR-009 (anchors in the stdout report), FR-010, FR-011.
- **Prerequisites:** F-01, F-02.
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:**
  - The analysis follows an established implementation-review methodology (plan discovery, drift/safety/pattern checks); its specific provenance / any reuse of an existing review checklist is undecided (PRD OQ "Critical-point analysis methodology provenance") — Owner: user. Block: no (planning adopts the methodology shape already described in FR-006; provenance is a citation, not a blocker).
- **Risk:** This slice references most of the must-have FRs, which is justified because the PRD has exactly one user-visible workflow (US-01) — the review of a single change. The split from S-02 is by delivery mode (local stdout vs. in-PR posting), a genuine user-visible distinction, not a technical-layer split. The load-bearing risk is signal quality: if the agent's critical points are generic or low-signal, the whole product hypothesis fails, so this is sequenced immediately after its two foundations rather than after the host-integration work.
- **Status:** proposed

### S-02: GitHub Review posting (in-PR, inline annotations)

- **Outcome:** user can open/update a PR in CI and see the findings posted automatically as a GitHub Review with inline, jump-to-location annotations (when `--github` is set); the step returns an advisory exit code and never blocks a merge.
- **Change ID:** github-review-posting
- **PRD refs:** US-01 (posted branch); FR-001 (CI-step half of "CI step or local CLI"), FR-003 (authenticate to post only, via CI `GITHUB_TOKEN`), FR-007 (posted mode), FR-008 (advisory exit), FR-009 (anchors render as inline annotations).
- **Prerequisites:** S-01 (consumes the findings pipeline; transitively F-01 + F-02).
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:**
  - Posting format under `--github` is unresolved — plain pull-request comment vs. inline review with line-level annotations (PRD OQ "Posting format under the posting flag") — Owner: user. Block: yes (the format determines which GitHub API path is used and whether FR-009 anchors render as inline annotations; the slice cannot be planned until this is decided). Note: `tech-stack.md` provisionally assumed inline review (PyGithub/httpx for line-level review comments), but the PRD leaves this open.
  - Fail-safe behavior when the git host errors mid-run in posting mode (PRD OQ "Fail-safe on upstream errors") — Owner: user. Block: no (advisory exit code means the step likely should not fail CI; planning picks retry/skip/"review unavailable" comment).
- **Risk:** Blocked on the posting-format decision. Sequenced after S-01 because posting is meaningless without a trusted findings stream, and because resolving OQ#8 is cheaper once the stdout signal already exists to inspect. Carries the entire host-integration surface (CI workflow, token auth, posting API), so it is a substantial integration slice, not a polish item.
- **Status:** blocked

## Backlog Handoff

| Roadmap ID | Change ID | Suggested issue title | Ready for `/10x-plan` | Notes |
|---|---|---|---|---|
| F-01 | agent-runtime-finding-schema | Scaffold reviewer agent runtime + typed Finding/Severity schema + OpenRouter wiring | yes | Run `/10x-plan agent-runtime-finding-schema`. Highest de-risking move (unfamiliar stack). |
| F-02 | change-input-pipeline | Build change input pipeline: dir → target-branch → capped diff + context | yes | Run `/10x-plan change-input-pipeline`. Parallel to F-01. |
| S-01 | stdout-critical-points-report | Emit structured JSON critical-points report to stdout (north star) | no | After F-01 + F-02 land. Run `/10x-plan stdout-critical-points-report`. |
| S-02 | github-review-posting | Post findings as a GitHub Review with inline annotations | no | Blocked — resolve "Posting format" (OQ) first. |

## Open Roadmap Questions

1. **Fail-safe on upstream errors** — what happens when the analysis source is unavailable, or (in posting mode) the git host errors mid-run? Advisory exit (FR-008) suggests the step should likely not fail CI, but the exact behavior (retry / skip / partial report + exit 0 + warning; in posting mode, whether to post a "review unavailable" comment) is undecided. — Owner: user. Block: S-02 (posting mode); roadmap-wide for the guardrail.
2. **Per-review cost ceiling** — "bounded per-review cost" is a guardrail; the actual $-per-review cap and the enforcement mechanism (max tokens / max agent steps / max model calls) are unspecified. LangGraph's recursion/step limit is the natural enforcement point. — Owner: user. Block: F-01 (the limit is wired when the agent runtime is built).
3. **Severity taxonomy** — FR-011's hardcoded severity-to-signal mapping needs the severity levels themselves (e.g. critical / warning / info) and what maps to "flagged" defined. — Owner: user. Block: F-01 (the schema).
4. **Diff cap policy** — FR-005 caps/segments the diff to the context budget; cap size and segmentation strategy (per-file? by hunk? by changed-lines budget?) are open. — Owner: user. Block: F-02.
5. **Git hosting platform** — ~~v1 targets a single platform; the specific host is pinned downstream.~~ **Resolved:** GitHub (`tech-stack.md` — `secrets.GITHUB_TOKEN` is the agent identity, FR-003).
6. **External analysis source / model provider** — ~~the AI source is locked at the tech-stack-selection step.~~ **Resolved:** OpenRouter (`tech-stack.md` — driven via `langchain-openai` `ChatOpenAI` with `base_url=https://openrouter.ai/api/v1`).
7. **Critical-point analysis methodology provenance** — the analysis follows an established implementation-review methodology (plan discovery, drift/safety/pattern checks); its specific provenance and any reuse of an existing review checklist are deferred to planning. — Owner: user. Block: S-01.
8. **Posting format under the posting flag** — FR-007 makes posting opt-in, but the format is unresolved: plain pull-request comment, or an inline review with line-level annotations (which FR-009's anchors populate)? Reconciles the "inline review, not a comment dump" resolution with the "pull request comment" phrasing. — Owner: user. Block: S-02 (yes — gates the posting API path; resolve before planning S-02).
9. **Target-branch / diff-base discovery** — with no PR identifier passed as input (FR-002), how does the tool learn the target branch to diff against (CI runtime env var? `git merge-base` heuristic? explicit default-branch name?)? — Owner: user. Block: F-02.

## Parked

- **No merge blocking in v1** — Why parked: PRD §Non-Goals (load-bearing — from FR-008). Exit code is advisory; blocking is a future, opt-in behavior.
- **No own deterministic checks (linters/tests)** — Why parked: PRD §Non-Goals. That is the remote project's existing CI step; this tool does agentic risk assessment only.
- **No auto-fixing / patch generation** — Why parked: PRD §Non-Goals. The tool flags risks and locations; it does not write or apply fixes.
- **No separate web dashboard / UI** — Why parked: PRD §Non-Goals. Findings live only in the stdout report or, when posted, on the pull request.
- **No host-API discovery/loading** — Why parked: PRD §Non-Goals (load-bearing — from FR-002). The tool operates on the local checked-out directory.
- **No multi-host support in v1** — Why parked: PRD §Non-Goals. v1 targets GitHub; other hosts deferred.
- **No offline-first guarantee** — Why parked: PRD §Non-Goals. The tool inherently needs the analysis source (and, in posting mode, the git host).
- **Per-finding severity/confidence triage UI** — Why parked: PRD Secondary success criterion — candidate for v1.1; deferred under the speed goal.
- **Configurable severity-to-signal mapping** — Why parked: FR-011 resolution — hardcoded in v1; configurability deferred.
- **Token rotation / scope hardening** — Why parked: FR-003 Socrates resolution — stands for v1 (posting-only scope); rotation hardening is a future concern.

## Done

- **F-01: (foundation) reviewer agent runtime, typed Finding/Severity schema, and OpenRouter provider wiring in place** — Archived 2026-08-01 → `context/archive/2026-08-01-agent-runtime-finding-schema/`. Lesson: —.
- **F-02: (foundation) the tool accepts a checked-out project directory as its sole input, discovers the target branch to diff against, computes a capped/segmented diff from local git history, and loads the repo's review context (AGENTS.md, skills, source) — emitting a prepared (diff, context) the analysis consumes. No findings are produced yet.** — Archived 2026-08-03 → `context/archive/2026-08-03-change-input-pipeline/`. Lesson: —.
