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


@dataclass(frozen=True)
class SockseekConfig:
    """Configuration for a Sockseek download-list generator."""

    input_path: Path
    output_path: Path
    include_format_mismatch: bool = True


@dataclass(frozen=True)
class WishlistConfig:
    """Configuration for a human-readable wishlist generator."""

    input_path: Path
    output_path: Path


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
        statuses = {"MISSING"}
        if self.config.include_format_mismatch:
            statuses.add("FORMAT-MISMATCH")
        rows = [
            row
            for row in read_check_results(self.config.input_path)
            if row["status"] in statuses
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
            if row["status"] in {"MISSING", "FORMAT-MISMATCH"}
        ]
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            " - ".join((row["title"], row["album"], row["artist"], row["status"]))
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
    sockseek.add_argument(
        "--include-format-mismatch",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="include FORMAT-MISMATCH rows (default: enabled)",
    )

    wishlist = generators.add_parser("wishlist", help="write a text wishlist")
    wishlist.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    wishlist.add_argument("--output", type=Path, default=DEFAULT_WISHLIST_OUTPUT)

    args = parser.parse_args(argv)
    if args.generator == "sockseek":
        return SockseekConfig(
            args.input,
            args.output,
            include_format_mismatch=args.include_format_mismatch,
        )
    return WishlistConfig(args.input, args.output)
