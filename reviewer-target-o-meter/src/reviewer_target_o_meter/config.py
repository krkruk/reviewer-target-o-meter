"""Env-driven runtime configuration (OQ#2 mechanism + provider wiring knobs).

One place holds the model slug, endpoint, cost/latency bounds, and attribution
headers — all env-overridable. The model slug lives in a single constant so a
free-tier withdrawal is a one-line change (research.md:567).
"""

from __future__ import annotations

import os
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class Config(BaseModel):
    """Frozen view of the runtime config, populated from the environment.

    The cost/latency knobs and attribution headers are ``ClassVar`` constants — the
    single source the graph/provider read from, identical across instances.
    """

    model_config = ConfigDict(frozen=True)

    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL

    # --- Cost / latency knobs (OQ#2 mechanism, ~5-min NFR prd.md:98) ---
    recursion_limit: ClassVar[int] = 40
    max_iterations: ClassVar[int] = 12
    run_timeout: ClassVar[int] = 120  # seconds — enforced via TimeoutPolicy on `checks`

    # --- OpenRouter attribution headers (set on the ChatOpenAI client) ---
    ATTRIBUTION_HEADERS: ClassVar[dict[str, str]] = {
        "HTTP-Referer": "https://github.com/reviewer-target-o-meter",
        "X-Title": "reviewer-target-o-meter",
    }

    @classmethod
    def from_env(cls) -> Config:
        """Build a Config from the process environment.

        Raises if ``OPENROUTER_API_KEY`` is unset/empty — it is the only required var.
        """
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required (set it in .env; see .env.example)"
            )
        return cls(
            api_key=api_key,
            model=os.environ.get("MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
            base_url=os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
        )

    @property
    def attribution_headers(self) -> dict[str, str]:
        return dict(self.ATTRIBUTION_HEADERS)
