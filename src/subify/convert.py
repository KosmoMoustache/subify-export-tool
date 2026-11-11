"""Convert a Spotify CSV to a Tracklist compatible with Subify"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_INPUT = Path("d/Liked_Songs.csv")
DEFAULT_OUTPUT = Path("d/playlist.csv")


@dataclass(frozen=True)
class ConvertConfig:
    """Source and destination of a Spotify playlist conversion."""

    input_path: Path
    output_path: Path


class SpotifyPlaylistConverter:
    """Convert a Spotify CSV export to Subify's compact playlist format."""

    _SOURCE_COLUMNS = {
        "isrc": "isrc",
        "title": "track name",
        "album": "album name",
        "artist": "artist name(s)",
        "duration_ms": "duration (ms)",
    }
    _OUTPUT_COLUMNS = ("isrc", "title", "album", "artist", "duration_ms")

    def __init__(self, config: ConvertConfig) -> None:
        self.config = config

    def run(self) -> int:
        """Convert the source CSV and return the number of written tracks."""
        rows = self._read_rows()
        self._write_rows(rows)
        return len(rows)

    def _read_rows(self) -> list[dict[str, str]]:
        try:
            source = self.config.input_path.open(encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise ValueError(
                f"Could not read Spotify playlist {self.config.input_path}: {exc}"
            ) from exc
        with source:
            reader = csv.DictReader(source)
            headers = {
                header.casefold().strip(): header for header in reader.fieldnames or []
            }
            missing = set(self._SOURCE_COLUMNS.values()) - headers.keys()
            if missing:
                raise ValueError(
                    "Spotify playlist is missing column(s): "
                    + ", ".join(sorted(missing))
                )
            rows = []
            for row in reader:
                converted = {
                    output: (row.get(headers[source]) or "").strip()
                    for output, source in self._SOURCE_COLUMNS.items()
                }
                if converted["title"]:
                    rows.append(converted)
        return rows

    def _write_rows(self, rows: list[dict[str, str]]) -> None:
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config.output_path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=self._OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)


def parse_args(argv: list[str]) -> ConvertConfig:
    """Parse the active convert command options."""
    parser = argparse.ArgumentParser(prog="subify convert", description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Spotify CSV (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Tracklist CSV (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)
    return ConvertConfig(args.input, args.output)
