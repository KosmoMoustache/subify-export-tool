"""Terminal-output formatting helpers."""

from __future__ import annotations

import os
import re
import sys

_CYAN = "\x1b[36m"
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_RESET = "\x1b[0m"
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def verbose(message: str) -> str:
    """Format a verbose message, highlighting its prefix in interactive terminals."""
    prefix = "[verbose]"
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
        prefix = f"{_CYAN}{prefix}{_RESET}"
    return f"{prefix} {message}"


def track_label(title: str, artist: str, album: str) -> str:
    """Render track fields with stable colours instead of punctuation separators."""
    fields = ((title, _CYAN), (artist, _GREEN), (album, _YELLOW))
    if not sys.stdout.isatty() or "NO_COLOR" in os.environ:
        return " ".join(value for value, _color in fields if value)
    return " ".join(f"{color}{value}{_RESET}" for value, color in fields if value)


def strip_ansi(value: str) -> str:
    """Remove terminal escape sequences before writing a plain-text file."""
    return _ANSI_ESCAPE.sub("", value)
