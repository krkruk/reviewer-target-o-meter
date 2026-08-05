"""Env-driven runtime configuration (OQ#2 mechanism + provider wiring knobs).

One place holds the model slug, endpoint, cost/latency bounds, and attribution
headers — all env-overridable. The model slug lives in a single constant so a
free-tier withdrawal is a one-line change (research.md:567).
"""

from __future__ import annotations

import os
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ._util import warn

DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class Config(BaseModel):
    """Frozen view of the runtime config, populated from the environment.

    The cost/latency knobs and attribution headers are ``ClassVar`` constants — the
    single source the graph/provider read from, identical across instances.
    """

    model_config = ConfigDict(frozen=True)

    api_key: str = Field(..., repr=False)  # never echo in repr — prevents accidental key exposure
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    # OpenRouter reasoning effort (fine-tune-context diagnosis): medium is the
    # measured sweet spot — low emits empty/malformed JSON on the final
    # structured-output turn (StructuredOutputValidationError, run 6); high
    # over-investigates and exhausts the iteration cap before emitting. Medium
    # emits reliably AND, with the hard tool-budget cap in the prompt, converges
    # in time. Overridable via REASONING_EFFORT for diagnosis runs.
    # Accepted values: none/minimal/low/medium/high/xhigh/max (OpenRouter docs).
    reasoning_effort: str = "medium"

    # --- Phase 5: PR / GitHub / base-ref inputs (all optional, env-driven) ---
    base_ref: str | None = None
    pr_number: int | None = None
    github_token: str | None = Field(default=None, repr=False)  # secret — never echo
    github_repository: str | None = None
    github_api_url: str = "https://api.github.com"
    # stderr step-trace verbosity (INFO by default; the Markdown preview is
    # independent of this — it is the payload, not a log line).
    log_level: str = "INFO"

    # --- Cost / latency knobs (OQ#2 mechanism, ~5-min NFR prd.md:98) ---
    recursion_limit: ClassVar[int] = 40
    # Final value (fine-tune-context diagnosis): the agent must reserve its last
    # turn for the structured-output emit. Lower values (8/12) saw it spend every
    # turn on tool batches and hit "run limit" before emitting. 16 gives
    # headroom for ~8 tool turns + the final emit at medium reasoning.
    # See context/changes/fine-tune-context/diagnosis.md.
    max_iterations: ClassVar[int] = 16
    # Final value (fine-tune-context diagnosis): a SEPARATE cap on TOOL calls
    # (ToolCallLimitMiddleware, exit_behavior='continue'). The deepseek model
    # never self-limits its investigation — without this it burns every model
    # call on tools and never emits (0 findings, runs 4/7/8). 18 lets a well-
    # batched model (3 calls/turn) do ~6 investigation turns then emit; a 1-call-
    # per-turn over-investigator is forced to converge and emit before exhausting
    # max_iterations. Over-budget tool calls return an "exhausted" message that
    # pushes the model to emit. See diagnosis.md.
    max_tool_calls: ClassVar[int] = 18
    # Final value (fine-tune-context diagnosis): 300 gives a paid 1M-context
    # model room to reason over a large diff; run 3 finished in 221s once the
    # tool-path bug was fixed. See diagnosis.md for the measured rationale.
    run_timeout: ClassVar[int] = 300  # seconds — enforced via TimeoutPolicy on `checks`

    # --- OpenRouter attribution headers (set on the ChatOpenAI client) ---
    ATTRIBUTION_HEADERS: ClassVar[dict[str, str]] = {
        "HTTP-Referer": "https://github.com/reviewer-target-o-meter",
        "X-Title": "reviewer-target-o-meter",
    }

    @classmethod
    def from_env(cls) -> Config:
        """Build a Config from the process environment.

        Raises if ``OPENROUTER_API_KEY`` is unset/empty — it is the only required var.
        ``PR_NUMBER`` is parsed forgivingly: a non-integer parses to ``None`` with
        a ``WARNING:`` (the switch stays False) rather than crashing the pipeline.
        """
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required (set it in .env; see .env.example)"
            )

        pr_number = _parse_pr_number(os.environ.get("PR_NUMBER"))

        return cls(
            api_key=api_key,
            model=os.environ.get("MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
            base_url=os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
            reasoning_effort=(os.environ.get("REASONING_EFFORT", "medium") or "medium").lower(),
            base_ref=_clean(os.environ.get("BASE_REF")),
            pr_number=pr_number,
            github_token=_clean(os.environ.get("GITHUB_TOKEN")),
            github_repository=_clean(os.environ.get("GITHUB_REPOSITORY")),
            github_api_url=_clean(os.environ.get("GITHUB_API_URL")) or "https://api.github.com",
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper() or "INFO",
        )

    @property
    def post_to_github(self) -> bool:
        """The single mode switch: post only when all three PR inputs are present.

        ``PR_NUMBER`` + ``GITHUB_TOKEN`` + ``GITHUB_REPOSITORY`` must all be set
        (and ``pr_number`` must have parsed to an int). Any missing → stdout mode.
        """
        return self.pr_number is not None and bool(self.github_token) and bool(self.github_repository)

    @property
    def attribution_headers(self) -> dict[str, str]:
        return dict(self.ATTRIBUTION_HEADERS)


def _clean(value: str | None) -> str | None:
    """Strip whitespace; treat empty string as None (unset)."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_pr_number(raw: str | None) -> int | None:
    """Parse ``PR_NUMBER`` forgivingly: non-integer → None + a WARNING."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        warn(f"PR_NUMBER={raw!r} is not an integer; GitHub posting disabled.")
        return None
