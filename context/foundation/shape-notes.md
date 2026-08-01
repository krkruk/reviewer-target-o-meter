---
project: reviewer-target-o-meter
context_type: greenfield
created: 2026-08-01
updated: 2026-08-01
product_type: cli
target_scale:
  users: small
  qps: low
  data_volume: small
timeline_budget:
  mvp_weeks: 4
  hard_deadline: 2026-08-29
  after_hours_only: true
checkpoint:
  current_phase: 8
  phases_completed: [1, 2, 3, 4, 5, 6, 7]
  gray_areas_resolved:
    - topic: primary persona (reviewer vs author)
      decision: PR reviewer — developer assigned to review others' PRs
    - topic: pain category
      decision: decision paralysis + missing capability (no automated quality signal)
    - topic: insight / why now
      decision: agentic LLM review now accurate/cheap enough via routers (OpenRouter)
    - topic: persona scope
      decision: a specific role inside one org (team of reviewers on their own repos)
    - topic: result consumption surface
      decision: in-PR, via GitHub — specifically a GitHub Review with inline annotations
    - topic: agent GitHub authentication
      decision: CI secret / token configured in the repo
    - topic: role model
      decision: flat — all repo members see findings equally
    - topic: MVP scope
      decision: commit to full v1; ~4 weeks after-hours, sustained-effort cost accepted
    - topic: run surface (FR-001)
      decision: GitHub Actions step AND local CLI (same code path)
    - topic: input model (FR-002)
      decision: accept project directory AND PR number
    - topic: context-loading (FR-004/006/010)
      decision: context-loading is core; diff-only is the fallback for context-less repos
    - topic: diff handling (FR-005)
      decision: diff capped/segmented to the model's context budget
    - topic: analysis plan-tolerance (FR-006)
      decision: skip plan-dependent checks when no plan.md exists; rest still runs
    - topic: posting format (FR-007)
      decision: GitHub Review with inline line-level annotations (not a comment dump)
    - topic: exit-code semantics (FR-008)
      decision: advisory in v1 — must NOT block merges; Review is the signal
    - topic: inline anchors (FR-009)
      decision: promoted to must-have (required by the Review format)
    - topic: threshold config (FR-011)
      decision: hardcoded severity-to-signal mapping in v1; configurability deferred
  frs_drafted: 11
  quality_check_status: accepted
---

# Shape Notes

## Seed idea (verbatim)

I need to build a code reviewer application. It's an agentic application that uses `uv` for python support, OpenRouter as the AI source and cooperates with Github. The application shall be launched as a part of CI Github Actions.

## Forward: tech-stack (informational — NOT a PRD section; for downstream tech-stack-selection)

User-named stack priors captured up front (to be evaluated by the tech-stack-selection step, not locked here):
- Language/runtime: Python, managed with `uv`
- AI source: OpenRouter
- Integration: GitHub (cooperates with GitHub repos / PRs)
- Launch surface: runs as part of CI GitHub Actions
- Product shape signal: "agentic" application

## Forward: technical-roadmap (informational — NOT a PRD section)

(none yet)

## Vision & Problem Statement

A developer assigned to review pull requests must read diffs they didn't write and figure out — under time pressure — which parts are genuinely risky and deserve their attention. Today there is no automated quality signal: humans are the only assessor, so the reviewer re-derives risk from scratch on every PR. On a large or unfamiliar diff this is decision paralysis (what matters most?) plus a missing capability (no machine signal at all), and the cost is slow, inconsistent reviews where critical points can be missed.

The insight that makes this worth building now: agentic LLM code review has recently become accurate and cheap enough — through routers like OpenRouter — that an automated "critical points in this PR" signal is finally fillable at a price and quality point that didn't exist before. The product turns that capability into a focused risk map the reviewer acts on, rather than another noisy style linter.

*Scale note (Step 6 Socrates probe):* the domain rule (identify risks, characterize by severity/location) is unchanged at 100x scale — only the cost and infrastructure constraints would bite harder. The product surface does not need to be different for more users.

## User & Persona

**Primary persona — the PR reviewer.** A developer inside one org whose role includes reviewing teammates' pull requests. They open a PR they've been assigned to, often for code they're not deeply familiar with, and need to decide where to spend their limited review time. Their moment of pain is the instant they land on a large diff and have to judge what matters. The MVP serves this reviewer; the author of the PR is a secondary concern (they benefit indirectly from clearer, faster reviews).

Secondary persona (not MVP): the PR author, who would value a pre-review self-check. Out of scope for v1.

## Access Control

The reviewer does not log into a separate product. Access is governed entirely by GitHub repository membership:

- **Reviewer consuming results** — the critical-point assessment is posted in-PR (as a GitHub review/comment) and inherits the repo's existing access. Any repo member who can already see the PR can see the findings.
- **Agent acting on the repo** — the agent authenticates to GitHub using a secret/token configured in the repo's CI configuration (set once by a maintainer). It reads the PR and writes its findings with that identity.
- **Role model** — flat for the MVP. Every repo member sees findings equally; there are no separate configure vs read-only roles in v1. Configuration of the CI secret is the only maintainer-only action, and it happens at the GitHub/CI level, not inside this product.

