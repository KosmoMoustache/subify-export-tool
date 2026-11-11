"""Tests for terminal-output formatting."""

import sys

from subify.output import track_label, verbose


def test_verbose_highlights_the_prefix_in_a_terminal(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)

    assert verbose("request sent") == "\x1b[36m[verbose]\x1b[0m request sent"


def test_verbose_stays_plain_when_color_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("NO_COLOR", "1")

    assert verbose("request sent") == "[verbose] request sent"


def test_track_label_colours_each_field_in_a_terminal(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)

    assert track_label("Title", "Artist", "Album") == (
        "\x1b[36mTitle\x1b[0m \x1b[32mArtist\x1b[0m \x1b[33mAlbum\x1b[0m"
    )


def test_track_label_uses_spaces_without_colour(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setenv("NO_COLOR", "1")

    assert track_label("Title", "Artist", "Album") == "Title Artist Album"
