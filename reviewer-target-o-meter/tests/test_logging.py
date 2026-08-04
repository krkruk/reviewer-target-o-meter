"""Unit tests for the logging channel (Phase 1).

Pins the contract that Phases 2-3 depend on: idempotency across repeated
``configure_logging`` calls (no duplicate handlers / duplicate log lines), the
``WARNING:`` format token (load-bearing for ``test_cli.py``'s degrade
assertions — the format's first token must be the level name), and per-module
logger naming (children inherit the single package handler).
"""

from __future__ import annotations

import logging

import pytest

from reviewer_target_o_meter._util import configure_logging, get_logger, warn

_PACKAGE_LOGGER = "reviewer_target_o_meter"


@pytest.fixture(autouse=True)
def _reset_package_logger() -> None:
    """Reset the package logger between tests so idempotency assertions are precise.

    The package logger persists across the test session; without this reset, the
    handler left by one test would make another test's single-handler assertion
    ambiguous. Save/restore keeps each test hermetic without weakening the real
    idempotency (clear-then-add) behavior.
    """
    logger = logging.getLogger(_PACKAGE_LOGGER)
    saved_handlers = logger.handlers[:]
    saved_level = logger.level
    saved_propagate = logger.propagate
    saved_flag = getattr(logger, "_rtom_configured", None)
    logger.handlers.clear()
    if hasattr(logger, "_rtom_configured"):
        del logger._rtom_configured
    yield
    logger.handlers = saved_handlers
    logger.setLevel(saved_level)
    logger.propagate = saved_propagate
    if saved_flag is not None:
        logger._rtom_configured = saved_flag
    elif hasattr(logger, "_rtom_configured"):
        del logger._rtom_configured


def test_configure_logging_is_idempotent() -> None:
    """Calling configure_logging twice leaves exactly one StreamHandler (no dup lines)."""
    configure_logging("INFO")
    configure_logging("INFO")
    logger = logging.getLogger(_PACKAGE_LOGGER)
    stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) == 1, f"expected 1 handler, got {stream_handlers!r}"


def test_configure_logging_binds_stderr_handler(capsys: pytest.CaptureFixture[str]) -> None:
    """The single handler writes to the runtime sys.stderr (so CliRunner can capture it)."""
    configure_logging("INFO")
    logging.getLogger(_PACKAGE_LOGGER).info("trace me")
    assert "trace me" in capsys.readouterr().err


def test_warn_emits_warning_token(capsys: pytest.CaptureFixture[str]) -> None:
    """warn() routes through the logger and emits a `WARNING: <msg>` line on stderr.

    The `WARNING` substring is load-bearing — ``test_cli.py``'s degrade
    assertions check for it, and the format's first token must be the level
    name to preserve it.
    """
    configure_logging("INFO")
    warn("diff skipped — degrade")
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "diff skipped — degrade" in captured.err


def test_get_logger_returns_child_inheriting_package_handler(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """get_logger(name) returns a child whose output flows through the package handler."""
    configure_logging("INFO")
    child = get_logger(f"{_PACKAGE_LOGGER}.diff")
    assert child.name == f"{_PACKAGE_LOGGER}.diff"
    # A child at NOTSET inherits the package logger's effective level.
    assert child.getEffectiveLevel() == logging.INFO
    child.info("child breadcrumb")
    assert "child breadcrumb" in capsys.readouterr().err


def test_log_level_controls_what_emits(capsys: pytest.CaptureFixture[str]) -> None:
    """At WARNING, INFO lines are suppressed; at INFO they emit."""
    configure_logging("WARNING")
    logging.getLogger(_PACKAGE_LOGGER).info("should be hidden")
    assert "should be hidden" not in capsys.readouterr().err

    configure_logging("INFO")
    logging.getLogger(_PACKAGE_LOGGER).info("should be visible")
    assert "should be visible" in capsys.readouterr().err
