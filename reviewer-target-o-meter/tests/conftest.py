"""Shared pytest fixtures + the smoke-gate skip rule.

The `smoke` marker (registered in pyproject.toml) selects live-OpenRouter tests.
They are skipped unless the caller opts in via the ``SMOKE=1`` environment variable,
so ``make test`` (``-m "not smoke"``) and a bare ``uv run pytest`` never hit the
network; only ``make llm-test`` (``SMOKE=1 ... -m smoke``) runs them.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip every @pytest.mark.smoke test unless SMOKE=1 is set in the environment."""
    if os.environ.get("SMOKE") == "1":
        return
    skip_smoke = pytest.mark.skip(reason="smoke test — opt in via SMOKE=1 (make llm-test)")
    for item in items:
        if "smoke" in {mark.name for mark in item.iter_markers()}:
            item.add_marker(skip_smoke)
