from __future__ import annotations

import csv
from pathlib import Path

from subify import SubifyApp
from subify.convert import ConvertConfig, SpotifyPlaylistConverter


def write_spotify_export(path: Path) -> None:
    path.write_text(
        "Track URI,ISRC,Track Name,Album Name,Artist Name(s),Duration (ms)\n"
        "spotify:track:1,US-ABC-12-34567,First Song,First Album,"
        "First Artist; Guest,123000\n"
        "spotify:track:2,,Second Song,Second Album,Second Artist,456000\n"
        "spotify:track:3,, ,Ignored Album,Ignored Artist,1000\n",
        encoding="utf-8",
    )


def test_converter_writes_the_compact_playlist_schema(tmp_path: Path) -> None:
    source = tmp_path / "Liked_Songs.csv"
    output = tmp_path / "nested" / "playlist.csv"
    write_spotify_export(source)

    count = SpotifyPlaylistConverter(ConvertConfig(source, output)).run()

    assert count == 2
    with output.open(encoding="utf-8", newline="") as converted:
        assert list(csv.DictReader(converted)) == [
            {
                "isrc": "US-ABC-12-34567",
                "title": "First Song",
                "album": "First Album",
                "artist": "First Artist; Guest",
                "duration_ms": "123000",
            },
            {
                "isrc": "",
                "title": "Second Song",
                "album": "Second Album",
                "artist": "Second Artist",
                "duration_ms": "456000",
            },
        ]


def test_convert_command_reports_the_written_track_count(
    tmp_path: Path, capsys
) -> None:
    source = tmp_path / "spotify.csv"
    output = tmp_path / "playlist.csv"
    write_spotify_export(source)

    assert (
        SubifyApp(["convert", "--input", str(source), "--output", str(output)]).run()
        == 0
    )

    assert f"Converted 2 track(s) to {output}" in capsys.readouterr().out
    assert output.exists()


def test_converter_rejects_a_file_without_spotify_columns(tmp_path: Path) -> None:
    source = tmp_path / "invalid.csv"
    source.write_text("title,artist\nSong,Artist\n", encoding="utf-8")

    app = SubifyApp(["convert", "--input", str(source)])

    assert app.run() == 2
