"""Typer CLI entrypoint — the single console command (FR-001).

Joins the pipeline end-to-end: build Config from env, assemble the fixture inputs
(F-01 *accepts* diff/context/plan; the real pipeline is F-02), invoke the graph,
print the report JSON to stdout (FR-007 default), and exit with the advisory code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from .config import Config
from .context_loader import load_context
from .diff import compute_diff
from .graph import run_review

app = typer.Typer(add_completion=False, help="Reviewer-target-o-meter: analyze a checkout and emit a FindingsReport.")


@app.command()
def review(
    repo_path: Path = typer.Argument(..., help="Path to the checkout to review."),  # noqa: B008
) -> None:
    """Run the reviewer graph over ``repo_path`` and print the FindingsReport JSON.

    F-01 accepts the diff/context/plan inputs (real discovery is F-02). Exits 0 if
    no findings are flagged, else 1 (advisory — FR-008; never blocks a merge).
    """
    config = Config.from_env()  # raises with a clear message if OPENROUTER_API_KEY is missing

    # F-02: compute the real diff + load the real review context from the
    # checkout. base_ref is None here (heuristic-only) until Phase 5 wires
    # config.base_ref through; the inline fixture diff is retained for system
    # tests (reached via monkeypatching compute_diff).
    inputs: dict[str, object] = {
        "repo_path": str(repo_path),
        "diff": compute_diff(repo_path, base_ref=None),
        "context": load_context(repo_path),
        "plan": None,
        "findings": [],
    }
    report = run_review(config, inputs)

    # Serialize: inject F{n} ids during emit; exit_code is advisory.
    payload = report.model_dump(mode="json")
    findings = payload.get("findings", [])
    for i, _finding in enumerate(findings, start=1):
        _finding["id"] = f"F{i}"
    payload["exit_code"] = report.exit_code
    typer.echo(json.dumps(payload, indent=2, default=str))
    sys.exit(report.exit_code)


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
