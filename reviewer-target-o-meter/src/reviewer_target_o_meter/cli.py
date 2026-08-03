"""Typer CLI entrypoint — the single console command (FR-001).

Joins the pipeline end-to-end: build Config from env, compute the real diff +
load the real context (F-02), invoke the graph, then either post a Markdown PR
comment (when the PR env vars are present) or print the report JSON to stdout
(FR-007 default), and exit with the advisory code.

Mode switching is env-driven only (no ``--github`` flag): ``PR_NUMBER`` +
``GITHUB_TOKEN`` + ``GITHUB_REPOSITORY`` present → post; else stdout. Posting
failures degrade to stdout + a WARNING (never fail CI — FR-008).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from ._util import warn as _warn
from .config import Config
from .context_loader import load_context
from .diff import compute_diff
from .github import post_comment, render_comment
from .graph import run_review

app = typer.Typer(add_completion=False, help="Reviewer-target-o-meter: analyze a checkout and emit a FindingsReport.")


@app.command()
def review(
    repo_path: Path = typer.Argument(..., help="Path to the checkout to review."),  # noqa: B008
) -> None:
    """Run the reviewer graph over ``repo_path`` and emit the FindingsReport.

    Computes the real diff + loads the real context (F-02). Posts a Markdown PR
    comment when ``PR_NUMBER`` + ``GITHUB_TOKEN`` + ``GITHUB_REPOSITORY`` are set,
    else prints the report JSON to stdout (FR-007). Exits 0 if no findings are
    flagged, else 1 (advisory — FR-008; never blocks a merge).
    """
    config = Config.from_env()  # raises with a clear message if OPENROUTER_API_KEY is missing

    inputs: dict[str, object] = {
        "repo_path": str(repo_path),
        "diff": compute_diff(repo_path, base_ref=config.base_ref),
        "context": load_context(repo_path),
        "plan": None,            # unchanged — real plan discovery is S-01
        "findings": [],
    }
    report = run_review(config, inputs)

    if config.post_to_github:
        # mypy can't narrow Optional fields through the post_to_github property;
        # both are guaranteed non-None here — narrow explicitly so the typed
        # post_comment call passes `uv run mypy src`.
        assert config.pr_number is not None and config.github_token is not None
        try:
            owner, _, repo_name = (config.github_repository or "").partition("/")
            post_comment(
                owner=owner, repo=repo_name, pr_number=config.pr_number,
                token=config.github_token, api_url=config.github_api_url,
                body=render_comment(report, repo=config.github_repository),
            )
        except Exception as exc:  # noqa: BLE001 — degrade: any posting failure must fall back to stdout, never fail CI (FR-008)
            # Log only the exception type, never str(exc) — a broad `except Exception`
            # forwarding the message verbatim risks leaking the Authorization header
            # if a future transport/log change puts it in the exception text
            # (AGENTS.md §d: key read at runtime only, never echoed).
            _warn(f"posting failed; falling back to stdout ({type(exc).__name__})")
            _emit_stdout(report)
            sys.exit(report.exit_code)
        sys.exit(report.exit_code)  # advisory, even after a successful post

    _emit_stdout(report)
    sys.exit(report.exit_code)


def _emit_stdout(report) -> None:
    """Serialize the report as JSON to stdout; inject F{n} ids during emit."""
    payload = report.model_dump(mode="json")
    findings = payload.get("findings", [])
    for i, _finding in enumerate(findings, start=1):
        _finding["id"] = f"F{i}"
    payload["exit_code"] = report.exit_code
    typer.echo(json.dumps(payload, indent=2, default=str))


# Minimal fixture diff (the real fixture lives in tests/fixtures/). Kept inline so
# the CLI is self-contained for the Phase-3 smoke; F-02 replaces this with a real
# diff computed from the checkout.
_FIXTURE_DIFF = """\
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,5 @@
 def query(user_id):
-    sql = "SELECT * FROM users WHERE id = " + user_id
+    # NOTE: user_id is attacker-controlled
+    sql = "SELECT * FROM users WHERE id = " + user_id
+    return run(sql)
"""


def main() -> None:
    """Console-script entrypoint (referenced by [project.scripts])."""
    app()


if __name__ == "__main__":
    main()
