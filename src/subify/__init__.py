"""Subify command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from .check import CheckAborted, CheckService
from .check import parse_args as parse_check_args
from .config import ServerConfig, add_server_options, server_from_args
from .convert import SpotifyPlaylistConverter
from .convert import parse_args as parse_convert_args
from .find import FindAborted, FindService
from .find import parse_args as parse_find_args
from .generate import SockseekConfig, SockseekGenerator, WishlistGenerator
from .generate import parse_args as parse_generate_args
from .subsonic import SubsonicClient, SubsonicClientError
from .sync import SyncService
from .sync import parse_args as parse_sync_args

USAGE = """Usage: subify <COMMAND> [OPTIONS]

Commands:
  test  test connectivity and credentials with a Subsonic server
  check check a playlist CSV against a Subsonic server
  convert convert a Spotify CSV export to a playlist CSV
  generate create Sockseek or wishlist files from check results
  sync  create or update a Subsonic playlist from a playlist CSV
  find  interactively save a playlist-to-Subsonic track correspondence
"""

ClientFactory = Callable[[ServerConfig], SubsonicClient]


class SubifyApp:
    """Dispatch commands implemented by the active package."""

    def __init__(
        self,
        argv: list[str] | None = None,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.argv = argv if argv is not None else sys.argv[1:]
        self.client_factory = client_factory or self._make_client

    @staticmethod
    def _make_client(server: ServerConfig) -> SubsonicClient:
        return SubsonicClient(server)

    def cmd_test(self, argv: list[str]) -> int:
        parser = argparse.ArgumentParser(
            prog="subify test",
            description="Test Subsonic connectivity and credentials.",
        )
        add_server_options(parser)
        server = server_from_args(parser, parser.parse_args(argv))
        print(f"Testing connection to {server.base_url}...")
        try:
            response = self.client_factory(server).ping()
        except SubsonicClientError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        print(
            f"OK: connected as '{server.username}', "
            f"Subsonic API version {response.get('version', '?')}"
        )
        return 0

    def cmd_check(self, argv: list[str]) -> int:
        config = parse_check_args(argv)
        try:
            service = CheckService(config, self.client_factory(config.server))
            if config.list_libraries:
                service.list_libraries()
                return 0
            results = service.run()
        except ValueError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 2
        except SubsonicClientError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        except CheckAborted:
            print("Check stopped; partial results were saved.")
            return 130
        found = sum(result.song is not None for result in results)
        print(
            f"Checked {len(results)} track(s): {found} found. "
            f"Results written to {config.result}"
        )
        return 0

    @staticmethod
    def cmd_convert(argv: list[str]) -> int:
        config = parse_convert_args(argv)
        try:
            count = SpotifyPlaylistConverter(config).run()
        except ValueError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 2
        print(f"Converted {count} track(s) to {config.output_path}")
        return 0

    @staticmethod
    def cmd_generate(argv: list[str]) -> int:
        config = parse_generate_args(argv)
        try:
            if isinstance(config, SockseekConfig):
                count = SockseekGenerator(config).run()
                label = "Sockseek track(s)"
            else:
                count = WishlistGenerator(config).run()
                label = "wishlist track(s)"
        except ValueError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 2
        print(f"Generated {count} {label} in {config.output_path}")
        return 0

    def cmd_sync(self, argv: list[str]) -> int:
        config = parse_sync_args(argv)
        try:
            results = SyncService(config, self.client_factory(config.server)).run()
        except ValueError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 2
        except SubsonicClientError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        except CheckAborted:
            print("Sync stopped; cache entries were saved.")
            return 130
        if not config.list_libraries:
            print(
                f"Synced {sum(result.song is not None for result in results)} track(s)."
            )
        return 0

    def cmd_find(self, argv: list[str]) -> int:
        config = parse_find_args(argv)
        try:
            track, song = FindService(config, self.client_factory(config.server)).run()
        except ValueError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 2
        except SubsonicClientError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        except FindAborted:
            print("Find cancelled; no correspondence was saved.")
            return 130
        print(f"Saved: {track.title} -> {song.title} (id={song.id})")
        return 0

    def run(self) -> int:
        if not self.argv:
            print(USAGE, file=sys.stderr)
            return 2
        command, *args = self.argv
        if command == "test":
            return self.cmd_test(args)
        if command == "check":
            return self.cmd_check(args)
        if command == "convert":
            return self.cmd_convert(args)
        if command == "generate":
            return self.cmd_generate(args)
        if command == "sync":
            return self.cmd_sync(args)
        if command == "find":
            return self.cmd_find(args)
        if command in {"help", "-h", "--help"}:
            print(USAGE)
            return 0
        print(f"Unknown command: {command}", file=sys.stderr)
        return 2


def main() -> int:
    """Run the CLI and return its process exit code."""
    return SubifyApp().run()
