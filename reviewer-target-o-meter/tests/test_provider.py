"""Provider factory + structured-output wrapper tests (mocked client, offline).

The live OpenRouter smoke is in test_smoke_provider.py (system-level, opt-in).
Here we pin: (1) build_llm wires model/base_url/temperature=0 from Config;
(2) to_report validates a good payload and degrades to an empty report on
parse failure (OQ#1 fail-safe).
"""

from langchain_openai import ChatOpenAI

from reviewer_target_o_meter.config import Config
from reviewer_target_o_meter.findings import FindingsReport, Severity
from reviewer_target_o_meter.provider import build_llm, build_structured_llm, to_report


def _cfg(**overrides) -> Config:
    base: dict[str, str] = {"api_key": "sk-test", "model": "vendor/slug", "base_url": "https://gw.example/v1"}
    base.update(overrides)
    return Config(**base)


# --- build_llm ---


def test_build_llm_returns_chatopenai_with_config() -> None:
    cfg = _cfg()
    llm = build_llm(cfg)
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "vendor/slug"
    assert str(llm.openai_api_base) == "https://gw.example/v1"


def test_build_llm_is_deterministic_temperature_zero() -> None:
    # prd.md:97 "consistent across re-runs" NFR.
    llm = build_llm(_cfg())
    assert llm.temperature == 0


def test_build_llm_sets_attribution_headers() -> None:
    llm = build_llm(_cfg())
    headers = llm.default_headers
    assert "HTTP-Referer" in headers and "X-Title" in headers


# --- build_structured_llm ---


def test_build_structured_llm_uses_json_schema_strict_with_raw() -> None:
    # The de-risking contract: json_schema method, strict, include_raw so a parse
    # failure is catchable rather than raising (OQ#1 fail-safe).
    runnable = build_structured_llm(_cfg())
    # include_raw=True -> the bound runnable yields a dict with raw/parsed/parsing_error.
    # We assert the binding happened (it is a RunnableSerializable), not its internals.
    assert hasattr(runnable, "invoke")


# --- to_report fail-safe ---


def _good_finding_dict() -> dict:
    return {
        "findings": [
            {
                "file": "src/app.py", "line": 10,
                "severity": "critical", "impact": "high",
                "dimension": "security", "title": "SQLi", "detail": "concat",
            }
        ],
        "summary": "ok", "overall_verdict": "needs work",
    }


def test_to_report_validates_good_include_raw_payload() -> None:
    good = _good_finding_dict()
    result = {"raw": object(), "parsed": FindingsReport.model_validate(good), "parsing_error": None}
    report = to_report(result)
    assert isinstance(report, FindingsReport)
    assert len(report.findings) == 1
    assert report.findings[0].severity is Severity.CRITICAL
    assert report.exit_code == 1


def test_to_report_validates_bare_parsed_payload() -> None:
    # When the caller passes the parsed object directly (no raw wrapper).
    report = to_report(_good_finding_dict())
    assert isinstance(report, FindingsReport) and len(report.findings) == 1


def test_to_report_degrades_to_empty_on_parse_error() -> None:
    # parsing_error present -> degrade safely: empty report, exit 0, warning summary (OQ#1).
    result = {"raw": object(), "parsed": None, "parsing_error": ValueError("bad json")}
    report = to_report(result)
    assert isinstance(report, FindingsReport)
    assert report.findings == []
    assert report.exit_code == 0
    assert report.summary is not None and "warn" in report.summary.lower()


def test_to_report_degrades_on_invalid_payload_shape() -> None:
    # A payload that passes the runner but fails our stricter host-side re-validation.
    bad = {"findings": [{"file": "/abs/path.py", "line": 1, "severity": "critical",
                          "impact": "high", "dimension": "security", "title": "x", "detail": "y"}]}
    report = to_report(bad)
    assert report.findings == [] and report.exit_code == 0
