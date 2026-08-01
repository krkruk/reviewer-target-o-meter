"""Schema validator tests for the Finding/Severity contract.

These pin the machine-validatable output shape (FR-009 anchors, FR-011 hardcoded
signal mapping, OQ#3 severity taxonomy). Outcomes, not internals: each test
asserts a validator accepts/rejects an input or derives a value.
"""

import pytest
from pydantic import ValidationError

from reviewer_target_o_meter.findings import (
    Confidence,
    Dimension,
    Finding,
    FindingsReport,
    FixOption,
    Impact,
    Severity,
)


def _valid_finding(**overrides) -> Finding:
    """Return a minimally-valid Finding, applying per-field overrides."""
    base: dict[str, object] = {
        "file": "src/app.py",
        "line": 10,
        "severity": Severity.WARNING,
        "impact": Impact.HIGH,
        "dimension": Dimension.CORRECTNESS,
        "title": "Untyped SQL string concatenation",
        "detail": "User input flows into a SQL string without parameterization.",
    }
    base.update(overrides)
    return Finding(**base)


# --- Severity.is_flagged (FR-011, hidden from the model) ---


@pytest.mark.parametrize("sev,expected", [
    (Severity.CRITICAL, True),
    (Severity.WARNING, True),
    (Severity.OBSERVATION, False),
])
def test_is_flagged_maps_critical_and_warning(sev: Severity, expected: bool) -> None:
    assert sev.is_flagged is expected


# --- Finding validators ---


def test_end_line_below_line_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _valid_finding(line=10, end_line=9)


def test_end_line_equal_to_line_is_accepted() -> None:
    f = _valid_finding(line=10, end_line=10)
    assert f.end_line == 10


def test_absolute_file_path_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _valid_finding(file="/abs/path/app.py")


def test_more_than_two_fixes_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _valid_finding(fixes=[FixOption(approach="a"), FixOption(approach="b"), FixOption(approach="c")])


def test_two_fixes_without_exactly_one_recommended_is_rejected() -> None:
    # none recommended
    with pytest.raises(ValidationError):
        _valid_finding(fixes=[FixOption(approach="a"), FixOption(approach="b")])
    # both recommended
    with pytest.raises(ValidationError):
        _valid_finding(fixes=[FixOption(approach="a", recommended=True),
                              FixOption(approach="b", recommended=True)])


def test_two_fixes_with_exactly_one_recommended_is_accepted() -> None:
    f = _valid_finding(fixes=[FixOption(approach="a", recommended=True),
                              FixOption(approach="b")])
    assert len(f.fixes) == 2 and f.fixes[0].recommended is True


def test_single_fix_not_recommended_is_accepted() -> None:
    f = _valid_finding(fixes=[FixOption(approach="a")])
    assert len(f.fixes) == 1 and f.fixes[0].recommended is False


def test_empty_approach_fix_option_is_rejected() -> None:
    with pytest.raises(ValidationError):
        FixOption(approach="")


def test_finding_is_frozen() -> None:
    f = _valid_finding()
    with pytest.raises(ValidationError):
        f.line = 99  # type: ignore[misc]


# --- FindingsReport.exit_code (FR-008 advisory) ---


def test_exit_code_is_zero_on_empty_report() -> None:
    assert FindingsReport().exit_code == 0


def test_exit_code_is_zero_when_all_observations() -> None:
    report = FindingsReport(findings=[_valid_finding(severity=Severity.OBSERVATION)])
    assert report.exit_code == 0


def test_exit_code_is_one_when_any_critical_or_warning_present() -> None:
    report = FindingsReport(findings=[
        _valid_finding(severity=Severity.OBSERVATION),
        _valid_finding(severity=Severity.WARNING),
    ])
    assert report.exit_code == 1


def test_flagged_lists_only_critical_and_warning() -> None:
    report = FindingsReport(findings=[
        _valid_finding(title="obs", severity=Severity.OBSERVATION),
        _valid_finding(title="warn", severity=Severity.WARNING),
    ])
    assert [f.title for f in report.flagged] == ["warn"]


# --- is_flagged must be absent from the JSON schema the model sees ---


def test_is_flagged_absent_from_json_schema() -> None:
    schema = FindingsReport.model_json_schema()
    blob = repr(schema)
    assert "is_flagged" not in blob
    assert "exit_code" not in blob
    assert "flagged" not in blob


# --- enums carry the impl-review dimensions and verdict fields ---


def test_dimension_enum_has_seven_impl_review_dimensions() -> None:
    names = {d.name for d in Dimension}
    assert names == {
        "CORRECTNESS", "SECURITY", "MAINTAINABILITY", "TESTABILITY",
        "PERFORMANCE", "DESIGN", "DOCUMENTATION",
    }


def test_severity_values_match_taxonomy() -> None:
    assert {s.value for s in Severity} == {"critical", "warning", "observation"}
    assert {i.value for i in Impact} == {"low", "medium", "high"}
    assert {c.value for c in Confidence} == {"high", "medium", "low"}
