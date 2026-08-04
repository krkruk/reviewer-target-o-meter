"""Render a FindingsReport as a Markdown PR comment and POST it to GitHub.

A plain function library (not a ``@tool``, not a graph node) called by the CLI
when ``config.post_to_github`` is True. The renderer is pure (no I/O); the
POST uses ``httpx`` (a direct dep as of Phase 4). Posting failures raise so the
caller (the CLI) owns the degrade strategy — never fail CI on a POST (FR-008).

Markdown shape: H1 header + one-line verdict, a findings table (id / severity /
dimension / file:line / title), a collapsible ``<details>`` block with each
finding's detail + fixes, and a trailing advisory disclaimer. Severity renders
as plain uppercase text (no emoji — repo convention).

The ``F{n}`` ids are injected here during rendering (models are unreliable at
sequential ids; see findings.py). The stdout emit path injects them too, so
both surfaces stay consistent.
"""

from __future__ import annotations

from typing import Any

import httpx

from .findings import FindingsReport, Severity

_DISCLAIMER = "_Advisory exit code: {code} — this review never blocks a merge (FR-008)._"
_SEVERITY_LABEL = {
    Severity.CRITICAL: "CRITICAL",
    Severity.WARNING: "WARNING",
    Severity.OBSERVATION: "OBSERVATION",
}


def render_comment(report: FindingsReport, repo: str | None = None) -> str:
    """Render ``report`` as the Markdown body of a PR comment.

    ``repo`` (``"owner/name"``), when provided, turns each ``File:Line`` cell
    into a source link; otherwise the cell is a plain backtick path.
    """
    findings = report.findings
    lines: list[str] = []

    # Header + one-line verdict.
    lines.append("# reviewer-target-o-meter")
    if report.overall_verdict:
        lines.append("")
        lines.append(report.overall_verdict)
    else:
        flagged = len(report.flagged)
        lines.append("")
        lines.append(
            f"{len(findings)} finding(s) ({flagged} flagged)"
            if findings else "0 findings"
        )

    # Findings table.
    if findings:
        lines.append("")
        lines.append("| ID | Severity | Dimension | File:Line | Title |")
        lines.append("|---|---|---|---|---|")
        for i, f in enumerate(findings, start=1):
            fid = f"F{i}"
            cell = _file_cell(f.file, f.line, repo)
            lines.append(
                f"| {fid} | {_SEVERITY_LABEL[f.severity]} | {f.dimension.value} | "
                f"{cell} | {_escape_pipe(f.title)} |"
            )

    # Collapsible details (detail + fixes per finding).
    if findings:
        lines.append("")
        lines.append("<details><summary>Details &amp; fixes</summary>")
        lines.append("")
        for i, f in enumerate(findings, start=1):
            lines.append(f"**F{i} — {_escape_pipe(f.title)}**")
            lines.append("")
            lines.append(f.detail)
            if f.fixes:
                lines.append("")
                for fix in f.fixes:
                    mark = " (recommended)" if fix.recommended else ""
                    lines.append(f"- {fix.approach}{mark}")
            lines.append("")
        lines.append("</details>")

    # Optional style observations (O{n} ids — distinct from blocking F{n}).
    # Advisory-on-advisory: these never affect exit_code / never block the PR.
    if report.optional_findings:
        lines.append("")
        lines.append("<details><summary>Optional style observations (non-blocking)</summary>")
        lines.append("")
        lines.append("| ID | Dimension | File:Line | Title |")
        lines.append("|---|---|---|---|")
        for i, f in enumerate(report.optional_findings, start=1):
            cell = _file_cell(f.file, f.line, repo)
            lines.append(
                f"| O{i} | {f.dimension.value} | {cell} | {_escape_pipe(f.title)} |"
            )
        lines.append("")

    # Advisory disclaimer (always present — FR-008).
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(_DISCLAIMER.format(code=report.exit_code))
    return "\n".join(lines)


def post_comment(
    *,
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
    body: str,
    api_url: str = "https://api.github.com",
    _client: httpx.Client | None = None,
) -> None:
    """POST ``body`` as a comment on PR ``pr_number``.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx so the caller owns the degrade
    strategy. ``_client`` is a test-only seam (inject a ``MockTransport``-backed
    client); production leaves it ``None`` and a fresh client is used per call.
    """
    url = f"{api_url}/repos/{owner}/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if _client is not None:
        _post(_client, url, headers, body)
        return
    # Production path: a single short-lived client. No retry/backoff — the
    # analysis dominates wall-clock; a transient failure degrades to stdout.
    with httpx.Client() as client:
        _post(client, url, headers, body)


def _post(client: httpx.Client, url: str, headers: dict[str, str], body: str) -> None:
    """Issue the POST and raise on HTTP error (caller degrades)."""
    client.post(url, json={"body": body}, headers=headers, timeout=30).raise_for_status()


def _file_cell(file: str, line: int, repo: str | None) -> str:
    """Render the File:Line cell as a plain backtick path.

    v1 omits the source link on purpose: ``/blob/HEAD/`` dereferences the repo's
    default branch on github.com, not the reviewed PR merge commit, so a link
    would point at a version of the file where a PR-added line may not exist.
    The plain backtick is the safe v1 default (plan §4.2); SHA threading is a
    follow-up.
    """
    return f"`{file}:{line}`"


def _escape_pipe(text: str) -> str:
    """Escape ``|`` so it doesn't break the Markdown table cell."""
    return text.replace("|", "\\|")


__all__: list[Any] = ["post_comment", "render_comment"]
