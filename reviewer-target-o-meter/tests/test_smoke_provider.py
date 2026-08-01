"""Live OpenRouter smoke test — F-01's central de-risking artifact.

Proves the free model emits a valid *full-shape* ``FindingsReport`` through
``with_structured_output(..., method="json_schema", strict=True)`` against the real
free tier. System-level (integration) check in V-model terms: it exercises the real
provider client + network + model, not a mock.

Opt-in only: skipped unless ``SMOKE=1`` (see conftest.py + the `smoke` marker).
Run via ``make llm-test``; never in default CI.
"""

from __future__ import annotations

import pytest

from reviewer_target_o_meter.config import Config
from reviewer_target_o_meter.findings import FindingsReport
from reviewer_target_o_meter.provider import build_structured_llm, to_report

pytestmark = pytest.mark.smoke

# A tiny, realistic review payload — a one-line SQL string concatenation. Minimal
# context, enough for the model to populate the full finding shape.
_TINY_DIFF = """\
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,5 @@
 def query(user_id):
-    sql = "SELECT * FROM users WHERE id = " + user_id
+    # NOTE: user_id is attacker-controlled
+    sql = "SELECT * FROM users WHERE id = " + user_id
+    return run(sql)
"""

_REVIEW_PROMPT = (
    "You are a non-interactive code reviewer. Read the diff and emit a FindingsReport "
    "(Pydantic schema). For each problem, set severity (critical/warning/observation), "
    "impact (low/medium/high), dimension (the seven impl-review dimensions), a file/line "
    "anchor (repo-relative path, 1-based line), a <=120-char title, a rationale in detail, "
    "and up to 2 FixOptions (a one-sentence fix DIRECTION, never a patch; mark exactly one "
    "recommended if there are two). Do not edit, post, or ask questions.\n\n"
    f"Diff:\n{_TINY_DIFF}"
)


def test_free_model_emits_valid_full_shape_report() -> None:
    """The free model must return a validated, non-empty FindingsReport over OpenRouter."""
    config = Config.from_env()  # raises if OPENROUTER_API_KEY unset — required for smoke
    structured = build_structured_llm(config)

    result = structured.invoke([{"role": "user", "content": _REVIEW_PROMPT}])
    report = to_report(result)

    assert isinstance(report, FindingsReport)
    assert len(report.findings) >= 1, f"expected >=1 finding, got: {report!r}"
    # Each finding survives host-side re-validation and carries the anchor + shape.
    for f in report.findings:
        assert f.file and not f.file.startswith("/"), f"bad file anchor: {f.file}"
        assert f.line >= 1
        assert f.severity and f.impact and f.dimension
        assert f.title and f.detail
    # The advisory exit code is computed purely from flagged severities.
    assert report.exit_code in (0, 1)
