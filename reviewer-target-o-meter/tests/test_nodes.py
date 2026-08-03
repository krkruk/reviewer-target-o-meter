"""Prompt-invariant tests for the ``checks`` node's system prompt.

These are offline guards over ``_SYSTEM_PROMPT``'s load-bearing invariants — the
lines the product hypothesis depends on (S-01 plan §1.2). They lock the
diff-scoping protocol, plan-tolerance conditional, no-execution rule, the
per-dimension cap reference, and the three review-lens names, so a future edit
cannot silently drop the single most load-bearing line.

No model call: these assert on the module-level f-string only.
"""

from __future__ import annotations

from reviewer_target_o_meter.agent.nodes import (
    _SYSTEM_PROMPT,
    MAX_FINDINGS_PER_DIMENSION,
)

PROMPT = _SYSTEM_PROMPT
PROMPT_LOWER = _SYSTEM_PROMPT.lower()


class TestSystemPromptInvariants:
    """Lock the load-bearing lines of the full methodology prompt."""

    def test_diff_scoping_anchor_rule_present(self) -> None:
        """The anchor rule: never flag a file the PR did not change.

        This is the core differentiator against a repo-wide linter (the failure
        mode that kills the product). Must read as a hard rule, not a suggestion.
        """
        assert "never flag a file the pr did not change" in PROMPT_LOWER

    def test_diff_scoping_active_investigation_protocol(self) -> None:
        """Diff-scoping is an ACTIVE investigation, not a passive 'confirm a
        concern' filter.

        The old minimal framing ('tools exist ONLY to confirm a concern') under-
        investigates; the full methodology must direct the model to READ the
        changed files first, then use the tools to trace symbols/flow and read
        siblings. Asserting BOTH the new active protocol AND the removal of the
        old passive phrase.
        """
        # Active protocol: read changed files first, then trace with both tools.
        assert "read the changed files first" in PROMPT_LOWER
        assert "structural_search" in PROMPT_LOWER
        assert "text_search" in PROMPT_LOWER
        # The replaced passive framing must be gone.
        assert "confirm a concern" not in PROMPT_LOWER

    def test_plan_tolerance_conditional_present(self) -> None:
        """The plan-tolerance conditional: plan-dependent checks run only when a
        plan is provided, else skipped (FR-006). Keeps Phase 1 independently
        shippable (plan discovery lands in Phase 2).
        """
        assert "if a plan is provided" in PROMPT_LOWER
        assert "if no plan" in PROMPT_LOWER

    def test_no_execution_rule_present(self) -> None:
        """Read-and-flag only: NEVER execute the reviewed project's commands
        (PRD Non-Goal). MISSING-TEST / UNCOVERED-BEHAVIOR come from static
        evidence, never execution.
        """
        assert "never execute" in PROMPT_LOWER

    def test_per_dimension_cap_reference_present(self) -> None:
        """The per-dimension cap (F-02) is referenced in the prompt, so the model
        prioritizes within each dimension. ``MAX_FINDINGS_PER_DIMENSION`` is
        spliced as an f-string at import time.
        """
        assert "per dimension" in PROMPT_LOWER
        assert str(MAX_FINDINGS_PER_DIMENSION) in PROMPT

    def test_three_review_lenses_named(self) -> None:
        """The three review lenses (the thinking method) are named: plan drift,
        safety/quality/pattern compliance, and test coverage.
        """
        assert "plan drift" in PROMPT_LOWER
        assert "safety" in PROMPT_LOWER
        assert "test coverage" in PROMPT_LOWER
