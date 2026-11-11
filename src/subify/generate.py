"""Generators based on the CSV written by ``subify check``."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_INPUT = Path("d/check_result.csv")
DEFAULT_SOCKSEEK_OUTPUT = Path("d/sockseek_list.csv")
DEFAULT_WISHLIST_OUTPUT = Path("d/wishlist.txt")
RESULT_FIELDS = ("title", "album", "artist", "status")
DEFAULT_STATUSES = ("MISSING", "FORMAT-MISMATCH")
VALID_STATUSES = frozenset(("FOUND", *DEFAULT_STATUSES))


@dataclass(frozen=True)
class SockseekConfig:
    """Configuration for a Sockseek download-list generator."""

    input_path: Path
    output_path: Path
    statuses: frozenset[str] = frozenset(DEFAULT_STATUSES)


@dataclass(frozen=True)
class WishlistConfig:
    """Configuration for a human-readable wishlist generator."""

    input_path: Path
    output_path: Path
    statuses: frozenset[str] = frozenset(DEFAULT_STATUSES)
    expected_format: str = "flac"


def read_check_results(path: Path) -> list[dict[str, str]]:
    """Read and validate the stable check-result CSV schema."""
    try:
        source = path.open(encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ValueError(f"Could not read check results {path}: {exc}") from exc
    with source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != RESULT_FIELDS:
            raise ValueError(
                "Check results must have columns: " + ", ".join(RESULT_FIELDS)
            )
        return [
            {field: row.get(field, "") for field in RESULT_FIELDS} for row in reader
        ]


class SockseekGenerator:
    """Write missing tracks in Sockseek's simple CSV input format."""

    fieldnames = ("title", "artist", "album")

    def __init__(self, config: SockseekConfig) -> None:
        self.config = config

    def run(self) -> int:
        rows = [
            row
            for row in read_check_results(self.config.input_path)
            if row["status"] in self.config.statuses
        ]
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config.output_path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(
                output, fieldnames=self.fieldnames, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(
                {field: row[field] for field in self.fieldnames} for row in rows
            )
        return len(rows)


class WishlistGenerator:
    """Write one missing or format-mismatched track per line."""

    def __init__(self, config: WishlistConfig) -> None:
        self.config = config

    def run(self) -> int:
        rows = [
            row
            for row in read_check_results(self.config.input_path)
            if row["status"] in self.config.statuses
        ]
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            " ".join(
                (
                    row["title"],
                    row["artist"],
                    *(
                        (self.config.expected_format,)
                        if row["status"] == "FORMAT-MISMATCH"
                        else ()
                    ),
                )
            )
            for row in rows
        ]
        self.config.output_path.write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )
        return len(rows)


def parse_args(argv: list[str]) -> SockseekConfig | WishlistConfig:
    """Parse ``subify generate`` and its generator-specific options."""
    parser = argparse.ArgumentParser(prog="subify generate", description=__doc__)
    generators = parser.add_subparsers(dest="generator", required=True)

    sockseek = generators.add_parser("sockseek", help="write a Sockseek CSV")
    sockseek.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    sockseek.add_argument("--output", type=Path, default=DEFAULT_SOCKSEEK_OUTPUT)
    _add_status_option(sockseek)

    wishlist = generators.add_parser("wishlist", help="write a text wishlist")
    wishlist.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    wishlist.add_argument("--output", type=Path, default=DEFAULT_WISHLIST_OUTPUT)
    _add_status_option(wishlist)
    wishlist.add_argument(
        "--format",
        dest="expected_format",
        default="flac",
        help="expected format written for every wishlist track (default: flac)",
    )

    args = parser.parse_args(argv)
    if args.generator == "sockseek":
        return SockseekConfig(
            args.input,
            args.output,
            statuses=_parse_statuses(args.status),
        )
    return WishlistConfig(
        args.input,
        args.output,
        statuses=_parse_statuses(args.status),
        expected_format=args.expected_format.casefold(),
    )


def _add_status_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--status",
        nargs="+",
        metavar="STATUS",
        help="statuses to export: MISSING, FORMAT-MISMATCH, or FOUND "
        "(default: MISSING FORMAT-MISMATCH)",
    )


def _parse_statuses(values: list[str] | None) -> frozenset[str]:
    if values is None:
        return frozenset(DEFAULT_STATUSES)
    statuses = frozenset(
        "FORMAT-MISMATCH"
        if value.strip().upper() == "FORMAT"
        else value.strip().upper()
        for item in values
        for value in item.split(",")
        if value.strip()
    )
    unknown = statuses - VALID_STATUSES
    if unknown:
        raise ValueError("Unknown status(es): " + ", ".join(sorted(unknown)))
    if not statuses:
        raise ValueError("At least one status is required")
    return statuses
