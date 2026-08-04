"""Shared internal helpers.

Owns the single logging channel (``configure_logging`` / ``get_logger``) that the
whole pipeline writes its INFO breadcrumbs through, plus the legacy ``warn``
degrade convention now routed through that same channel.

Historically this module held only ``_warn`` — a one-line ``WARNING: ...`` to
stderr, used by every module that follows the degrade convention (AGENTS.md §b):
recoverable failures write that line and return a safe fallback rather than
raising out of the pipeline. ``warn`` is now a thin wrapper over the package
logger so all output (existing warnings + future INFO breadcrumbs) flows through
one channel with one format — and the literal ``WARNING:`` substring stays intact
(the format's first token is the level name), keeping the degrade assertions in
``test_cli.py`` green.

Logging is bound to the runtime ``sys.stderr`` (not import time) so typer's
``CliRunner`` can capture it under tests, and ``configure_logging`` is idempotent
across repeated invokes (the package logger persists across a test session; a
missing guard would append a duplicate handler per invoke and double every line).
"""

from __future__ import annotations

import logging
import sys

_LOGGER_NAME = "reviewer_target_o_meter"
_FORMAT = "%(levelname)s: %(message)s"


def configure_logging(level: str) -> None:
    """Configure the package logger with exactly one stderr handler (idempotent).

    Clears any handlers left by a prior invoke, then adds a fresh one bound to
    the CURRENT ``sys.stderr``. Two reasons this is clear-then-add rather than
    a "configure once" flag:

    - **No duplicate lines.** The package logger persists for the whole process
      (and across a pytest session); re-adding without clearing would double
      every log line on a second invoke.
    - **Live stderr binding.** typer's ``CliRunner`` replaces ``sys.stderr``
      around each invoke; a handler bound to the first invoke's stderr would go
      stale (and miss capture) on later invokes. Clear-then-add re-binds it to
      the live stream every call.

    The level is re-applied each call so a caller can escalate/de-escalate
    verbosity between invokes. This MUST run at command runtime (inside
    ``review()``), not at import time, for the stderr binding above to hold.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(_coerce_level(level))
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a per-module logger (a child of the configured package logger).

    Call as ``get_logger(__name__)``; the result inherits the single handler +
    effective level set on the package logger by ``configure_logging``.
    """
    return logging.getLogger(name)


def warn(message: str) -> None:
    """Emit a ``WARNING: <message>`` through the package logger (degrade convention).

    Output stays ``WARNING: <message>`` — the format's first token is the level
    name, so the literal ``WARNING`` substring asserted by ``test_cli.py``'s
    degrade cases is preserved.
    """
    get_logger(f"{_LOGGER_NAME}._util").warning(message)


def _coerce_level(level: str) -> int:
    """Map a level name to a ``logging`` int, falling back to INFO on unknowns.

    Pure (no logging side effects) — the caller (``configure_logging``) owns the
    logger state. Unknown values degrade to INFO rather than raising, matching
    the forgiving env-config convention and never crashing the pipeline over a
    typo in ``LOG_LEVEL``; the miss is flagged separately in ``Config.from_env``.
    """
    upper = level.upper()
    numeric = logging.getLevelName(upper)
    if isinstance(numeric, int) and logging.DEBUG <= numeric <= logging.CRITICAL:
        return numeric
    return logging.INFO


__all__ = ["configure_logging", "get_logger", "warn"]
