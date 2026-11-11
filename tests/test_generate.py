from __future__ import annotations

import csv
from pathlib import Path

from subify import SubifyApp
from subify.generate import (
    SockseekConfig,
    SockseekGenerator,
    WishlistConfig,
    WishlistGenerator,
)


def write_results(path: Path) -> None:
    path.write_text(
        "title,album,artist,status\n"
        "Found,Album A,Artist A,FOUND\n"
        "Missing,Album B,Artist B,MISSING\n"
        "Wrong Format,Album C,Artist C,FORMAT-MISMATCH\n",
        encoding="utf-8",
    )


def test_sockseek_generator_writes_missing_and_format_mismatch_rows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "check_result.csv"
    output = tmp_path / "sockseek.csv"
    write_results(source)

    count = SockseekGenerator(SockseekConfig(source, output)).run()

    assert count == 2
    with output.open(encoding="utf-8", newline="") as generated:
        assert list(csv.DictReader(generated)) == [
            {"title": "Missing", "artist": "Artist B", "album": "Album B"},
            {
                "title": "Wrong Format",
                "artist": "Artist C",
                "album": "Album C",
            },
        ]


def test_sockseek_can_exclude_format_mismatches(tmp_path: Path) -> None:
    source = tmp_path / "check_result.csv"
    output = tmp_path / "sockseek.csv"
    write_results(source)

    count = SockseekGenerator(
        SockseekConfig(source, output, include_format_mismatch=False)
    ).run()

    assert count == 1


def test_wishlist_generator_writes_one_track_per_line(tmp_path: Path) -> None:
    source = tmp_path / "check_result.csv"
    output = tmp_path / "wishlist.txt"
    write_results(source)

    count = WishlistGenerator(WishlistConfig(source, output)).run()

    assert count == 2
    assert output.read_text(encoding="utf-8") == (
        "Missing - Album B - Artist B - MISSING\n"
        "Wrong Format - Album C - Artist C - FORMAT-MISMATCH\n"
    )


def test_generate_command_dispatches_sockseek(tmp_path: Path, capsys) -> None:
    source = tmp_path / "check_result.csv"
    output = tmp_path / "sockseek.csv"
    write_results(source)

    assert (
        SubifyApp(
            ["generate", "sockseek", "--input", str(source), "--output", str(output)]
        ).run()
        == 0
    )

    assert f"Generated 2 Sockseek track(s) in {output}" in capsys.readouterr().out
