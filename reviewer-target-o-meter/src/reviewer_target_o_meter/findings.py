"""Typed output contract for the reviewer-agent (FR-009 anchors, FR-011 signal, OQ#3).

The full impl-review shape: Severity + Impact + 7-dimension + Fix-grammar. The model
picks enum values and content; the *host* decides signal — ``Severity.is_flagged`` is a
plain ``@property`` (NOT a ``@computed_field``) so it never appears in the JSON schema the
model sees. Likewise ``FindingsReport.flagged``/``exit_code`` are host-side derivations.

No ``Decision: PENDING`` field (CI-harness-triage only) and no ``id`` on ``Finding``
(the ``report`` node injects ``F{n}`` during serialization — models are unreliable at
sequential ids).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Severity(str, Enum):
    """CRITICAL/WARNING/OBSERVATION — the impl-review-ci taxonomy (OQ#3)."""

    CRITICAL = "critical"
    WARNING = "warning"
    OBSERVATION = "observation"

    @property
    def is_flagged(self) -> bool:
        """FR-011 hardcoded signal: CRITICAL/WARNING flag, OBSERVATION does not.

        A plain property (not ``@computed_field``) — deliberately absent from the JSON
        schema the model sees, so the host keeps sole authority over the signal mapping.
        """
        return self in (Severity.CRITICAL, Severity.WARNING)


class Impact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Dimension(str, Enum):
    """The seven impl-review dimensions (research.md:198-202)."""

    CORRECTNESS = "correctness"
    SECURITY = "security"
    MAINTAINABILITY = "maintainability"
    TESTABILITY = "testability"
    PERFORMANCE = "performance"
    DESIGN = "design"
    DOCUMENTATION = "documentation"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FixOption(BaseModel):
    """A fix DIRECTION — one sentence, never an applied patch (Non-Goal prd.md:119)."""

    model_config = ConfigDict(frozen=True)

    approach: str = Field(..., min_length=1, description="One-sentence fix DIRECTION, never an applied patch.")
    strength: str | None = None
    tradeoff: str | None = None
    blind_spot: str | None = None
    confidence: Confidence | None = None
    recommended: bool = False


class Finding(BaseModel):
    """One reviewer finding with a mandatory file/line anchor (FR-009)."""

    model_config = ConfigDict(frozen=True)

    file: str = Field(..., min_length=1)
    line: int = Field(..., ge=1)  # 1-based — FR-009 mandatory
    end_line: int | None = Field(default=None, ge=1)
    severity: Severity
    impact: Impact
    dimension: Dimension
    title: str = Field(..., min_length=1, max_length=120)
    detail: str = Field(..., min_length=1)  # = rationale (FR-009)
    fixes: list[FixOption] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def _end_line_ge_line(self) -> Finding:
        if self.end_line is not None and self.end_line < self.line:
            raise ValueError("end_line must be >= line")
        return self

    @field_validator("file")
    @classmethod
    def _no_absolute_path(cls, v: str) -> str:
        if v.startswith("/"):
            raise ValueError("file must be repo-relative, not absolute")
        return v

    @model_validator(mode="after")
    def _fixes_grammar(self) -> Finding:
        if len(self.fixes) == 2 and sum(o.recommended for o in self.fixes) != 1:
            raise ValueError("two fix options must mark exactly one recommended")
        return self


class FindingsReport(BaseModel):
    """The validated output. Signal + exit code are host-side, hidden from the model."""

    findings: list[Finding] = Field(default_factory=list)
    summary: str | None = None
    overall_verdict: str | None = None

    @property
    def flagged(self) -> list[Finding]:
        return [f for f in self.findings if f.severity.is_flagged]

    @property
    def exit_code(self) -> int:
        """FR-008 advisory: 0 if nothing flagged, else 1. Never blocks a merge."""
        return 1 if self.flagged else 0
