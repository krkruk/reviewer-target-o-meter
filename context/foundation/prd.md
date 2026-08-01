---
project: reviewer-target-o-meter
version: 1
status: draft
created: 2026-08-01
context_type: greenfield
product_type: cli
target_scale:
  users: small
  qps: low
  data_volume: small
timeline_budget:
  mvp_weeks: 4
  hard_deadline: 2026-08-29
  after_hours_only: true
---

# reviewer-target-o-meter — Product Requirements Document

## Vision & Problem Statement

A developer assigned to review pull requests must read diffs they didn't write and figure out — under time pressure — which parts are genuinely risky and deserve their attention. Today there is no automated quality signal: humans are the only assessor, so the reviewer re-derives risk from scratch on every PR. On a large or unfamiliar diff this is decision paralysis (what matters most?) plus a missing capability (no machine signal at all), and the cost is slow, inconsistent reviews where critical points can be missed.

The insight that makes this worth building now: automated, agent-driven code review has recently become accurate and cheap enough that an automated "critical points in this PR" signal is finally fillable at a price and quality point that didn't exist before. The product turns that capability into a focused risk map the reviewer acts on, rather than another noisy style linter.

*Scale note:* the domain rule (identify risks, characterize by severity/location) is unchanged at 100x scale — only the cost and infrastructure constraints would bite harder. The product surface does not need to be different for more users.

## User & Persona

**Primary persona — the PR reviewer.** A developer inside one org whose role includes reviewing teammates' pull requests. They open a PR they've been assigned to, often for code they're not deeply familiar with, and need to decide where to spend their limited review time. Their moment of pain is the instant they land on a large diff and have to judge what matters. The MVP serves this reviewer; the author of the PR is a secondary concern (they benefit indirectly from clearer, faster reviews).

Secondary persona (not MVP): the PR author, who would value a pre-review self-check. Out of scope for v1.

## Success Criteria

### Primary
- When a change is ready for review, reviewer-target-o-meter runs (as a CI step or local CLI) against the checked-out directory, loads the repo's context (its AGENTS.md, skills, and source) from that checkout, computes a capped diff against the target branch from local history, and runs a critical-point analysis (plan-tolerant: plan discovery, drift/safety/pattern checks). By default it emits a structured JSON report of findings to standard output; when an opt-in posting flag is set, it posts the findings to the pull request instead. In both cases it returns an **advisory** exit code reflecting the assessment.
- v1 never blocks a merge on the tool's output; the report (stdout or posted) is the human-facing signal a reviewer acts on.

### Secondary
- (File/line anchors on every finding were promoted to must-have; they appear in both the stdout report and the posted output.) No separate nice-to-have pinned for v1 yet; candidate for v1.1: per-finding severity/confidence so the reviewer can triage which findings to trust.

### Guardrails
- **No secret/source leakage** — repo credentials, secrets, and source must never persist beyond the analysis call, and must never be echoed into the posted output. (In default stdout mode nothing is written to the host at all.)
- **Bounded per-review cost** — spend on the external analysis source per review is predictable and capped; there is no unbounded escalation.

## User Stories

### US-01: Reviewer receives a critical-point map on a change ready for review

- **Given** a change is ready for review against a target branch, reviewer-target-o-meter is pointed at the checked-out directory (as a CI step or run locally), and access to the external analysis source is configured (a host credential is configured only if findings will be posted)
- **When** the run reaches the analysis step
- **Then** the tool loads the repo's context (AGENTS.md, skills, source) from the checked-out directory, computes a capped diff against the target branch from local history, runs the critical-point analysis (skipping plan-dependent checks if no plan exists), and by default emits a structured JSON report of findings (each with a file/line anchor) to standard output; when the posting flag is set, it posts the findings to the pull request instead; in both cases it returns an **advisory** exit code

#### Acceptance Criteria
- By default, findings are emitted as a structured JSON report to standard output, each carrying a file/line anchor, before the step exits (FR-007, FR-009); when the posting flag is set, findings are posted to the pull request instead
- Exit code reflects the assessment but is **advisory in v1** — it must NOT block merges; the report (stdout or posted) is the human-facing signal (FR-008)
- A hardcoded severity-to-signal mapping determines what gets flagged (FR-011)
- If repo context files are absent (no AGENTS.md/skills), the run degrades gracefully to a diff-based review rather than crashing (FR-010)
- If no plan.md exists, plan-dependent checks are skipped and the rest of the analysis still runs (FR-006)

## Functional Requirements

### Invocation & input
- FR-001: reviewer-target-o-meter can be invoked as a CI step in the pipeline or run as a local CLI (same code path). Priority: must-have
  > Socrates: Counter-argument considered: "Actions-only excludes local/pre-commit use where issues are cheapest to fix." Resolution: adopted — also runnable as a local CLI so devs iterate before pushing.