## Success Criteria

### Primary
- When a PR is opened/updated, reviewer-target-o-meter runs (as a CI step or local CLI), loads the PR's context (AGENTS.md, skills, source at the PR revision), computes a capped diff against the target branch, runs the `/10x-impl-review-ci`-style critical-point analysis (plan-tolerant), posts the findings as a **GitHub Review with inline, jump-to-location annotations**, and returns an **advisory** exit code reflecting the assessment.
- v1 never blocks a merge on the tool's output; the Review is the human-facing signal a reviewer acts on.

### Secondary
- (The original secondary — inline jump-to-location findings — was promoted to must-have as part of the GitHub Review format decision in Step 4.5.) No separate nice-to-have pinned for v1 yet; candidate for v1.1: per-finding severity/confidence so the reviewer can triage which findings to trust.

### Guardrails
- **No secret/source leakage** — repo tokens, secrets, and source must never leak beyond the analysis call (no persistence into LLM-side storage, no echoing into the posted Review).
- **Bounded per-review cost** — OpenRouter spend per review is predictable and capped (no runaway agent loops burning unbounded budget).

## Timeline acknowledgment

Acknowledged on 2026-08-01: 4-week MVP requires sustained dedication; user accepted. User notes the remote project's CI/CD pipeline already exists, so reviewer-target-o-meter is added as one more action — the workflow-setup cost is near zero, and the 4-week estimate is for the tool itself (context-loading + impl-review analysis engine + GitHub read/write + OpenRouter integration).

## Functional Requirements

### Invocation & input
- FR-001: reviewer-target-o-meter can be invoked as a GitHub Actions step or run as a local CLI (same code path). Priority: must-have
  > Socrates: Counter-argument considered: "Actions-only excludes local/pre-commit use where issues are cheapest to fix." Resolution: adopted — also runnable as a local CLI so devs iterate before pushing.
- FR-002: reviewer-target-o-meter can accept the checked-out project directory AND the PR number; uses the directory for source, the PR number for diff/metadata. Priority: must-have
  > Socrates: Counter-argument considered: "a directory couples to a filesystem; a PR number is more portable." Resolution: take both — directory for source, PR number for diff/metadata.
- FR-003: reviewer-target-o-meter can authenticate to GitHub (via CI secret/token) to read the PR and post findings. Priority: must-have
  > Socrates: Counter-argument considered: "a long-lived CI token is a rotation/scope liability." Resolution: stands for v1 — token rotation hardening is a future concern.

### Context & diff
- FR-004: reviewer-target-o-meter can load review context — AGENTS.md, skills, and the project source at the PR's revision. Priority: must-have
  > Socrates: Counter-argument considered: "diff-only is enough; context-loading is gold-plating and rarely exists." Resolution: kept core — context-aware review is the product's distinguishing value; diff-only is the fallback (FR-010), not the primary path.
- FR-005: reviewer-target-o-meter can compute the diff between the PR branch and the target branch, capped/segmented to stay within the model's context budget. Priority: must-have
  > Socrates: Counter-argument considered: "a whole-PR diff can be enormous and blow the budget." Resolution: adopted — the diff is capped/segmented per the context budget.

### Analysis & output
- FR-006: reviewer-target-o-meter can run the critical-point analysis following the /10x-impl-review-ci methodology (plan discovery, drift/safety/pattern checks), skipping plan-dependent checks gracefully when no plan exists. Priority: must-have
  > Socrates: Counter-argument considered: "that methodology assumes a plan exists; most PRs won't have one." Resolution: kept, but plan-dependent checks are skipped when no plan exists; the rest still runs (ties to FR-010).
- FR-007: reviewer-target-o-meter can post findings as a GitHub Review with inline line-level annotations (not a top-level comment dump). Priority: must-have
  > Socrates: Counter-argument considered: "a comment dump is noisy/spammy." Resolution: adopted — post as a GitHub Review with inline annotations.
- FR-008: reviewer-target-o-meter can return an exit code that reflects the assessment; in v1 it is advisory (consumers should NOT hard-block merges on it) — the GitHub Review is the human-facing signal. Priority: must-have
  > Socrates: Counter-argument considered: "a wrong no-go blocks real work." Resolution: adopted — v1 is advisory; blocking is a future, opt-in behavior.
- FR-009: reviewer-target-o-meter can attach file/line anchors to findings so they render as inline annotations in the GitHub Review. Priority: must-have
  > Socrates: Counter-argument considered: "hunk→line mapping is fiddly and drifts on rebases; skip for v1." Resolution: overridden — promoted to must-have because FR-007's posting format (GitHub Review with inline annotations) requires it.

