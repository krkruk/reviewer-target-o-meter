"""Load the current change's ``plan.md`` from a 10x-shaped checkout.

A plain function library (not a ``@tool``, not a graph node) called by the CLI —
same shape as ``diff.py`` / ``context_loader.py``. ``load_plan`` turns a
(checkout path, diff) into the plan text the ``checks`` node splices into its
prompt, or ``None`` when no plan is determinable (the prompt's plan-tolerance
handles ``None`` — FR-006).

Discovery is a non-obvious ordered chain (the ordering is load-bearing —
diff-driven wins because "the current change" is what the diff touches;
single-active is the fallback when the diff is ambiguous or doc-only):

1. **Diff-driven:** a path like ``context/changes/<id>/plan.md`` (or
   ``frame.md`` / ``research.md``) appears in the diff → ``<id>`` is the current
   change. Exactly one → use it; two or more → ambiguous → give up (``None``).
2. **Single-active fallback:** exactly one non-archived change dir with a
   ``plan.md`` (``context/archive/`` is excluded). Zero or >1 → ``None``.

Then read ``<repo>/context/changes/<id>/plan.md`` — the authoritative artifact
(``frame.md``/``research.md`` are context, already loaded by ``context_loader``).
``MAX_PLAN_CHARS`` bounds the checks-node prompt; truncation appends a visible
marker so the model is never silently fed a truncation. Missing file / unreadable
→ ``WARNING:`` to stderr + ``None`` (degrade convention, AGENTS.md §b).
"""

from __future__ import annotations

import re
from pathlib import Path

from ._util import warn as _warn

# Module constant (NOT env-driven). The plan is the single highest-signal input,
# so it earns a generous share of the context budget alongside the ~20k-char
# diff cap and ~8k-char context cap (F-02). Sized to leave headroom.
MAX_PLAN_CHARS = 12_000

_TRUNCATION_MARKER = "… [plan truncated: {remaining} more chars]"

# Change-doc filenames whose presence in the diff identifies the current change
# (plan.md is the primary; frame/research also single out the active change).
_CHANGE_DOCS = ("plan.md", "frame.md", "research.md")

# Match "diff --git a/context/changes/<id>/<doc>" — capture <id>. The id is any
# path segment that stops at the next "/" (no nested change ids in the 10x shape).
_CHANGE_PATH_RE = re.compile(
    r"^diff --git a/context/changes/(?P<id>[^/]+)/(?:" + "|".join(_CHANGE_DOCS) + r")\b",
    re.MULTILINE,
)


def load_plan(repo_path: str | Path, diff: str) -> str | None:
    """Return the capped plan text for the current change, or ``None``.

    None-tolerant across the whole chain: an ambiguous diff, zero/many active
    changes, a missing ``plan.md``, or an unreadable file all degrade to ``None``
    (with a ``WARNING:`` on stderr for the actionable misses) — never raise.
    """
    root = Path(repo_path)
    if not root.is_dir():
        _warn(f"plan skipped — not a directory ({root})")
        return None

    change_id = _discover_change_id(root, diff)
    if change_id is None:
        return None

    plan_path = root / "context" / "changes" / change_id / "plan.md"
    try:
        text = plan_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Diff-driven pointed at a change dir with no plan.md, or a single-active
        # dir whose only doc isn't plan.md — actionable enough to warn.
        _warn(f"plan skipped — no plan.md for change '{change_id}'")
        return None
    except OSError as exc:  # permission error, broken symlink, etc.
        _warn(f"plan skipped unreadable file {plan_path} ({exc})")
        return None

    text = text.rstrip()
    if not text:
        return None
    return _cap(text)


def _discover_change_id(repo_path: Path, diff: str) -> str | None:
    """Ordered chain: diff-driven → single-active → None.

    The ordering is load-bearing — see module docstring.
    """
    touched = _changed_change_ids(diff)
    if len(touched) == 1:
        return touched.pop()
    if len(touched) > 1:
        return None  # ambiguous diff → fall through / give up (plan-tolerance)

    active = _active_change_ids(repo_path)
    if len(active) == 1:
        return active[0]
    return None  # 0 or >1 active → no plan (plan-tolerance)


def _changed_change_ids(diff: str) -> set[str]:
    """Parse the diff for change ids whose change-doc is touched."""
    return {m.group("id") for m in _CHANGE_PATH_RE.finditer(diff)}


def _active_change_ids(repo_path: Path) -> list[str]:
    """Non-archived change dirs that carry a plan.md (single-active fallback)."""
    changes_root = repo_path / "context" / "changes"
    if not changes_root.is_dir():
        return []
    active: list[str] = []
    for change_dir in sorted(changes_root.iterdir()):
        if change_dir.is_dir() and (change_dir / "plan.md").is_file():
            active.append(change_dir.name)
    return active


def _cap(text: str) -> str:
    """Truncate ``text`` to ``MAX_PLAN_CHARS`` with a visible marker."""
    if len(text) <= MAX_PLAN_CHARS:
        return text
    remaining = len(text) - MAX_PLAN_CHARS
    return text[:MAX_PLAN_CHARS] + _TRUNCATION_MARKER.format(remaining=remaining)


__all__ = ["MAX_PLAN_CHARS", "load_plan"]