- FR-002: reviewer-target-o-meter can accept the checked-out project directory as its sole input parameter and operate entirely on that local checkout (source + diff) — it does NOT fetch or discover the pull request via the host API. Priority: must-have
  > Socrates: Counter-argument considered: "a directory couples to a filesystem; a PR number is more portable." Resolution: overridden — the tool always runs inside the change's CI context, where the full checkout and git history are already present, so the directory is sufficient for both source and diff. The host credential and pull-request identifier, needed only when posting findings, are read from the CI runtime environment, not passed as input.
- FR-003: reviewer-target-o-meter can authenticate to the git hosting platform ONLY to post findings (when the posting flag is set), using a credential/token available in the CI runtime environment; reading source and computing the diff are local operations that do not use the host API. Priority: must-have
  > Socrates: Counter-argument considered: "a long-lived CI token is a rotation/scope liability." Resolution: stands for v1, and is now scoped to posting only — since reading is local, the credential is exercised only when findings are opted into posting; token rotation hardening remains a future concern.

### Context & diff
- FR-004: reviewer-target-o-meter can load review context — AGENTS.md, skills, and the project source — from the checked-out directory. Priority: must-have
  > Socrates: Counter-argument considered: "diff-only is enough; context-loading is gold-plating and rarely exists." Resolution: kept core — context-aware review is the product's distinguishing value; diff-only is the fallback (FR-010), not the primary path.
- FR-005: reviewer-target-o-meter can compute the diff between the current branch and the target branch from local git history, capped/segmented to stay within the analysis context budget. Priority: must-have
  > Socrates: Counter-argument considered: "a whole-PR diff can be enormous and blow the budget." Resolution: adopted — the diff is capped/segmented per the context budget.

### Analysis & output
- FR-006: reviewer-target-o-meter can run a critical-point analysis (plan discovery, drift/safety/pattern checks), skipping plan-dependent checks gracefully when no plan exists. Priority: must-have
  > Socrates: Counter-argument considered: "that analysis assumes a plan exists; most PRs won't have one." Resolution: kept, but plan-dependent checks are skipped when no plan exists; the rest still runs (ties to FR-010).
- FR-007: reviewer-target-o-meter can, by default, emit the findings as a structured JSON report to standard output; and, when an opt-in posting flag is set, post the findings to the pull request on the git hosting platform instead of stdout. Priority: must-have
  > Socrates: Counter-argument considered: "a comment dump is noisy/spammy." Resolution: revised — the noise concern is now handled by making stdout the default (nothing is posted unless explicitly opted in). The exact posting format under the flag (plain pull-request comment vs. an inline review with line-level annotations) is unresolved; see Open Questions.
- FR-008: reviewer-target-o-meter can return an exit code that reflects the assessment; in v1 it is advisory (consumers should NOT hard-block merges on it) — the report (stdout or posted) is the human-facing signal. Priority: must-have
  > Socrates: Counter-argument considered: "a wrong no-go blocks real work." Resolution: adopted — v1 is advisory; blocking is a future, opt-in behavior.
- FR-009: reviewer-target-o-meter can attach a file/line anchor to every finding, present in both the stdout JSON report and, under the posting flag, in the posted output. Priority: must-have
  > Socrates: Counter-argument considered: "hunk→line mapping is fiddly and drifts on rebases; skip for v1." Resolution: stands — promoted to must-have; anchors are part of the finding shape in both output modes. Whether they render as inline annotations in the posted output depends on the posting-format decision (see Open Questions).

### Robustness & configuration
- FR-010: reviewer-target-o-meter can detect whether the repo has context conventions (AGENTS.md / skills) and degrade gracefully to a diff-based review when absent. Priority: must-have
  > Socrates: Counter-argument considered: "two code paths; the fallback becomes the real product." Resolution: kept — context-loading is the primary path (FR-004 resolution); the fallback handles the edge case, not the main product.
- FR-011: reviewer-target-o-meter applies a hardcoded (non-configurable in v1) severity-to-signal mapping; configurability is deferred. Priority: must-have
  > Socrates: Counter-argument considered: "config surface is burden for v1." Resolution: adopted — hardcoded default for v1; configurability deferred.

## Non-Functional Requirements