### Robustness & configuration
- FR-010: reviewer-target-o-meter can detect whether the repo has 10x context (AGENTS.md / skills) and degrade gracefully to a diff-based review when absent. Priority: must-have
  > Socrates: Counter-argument considered: "two code paths; the fallback becomes the real product." Resolution: kept — context-loading is the primary path (FR-004 resolution); the fallback handles the edge case, not the main product.
- FR-011: reviewer-target-o-meter applies a hardcoded (non-configurable in v1) severity-to-signal mapping; configurability is deferred. Priority: must-have
  > Socrates: Counter-argument considered: "config surface is burden for v1." Resolution: adopted — hardcoded default for v1; configurability deferred.

## User Stories

### US-01: Reviewer receives a critical-point map on a new PR
- **Given** a PR is opened/updated against the target branch, reviewer-target-o-meter is wired as a CI step (or run locally with the PR number), and a valid GitHub token + OpenRouter access are configured
- **When** the run reaches the analysis step
- **Then** the agent loads the PR's context (AGENTS.md, skills, source at the PR revision), computes a capped diff against the target branch, runs the impl-review-style critical-point analysis (skipping plan-dependent checks if no plan exists), posts the findings as a **GitHub Review with inline annotations**, and returns an **advisory** exit code

#### Acceptance Criteria
- Findings are posted as a GitHub Review with inline file/line annotations before the step exits (FR-007, FR-009)
- Exit code reflects the assessment but is **advisory in v1** — it must NOT block merges; the Review is the human-facing signal (FR-008)
- A hardcoded severity-to-signal mapping determines what gets flagged (FR-011)
- If 10x context is absent (no AGENTS.md/skills), the run degrades gracefully to a diff-based review rather than crashing (FR-010)
- If no plan.md exists, plan-dependent checks are skipped and the rest of the analysis still runs (FR-006)

## Business Logic

For a given pull request, the application identifies the risks the change introduces and characterizes each finding by severity and location, so the reviewer knows exactly what to scrutinize.

Inputs it consumes (as seen by the reviewer, not the machinery): the PR's changed code, the surrounding repo context (its conventions and any change plan), and the target branch the change is meant to merge into. Output: a set of findings, each carrying a severity, a file/line location, and a short rationale. The reviewer encounters it as inline annotations on the PR they're already reading — no separate surface to visit.

## Non-Functional Requirements

- **Actionable, non-generic findings** — every finding carries a file/line location and a rationale; generic style nits are out of scope. Output must be worth the reviewer's attention.
- **Consistent across re-runs** — re-running the analysis on the same PR/SHA produces consistent findings (no high-variance output between runs).
- **Bounded review latency** — a typical PR review completes within ~5 minutes wall-clock (starting target to refine), so it does not bottleneck CI.
- *(Note: the advisory exit-code design (FR-008) means the workflow should not hard-block on the tool's output regardless of upstream hiccups; an explicit fail-safe NFR was considered but not pinned.)*

## Non-Goals

- **No merge blocking in v1** — the exit code is advisory; it must NOT gate a merge. Blocking is a future, opt-in behavior. (Load-bearing — from FR-008.)
- **No own deterministic checks (linters/tests)** — that is the remote project's existing CI step; reviewer-target-o-meter does the agentic risk assessment only.
- **No auto-fixing / patch generation** — the tool flags risks and locations; it does not write or apply fixes.
- **No separate web dashboard / UI** — findings live only in the GitHub Review posted to the PR.
- **No non-GitHub git hosts in v1** — GitHub only; GitLab/Bitbucket support is deferred.
- **No offline-first guarantee** — the tool inherently needs OpenRouter and GitHub network access; it is not designed to run disconnected.

## Quality cross-check

All six greenfield gate elements present (Access Control, Business Logic one-sentence rule, Project artifacts, Timeline-cost acknowledgment, Non-Goals; Preserved behavior n/a). `quality_check_status: accepted`.

One soft note (not gate-failing, routed to Open Questions): the **fail-safe-on-upstream-error** behavior was considered as an NFR but not pinned.

## Open Questions

1. **Fail-safe on upstream errors** — what must happen when OpenRouter or GitHub is unavailable or erroring mid-run? Since the exit code is advisory (FR-008), the step should likely NOT fail the CI run, but the exact behavior (retry? skip? post a "review unavailable" comment? exit 0 with a warning?) is undecided. — Owner: user. Resolve before/during planning.
2. **Per-review cost ceiling** — "bounded per-review cost" is a guardrail; the actual $-per-review cap and the mechanism to enforce it (max tokens, max agent steps, max model calls) are not yet specified. — Owner: user.
3. **Severity taxonomy** — FR-011 uses a hardcoded severity-to-signal mapping, but the severity levels themselves (e.g., critical / warning / info) and what maps to "flagged in the Review" are not yet defined. — Owner: user.
4. **Diff cap policy** — FR-005 caps/segments the diff to the model's context budget, but the cap size and segmentation strategy (per-file? by hunk? by changed-lines budget?) are open. — Owner: user.
