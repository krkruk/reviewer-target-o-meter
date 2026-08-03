"""Unit tests for the GitHub posting module (Phase 4, S-02 half).

Covers the Markdown renderer (pure) and the httpx POST (offline, via
``httpx.MockTransport`` so no network is touched). The live POST is exercised
only via the Phase 5/6 manual flow against a real PR.
"""

from __future__ import annotations

import httpx
import pytest

from reviewer_target_o_meter.findings import (
    Dimension,
    Finding,
    FindingsReport,
    Impact,
    Severity,
)
from reviewer_target_o_meter.github import post_comment, render_comment


def _flagged_report() -> FindingsReport:
    return FindingsReport(
        findings=[
            Finding(
                file="src/app.py", line=3, severity=Severity.CRITICAL, impact=Impact.HIGH,
                dimension=Dimension.SECURITY, title="SQL injection via concat",
                detail="user_id is concatenated into the SQL string, enabling injection.",
            ),
            Finding(
                file="src/app.py", line=10, severity=Severity.WARNING, impact=Impact.MEDIUM,
                dimension=Dimension.MAINTAINABILITY, title="Bare except swallows errors",
                detail="A bare except hides all errors, including KeyboardInterrupt.",
            ),
        ]
    )


# --- render_comment: shape ----------------------------------------------------


def test_render_comment_has_header_table_details_and_disclaimer() -> None:
    md = render_comment(_flagged_report())

    # H1 header naming the tool.
    assert md.lstrip().startswith("# "), "expected an H1 header"
    assert "reviewer-target-o-meter" in md.lower()

    # Findings table: one row per finding, with F{n} ids injected.
    assert "F1" in md and "F2" in md
    assert "src/app.py:3" in md
    assert "src/app.py:10" in md
    # Severity labels are uppercase plain text (no emoji per repo convention).
    assert "CRITICAL" in md and "WARNING" in md

    # Collapsible details block with each finding's detail + fixes.
    assert "<details>" in md and "</details>" in md
    assert "enabling injection" in md  # the CRITICAL detail body

    # Advisory disclaimer (FR-008) is always present.
    assert "Advisory exit code" in md
    assert "never blocks a merge" in md


def test_render_comment_empty_report_shows_zero_findings_verdict() -> None:
    md = render_comment(FindingsReport(findings=[]))

    assert "0 findings" in md
    # The disclaimer is still emitted (advisory exit 0).
    assert "Advisory exit code" in md
    # No F{n} rows when there are no findings.
    assert "F1" not in md


def test_render_comment_injects_sequential_finding_ids() -> None:
    md = render_comment(_flagged_report())
    # The ids appear in order within the table.
    assert md.index("F1") < md.index("F2")


def test_render_comment_file_cell_uses_backticks_when_repo_unknown() -> None:
    md = render_comment(_flagged_report(), repo=None)
    # No repo → plain backtick path, no Markdown link.
    assert "`src/app.py:3`" in md
    assert "https://github.com/" not in md


def test_render_comment_file_cell_links_when_repo_known() -> None:
    md = render_comment(_flagged_report(), repo="owner/repo")
    # A blob link to the source line is rendered when the repo is known.
    assert "https://github.com/owner/repo/blob/" in md
    assert "#L3" in md


# --- post_comment: offline via MockTransport ----------------------------------


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_post_comment_201_does_not_raise_and_hits_url_headers_body() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.read().decode()
        return httpx.Response(201, json={"id": 42})

    transport = _mock_transport(handler)
    # Inject the transport via a client bound to post_comment's call shape.
    with httpx.Client(transport=transport) as client:
        _post_with_client(
            client,
            owner="krkruk", repo="target-o-meter", pr_number=7,
            token="tok", body="## reviewer-target-o-meter\n...",
        )

    assert captured["url"].endswith("/repos/krkruk/target-o-meter/issues/7/comments")
    assert captured["headers"]["authorization"] == "Bearer tok"
    assert captured["headers"]["accept"] == "application/vnd.github+json"
    assert "reviewer-target-o-meter" in captured["body"]


def test_post_comment_404_raises_http_status_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    transport = _mock_transport(handler)
    with httpx.Client(transport=transport) as client, pytest.raises(httpx.HTTPStatusError):
        _post_with_client(
            client,
            owner="o", repo="r", pr_number=1, token="tok", body="x",
        )


# --- helper: call post_comment with an injected client ------------------------
# post_comment builds its own client by default; for tests we pass one in via
# the optional ``_client`` keyword (test-only seam, prefixed to signal that).


def _post_with_client(client: httpx.Client, **kw) -> None:
    post_comment(_client=client, api_url="https://api.github.com", **kw)
