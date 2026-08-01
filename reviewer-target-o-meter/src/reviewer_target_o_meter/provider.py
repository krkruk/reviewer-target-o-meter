"""OpenRouter provider wiring + the structured-output fail-safe wrapper.

The provider client is OpenAI-compatible against OpenRouter, deterministic
(temperature=0). The structured-output wrapper returns a validated ``FindingsReport``
and degrades to an empty report (exit 0) on any parse failure — the host-side
re-check that compensates for free-tier looseness (OQ#1, research.md:539-543).
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import SecretStr, ValidationError

from .config import Config
from .findings import FindingsReport

# Reasoning tokens are emitted separately from the structured payload; set generous
# max_tokens so reasoning + JSON both fit and the JSON doesn't truncate mid-generation
# (research.md:316-319). Set as a field after construction (the typed __init__ overloads
# don't list it, though it is a valid model field).
_MAX_TOKENS = 8192


def build_llm(config: Config) -> ChatOpenAI:
    """Build the OpenAI-compatible client pointing at OpenRouter.

    Never hardcodes or echoes the key; temperature=0 for "consistent across
    re-runs" (prd.md:97).
    """
    llm = ChatOpenAI(
        model=config.model,
        base_url=config.base_url,
        api_key=SecretStr(config.api_key),
        temperature=0,
        default_headers=config.attribution_headers,
    )
    llm.max_tokens = _MAX_TOKENS
    return llm


def build_structured_llm(config: Config):
    """Bind ``FindingsReport`` structured output with the de-risking contract.

    ``method="json_schema"`` + ``strict=True`` + ``include_raw=True``: the free model
    emits the full schema, and a parse failure is returned (catchable) rather than
    raised. Pair with :func:`to_report` for the host-side re-validation.
    """
    return build_llm(config).with_structured_output(
        FindingsReport,
        method="json_schema",
        strict=True,
        include_raw=True,
    )


def to_report(result: Any) -> FindingsReport:
    """Coerce a structured-output result into a validated ``FindingsReport``.

    Handles two shapes:
      * the ``include_raw=True`` dict ``{"raw", "parsed", "parsing_error"}``; and
      * a bare parsed object / dict passed directly.

    On any parse/validation failure, returns an *empty* report with exit 0 and a
    warning in ``summary`` (OQ#1 fail-safe) — the agent never raises out.
    """
    parsed: Any = None
    if isinstance(result, dict) and {"raw", "parsed", "parsing_error"} <= set(result):
        # include_raw=True shape: if the runner already flagged a parse error, degrade.
        if result.get("parsing_error") is not None:
            return _empty_with_warning(str(result["parsing_error"]))
        parsed = result.get("parsed")
    else:
        parsed = result

    try:
        return FindingsReport.model_validate(parsed)
    except (ValidationError, TypeError, ValueError) as exc:
        return _empty_with_warning(str(exc))


def _empty_with_warning(reason: str) -> FindingsReport:
    return FindingsReport(
        findings=[],
        summary=f"WARNING: structured-output parse failed; emitted empty report ({reason}).",
    )
