"""reviewer-target-o-meter package — the console entrypoint delegates to cli.app."""

from .cli import app, main

__all__ = ["app", "main"]
