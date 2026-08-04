"""Prompt-invariant tests for the ``checks`` node's system prompt + usage-telemetry.

These are offline guards over ``_SYSTEM_PROMPT``'s load-bearing invariants — the
lines the product hypothesis depends on (S-01 plan §1.2). They lock the
diff-scoping protocol, plan-tolerance conditional, no-execution rule, the
per-dimension cap reference, and the three review-lens names, so a future edit
cannot silently drop the single most load-bearing line.

The ``_extract_usage`` tests (Phase 2, H-B) guard the best-effort usage-telemetry
probe: it must read ``usage_metadata``/``response_metadata`` from the agent
result's last message and NEVER raise when metadata or messages are absent.

No model call: these assert on the module-level f-string / pure helper only.
"""

from __future__ import annotations

from typing import Any, ClassVar

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

    def test_substantive_gate_removed(self) -> None:
        """The recall-suppressing "Report only substantive issues" gate is gone.

        A validation run missed a swallowed ``except Exception`` and an unbounded
        global dict — both real reliability smells the model self-suppressed under
        this gate. The phrase must stay out of the prompt so a future edit can't
        silently re-introduce it. Whitespace-collapsed so a line-wrap can't hide it.
        """
        import re
        collapsed = re.sub(r"\s+", " ", PROMPT_LOWER)
        assert "report only substantive issues" not in collapsed

    def test_error_suppression_pattern_named(self) -> None:
        """The safety lens names present-but-hostile error handling: a bare or
        broad ``except`` that swallows the error and returns a default (hiding
        failures). Covers the ``stats()`` defect class the validation missed.
        """
        assert "swallow" in PROMPT_LOWER or "bare" in PROMPT_LOWER
        assert "except" in PROMPT_LOWER

    def test_unbounded_growth_pattern_named(self) -> None:
        """The safety lens names unbounded state accumulation: a collection
        (especially module-level / process-global) that grows without bound over
        the process lifetime with no eviction. Covers the ``_posts`` defect class.
        """
        assert "unbounded" in PROMPT_LOWER

    def test_observation_severity_recall_guidance_present(self) -> None:
        """The prompt directs the model to emit minor-but-real smells at
        OBSERVATION severity, so recall-positive guidance doesn't inflate
        CRITICAL/WARNING. Replaces the old "substantive" self-suppression gate.
        """
        assert "observation severity" in PROMPT_LOWER

    def test_optional_findings_section_present(self) -> None:
        """The prompt directs the model to emit 1-3 style/pickiness observations
        into ``optional_findings`` on every review — naming the field and the
        non-blocking intent so the model uses the bucket (not the main list).
        """
        assert "optional_findings" in PROMPT_LOWER
        assert "style" in PROMPT_LOWER or "picky" in PROMPT_LOWER


# --- usage telemetry probe (Phase 2, H-B) ---


class TestExtractUsageBestEffort:
    """``_extract_usage`` is the best-effort token/usage probe on the success path.

    It reads ``usage_metadata``/``response_metadata`` from the agent result's last
    message (mirroring the shapes the real agent and the test ``_FakeAgent``
    return) and MUST NOT raise when metadata or messages are absent — missing
    metadata means skip the breadcrumb, never a crash (plan §Phase 2.2 contract).
    """

    def test_reads_usage_from_last_ai_message(self) -> None:
        """A normal completion surfaces ``usage_metadata`` + ``response_metadata`` on
        the last message. The probe pulls input/output/total tokens + finish_reason.
        """
        from langchain.messages import AIMessage

        from reviewer_target_o_meter.agent.nodes import _extract_usage

        msg = AIMessage(
            content="{}",
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            response_metadata={"finish_reason": "stop"},
        )
        result = {"messages": [msg]}
        usage = _extract_usage(result)
        assert usage is not None
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.total_tokens == 150
        assert usage.finish_reason == "stop"

    def test_returns_none_when_no_messages(self) -> None:
        """The ``_FakeAgent`` test fixture returns ``{"messages": []}``; the probe
        must skip (return None) rather than index-error.
        """
        from reviewer_target_o_meter.agent.nodes import _extract_usage

        assert _extract_usage({"messages": []}) is None
        assert _extract_usage({}) is None
        assert _extract_usage(None) is None  # type: ignore[arg-type]

    def test_returns_none_when_last_message_lacks_usage_metadata(self) -> None:
        """A message without ``usage_metadata`` (e.g. a HumanMessage, or a stripped
        tool message) must skip the breadcrumb — never raise.
        """
        from langchain.messages import HumanMessage

        from reviewer_target_o_meter.agent.nodes import _extract_usage

        result = {"messages": [HumanMessage(content="hi")]}
        assert _extract_usage(result) is None

    def test_returns_none_when_usage_metadata_incomplete(self) -> None:
        """A partial ``usage_metadata`` (missing token keys) must skip, not crash.
        Defensive against the free-tier model attaching a malformed usage block at
        runtime (AIMessage's constructor rejects this, but the helper can't assume
        its input is constructor-validated). Uses a stub message to exercise the
        helper's own try/except.
        """
        from reviewer_target_o_meter.agent.nodes import _extract_usage

        class _StubMsg:
            usage_metadata: ClassVar[Any] = {"input_tokens": 10}  # missing output/total
            response_metadata: ClassVar[Any] = {"finish_reason": "stop"}

        assert _extract_usage({"messages": [_StubMsg()]}) is None

    def test_reads_structured_response_messages_shape(self) -> None:
        """The ``_extract_findings`` helper already tolerates the
        ``structured_response`` + ``messages`` shape the real agent exposes; the
        usage probe must read the last message from that same shape.
        """
        from langchain.messages import AIMessage

        from reviewer_target_o_meter.agent.nodes import _extract_usage

        msg = AIMessage(
            content="{}",
            usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
            response_metadata={"finish_reason": "length"},
        )
        result = {"structured_response": object(), "messages": [msg]}
        usage = _extract_usage(result)
        assert usage is not None
        assert usage.finish_reason == "length"
        assert usage.output_tokens == 3

