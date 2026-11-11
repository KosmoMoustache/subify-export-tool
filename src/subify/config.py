"""Configuration shared by the active Subify commands."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = "creds.txt"
DEFAULT_DELAY = 0.15
DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class ServerConfig:
    """Connection settings for a Subsonic-compatible server."""

    base_url: str
    username: str
    password: str
    timeout: float = DEFAULT_TIMEOUT
    delay: float = DEFAULT_DELAY
    verbose: int = 0
    config_path: Path = Path(DEFAULT_CONFIG)


def load_credentials_file(path: Path) -> dict[str, str]:
    """Load URL, username and password from a local ``key=value`` file."""
    credentials: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", ";")) or "=" not in line:
                continue
            key, value = (part.strip() for part in line.split("=", maxsplit=1))
            key = key.removeprefix("NAVIDROME_").lower()
            if key in {"url", "username", "password"} and value:
                credentials[key] = value.strip("\"'")
    except OSError:
        pass
    return credentials


def add_server_options(parser: argparse.ArgumentParser) -> None:
    """Add connection options accepted by commands that contact the server."""
    parser.add_argument(
        "--config", type=Path, default=Path(DEFAULT_CONFIG), help="Path to config file"
    )
    parser.add_argument("--url", help="Subsonic server URL")
    parser.add_argument("--username", help="Subsonic server username")
    parser.add_argument("--password", help="Subsonic server password")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help=(
            "show match decisions; repeat for HTTP requests (-vv) "
            "and API responses (-vvv)"
        ),
    )


def server_from_args(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> ServerConfig:
    """Resolve credentials with CLI options taking precedence over local config."""
    file_credentials = load_credentials_file(args.config)
    base_url = (
        args.url or file_credentials.get("url") or os.getenv("NAVIDROME_URL", "")
    ).rstrip("/")
    username = (
        args.username
        or file_credentials.get("username")
        or os.getenv("NAVIDROME_USER", "")
    )
    password = (
        args.password
        or file_credentials.get("password")
        or os.getenv("NAVIDROME_PASSWORD", "")
    )
    if not username or not password:
        parser.error("username and password are required")
    if not base_url:
        parser.error("a Subsonic server URL is required")
    return ServerConfig(
        base_url,
        username,
        password,
        args.timeout,
        args.delay,
        args.verbose,
        args.config,
    )
