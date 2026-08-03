"""Load a repo's review context (AGENTS.md + foundation + current change docs).

A plain function library (not a ``@tool``, not a graph node) called by the CLI.
Builds the ``context`` string the ``checks`` node splices into its prompt.

None-tolerant: missing files contribute nothing; total absence returns ``None``
so the existing ``context_load`` node sets ``context_present=False``, preserving
FR-010 graceful degradation. Missing-dir / unreadable-file failures are swallowed
with a ``WARNING:`` to stderr (degrade convention).

Scope, in priority order (highest signal first), concatenated with ``---``:

1. ``<repo>/AGENTS.md`` (root).
2. ``<repo>/context/foundation/*.md`` (prd, roadmap, tech-stack, lessons...).
3. ``<repo>/context/changes/*/{plan,frame,research}.md`` for each NON-archived
   change dir (``context/archive/`` is excluded).

The ~8k-char cap bounds the ``checks`` node's prompt size; truncation appends a
visible marker so the model is never silently fed a truncation.
"""

from __future__ import annotations

from pathlib import Path

from ._util import warn as _warn

# Module constant (NOT env-driven in v1). Bounds the checks-node prompt.
MAX_CONTEXT_CHARS = 8_000

_SEPARATOR = "\n---\n"
_TRUNCATION_MARKER = "… [context truncated: {remaining} more chars]"

# Change-doc filenames we treat as reviewable context, in a stable read order.
_CHANGE_DOCS = ("plan.md", "frame.md", "research.md")


def load_context(repo_path: str | Path) -> str | None:
    """Return the capped review-context string, or ``None`` if nothing loaded.

    None-tolerant across the whole scope: a missing checkout, a missing
    ``context/`` tree, or unreadable files degrade to a smaller result (or
    ``None``) with a ``WARNING:`` on stderr — never raise.
    """
    root = Path(repo_path)
    if not root.is_dir():
        _warn(f"context skipped — not a directory ({root})")
        return None

    chunks: list[str] = []

    # 1. AGENTS.md (root) — highest signal.
    _append_file(chunks, root / "AGENTS.md")

    # 2. context/foundation/*.md (stable order for reproducible prompts).
    foundation = sorted((root / "context" / "foundation").glob("*.md"))
    for doc in foundation:
        _append_file(chunks, doc)

    # 3. context/changes/*/{plan,frame,research}.md — exclude context/archive/.
    changes_root = root / "context" / "changes"
    if changes_root.is_dir():
        for change_dir in sorted(changes_root.iterdir()):
            if not change_dir.is_dir():
                continue
            for name in _CHANGE_DOCS:
                _append_file(chunks, change_dir / name)

    if not chunks:
        return None

    return _cap(_SEPARATOR.join(chunks))


def _append_file(chunks: list[str], path: Path) -> None:
    """Read ``path`` and append its text to ``chunks``; degrade on any I/O error."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return  # not every repo has every doc — fine
    except OSError as exc:  # permission error, broken symlink, etc.
        _warn(f"context skipped unreadable file {path} ({exc})")
        return
    if text:
        chunks.append(text.rstrip())


def _cap(text: str) -> str:
    """Truncate ``text`` to ``MAX_CONTEXT_CHARS`` with a visible marker."""
    if len(text) <= MAX_CONTEXT_CHARS:
        return text
    remaining = len(text) - MAX_CONTEXT_CHARS
    return text[:MAX_CONTEXT_CHARS] + _TRUNCATION_MARKER.format(remaining=remaining)


__all__ = ["MAX_CONTEXT_CHARS", "load_context"]
