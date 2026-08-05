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
import logging
import os
import sys
from pathlib import Path
from typing import Any

import typer

from ._util import configure_logging, get_logger, redacted_env
from ._util import warn as _warn
from .config import Config
from .context_loader import load_context
from .diff import compute_diff
from .github import post_comment, render_comment
from .graph import run_review
from .plan_loader import load_plan

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
    # Bind logging to the runtime sys.stderr before any pipeline step runs, so
    # breadcrumbs surface under typer's CliRunner capture in tests and stream to
    # the GHA step log in PROD. Idempotent across invokes.
    configure_logging(config.log_level)
    log = get_logger(__name__)

    # DEBUG-only dump of the runtime env (secret-named vars redacted by pattern)
    # so a CI step log shows exactly which inputs the tool saw — clearing up "is X
    # set?" without ever echoing a token (AGENTS.md §d). Off at default INFO.
    if log.isEnabledFor(logging.DEBUG):
        log.debug("env dump (secret-named vars redacted): %s", redacted_env())

    mode = "post" if config.post_to_github else "stdout"
    log.info(
        "review start — mode=%s model=%s base_ref_override=%s repo=%s",
        mode, config.model, config.base_ref, config.github_repository,
    )
    # DEBUG-only directory map of the reviewed checkout (2 levels deep). Makes
    # environment mismatches (wrong checkout, missing files, CWD surprises)
    # diagnosable from the CI step log without SSH. Off at default INFO.
    _log_dir_tree(repo_path, log)

    # Compute the diff once and feed it to both plan discovery and the graph —
    # don't diff twice. load_plan is None-tolerant (no plan discoverable → the
    # prompt's plan-tolerance kicks in; FR-006).
    diff = compute_diff(repo_path, base_ref=config.base_ref)
    # The configured base (may differ from the resolved base the in-module
    # diff breadcrumb reports when the override is None and the heuristic chain
    # picks origin/main). Final size is CLI-level; truncation is in-module.
    log.info("diff computed — configured_base=%s chars=%d", config.base_ref, len(diff))
    context = load_context(repo_path)
    plan = load_plan(repo_path, diff)
    # The richer context/plan breadcrumbs (chunk count, change-id-or-reason) are
    # emitted in-module; no need to echo a thinner CLI-level duplicate here.
    inputs: dict[str, object] = {
        "repo_path": str(repo_path),
        "diff": diff,
        "context": context,
        "plan": plan,
        "findings": [],
    }
    report = run_review(config, inputs)
    log.info(
        "review complete — findings=%d flagged=%d exit_code=%d",
        len(report.findings), len(report.flagged), report.exit_code,
    )

    # Markdown preview: the exact render_comment() payload that is (or would be)
    # posted, echoed to stderr once before the post-vs-stdout branch. It is NOT a
    # log line (so LOG_LEVEL never suppresses it) and carries no per-line level
    # prefix (clean, copy-pasteable Markdown). A pure, cheap extra render.
    typer.echo(render_comment(report, repo=config.github_repository), err=True)

    if config.post_to_github:
        # mypy can't narrow Optional fields through the post_to_github property;
        # both are guaranteed non-None here — narrow explicitly so the typed
        # post_comment call passes `uv run mypy src`.
        assert config.pr_number is not None and config.github_token is not None
        owner, _, repo_name = (config.github_repository or "").partition("/")
        log.info("post attempt — %s#%d", config.github_repository, config.pr_number)
        try:
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
            log.info("post failed — degraded to stdout (%s)", type(exc).__name__)
            _emit_stdout(report)
            sys.exit(report.exit_code)
        log.info("post success — comment posted to %s#%d", config.github_repository, config.pr_number)
        sys.exit(report.exit_code)  # advisory, even after a successful post

    _emit_stdout(report)
    sys.exit(report.exit_code)


def _emit_stdout(report) -> None:
    """Serialize the report as JSON to stdout; inject F{n}/O{n} ids during emit."""
    payload = report.model_dump(mode="json")
    findings = payload.get("findings", [])
    for i, _finding in enumerate(findings, start=1):
        _finding["id"] = f"F{i}"
    # Optional style observations get a separate O{n} counter (distinct from F{n}).
    optional = payload.get("optional_findings", [])
    for i, _finding in enumerate(optional, start=1):
        _finding["id"] = f"O{i}"
    payload["exit_code"] = report.exit_code
    typer.echo(json.dumps(payload, indent=2, default=str))


def _log_dir_tree(repo_path: Path, log: Any) -> None:
    """DEBUG-only: log the reviewed checkout's directory tree (2 levels deep).

    Mirrors `find {repo_path} -type d -maxdepth 2` in-process (no shell-out, so
    it works on every runner). Makes environment mismatches diagnosable from the
    CI step log: a wrong checkout, a missing src/ tree, or a CWD surprise all
    become visible without SSH. Best-effort, never raises — a diagnosis probe
    must not break the pipeline.
    """
    if not log.isEnabledFor(logging.DEBUG):
        return
    try:
        root = Path(repo_path)
        if not root.is_dir():
            log.debug("dir-tree: repo_path=%s is not a directory", repo_path)
            return
        log.debug("dir-tree (maxdepth 2) for %s:", repo_path)
        for depth, (dirpath, dirnames, _filenames) in enumerate(
            _walk_limited(root, max_depth=2)
        ):
            rel = Path(dirpath).relative_to(root)
            log.debug("  %s%s/ (%d subdirs)", "  " * depth, rel, len(dirnames))
    except Exception as exc:  # noqa: BLE001 — diagnosis probe must never break the pipeline
        log.debug("dir-tree failed: %s: %s", type(exc).__name__, exc)


def _walk_limited(root: Path, max_depth: int):
    """os.walk yielding only up to ``max_depth`` levels (generator)."""
    root_str = str(root)
    for dirpath, dirnames, filenames in os.walk(root_str):
        depth = Path(dirpath).relative_to(root_str).parts
        if len(depth) > max_depth:
            dirnames[:] = []  # don't descend further
            continue
        yield dirpath, dirnames, filenames


def main() -> None:
    """Console-script entrypoint (referenced by [project.scripts])."""
    app()


if __name__ == "__main__":
    main()