- **Actionable, non-generic findings** — every finding carries a file/line location and a rationale; generic style nits are out of scope. Output must be worth the reviewer's attention.
- **Consistent across re-runs** — re-running the analysis on the same checkout/SHA produces consistent findings (no high-variance output between runs).
- **Bounded review latency** — a typical review completes within ~5 minutes wall-clock, so it does not bottleneck CI.
- *(Note: the advisory exit-code design (FR-008) means the workflow should not hard-block on the tool's output regardless of upstream hiccups; an explicit fail-safe NFR was considered but not pinned — see Open Questions.)*

## Business Logic

For a given pull request, the application identifies the risks the change introduces and characterizes each finding by severity and location, so the reviewer knows exactly what to scrutinize.

Inputs it consumes (as seen by the reviewer, not the machinery): the changed code, the surrounding repo context (its conventions and any change plan), and the target branch the change is meant to merge into — all read from the local checked-out directory. Output: a set of findings, each carrying a severity, a file/line location, and a short rationale. The reviewer encounters it as a structured report on standard output by default, or — when posting is opted into — as annotations on the pull request they are already reading; there is no separate surface to visit.

## Access Control

The reviewer does not log into a separate product. Access is governed entirely by repository membership on the git hosting platform:

- **Reviewer consuming results** — the critical-point assessment is emitted to standard output by default (visible to whoever runs the tool, including in CI logs); when posted, it appears on the pull request and inherits the repo's existing access. Any repo member who can already see the PR can see posted findings.
- **Tool acting on the repo** — the tool reads the checked-out directory locally and does not contact the host API to read. It authenticates to the git hosting platform ONLY to post findings (when the posting flag is set), using a credential/token available in the CI runtime environment, and writes its findings with that identity.
- **Role model** — flat for the MVP. Every repo member sees findings equally; there are no separate configure vs read-only roles in v1. Configuration of the CI credential is the only maintainer-only action, and it happens at the host/CI level, not inside this product.

## Non-Goals

- **No merge blocking in v1** — the exit code is advisory; it must NOT gate a merge. Blocking is a future, opt-in behavior. (Load-bearing — from FR-008.)
- **No own deterministic checks (linters/tests)** — that is the remote project's existing CI step; reviewer-target-o-meter does the agentic risk assessment only.
- **No auto-fixing / patch generation** — the tool flags risks and locations; it does not write or apply fixes.
- **No separate web dashboard / UI** — findings live only in the stdout report or, when posted, on the pull request.
- **No host-API discovery/loading** — the tool operates on the local checked-out directory; it does not fetch the pull request or its files via the host API. (Load-bearing — from FR-002.)
- **No multi-host support in v1** — v1 targets a single git hosting platform; support for additional hosts is deferred. (The specific host is a stack decision — see Open Questions.)
- **No offline-first guarantee** — the tool inherently needs network access to the external analysis source (and, in posting mode, to the git host); it is not designed to run disconnected.

## Open Questions

1. **Fail-safe on upstream errors** — what must happen when the analysis source is unavailable, or (in posting mode) the git host errors mid-run? Since the exit code is advisory (FR-008), the step should likely NOT fail the CI run, but the exact behavior is undecided: in default stdout mode (no host-read dependency, since reading is local), options include retry, skip, or emit a partial/empty report with exit 0 + warning; in posting mode, additionally whether to post a "review unavailable" comment. — Owner: user. Resolve before/during planning.
2. **Per-review cost ceiling** — "bounded per-review cost" is a guardrail; the actual $-per-review cap and the mechanism to enforce it (max tokens, max agent steps, max model calls) are not yet specified. — Owner: user.
3. **Severity taxonomy** — FR-011 uses a hardcoded severity-to-signal mapping, but the severity levels themselves (e.g., critical / warning / info) and what maps to "flagged" are not yet defined. — Owner: user.
4. **Diff cap policy** — FR-005 caps/segments the diff to the analysis context budget, but the cap size and segmentation strategy (per-file? by hunk? by changed-lines budget?) are open. — Owner: user.
5. **Git hosting platform** — v1 targets a single platform; the specific host is confirmed and locked at the tech-stack-selection step. Block: no (scope decision), but the host identity is pinned downstream, not in this PRD.
6. **External analysis source / model provider** — the AI source that powers the critical-point analysis is a means, not a product property; it is locked at the tech-stack-selection step. Block: no.
7. **Critical-point analysis methodology provenance** — the analysis follows an established implementation-review methodology (plan discovery, drift/safety/pattern checks). Its specific provenance and any reuse of an existing review checklist are deferred to planning. — Owner: user. (Routed from FR-006.)
8. **Posting format under the posting flag** — FR-007 makes posting opt-in via a flag, but the format of the posted output is unresolved: is it a plain pull-request comment, or an inline review with line-level annotations (which FR-009's anchors would populate)? This reconciles the prior "inline review, not a comment dump" resolution with the "pull request comment" phrasing. — Owner: user. Block: no (affects posting-mode rendering only; the stdout default is unaffected), but resolve before the posting slice is planned.
9. **Target-branch / diff-base discovery** — with no pull-request identifier passed as input (FR-002), how does the tool determine the target branch to diff against (a CI runtime environment variable? a git merge-base heuristic? an explicit default-branch name?)? — Owner: user. Block: no (implementation detail); route to planning.
