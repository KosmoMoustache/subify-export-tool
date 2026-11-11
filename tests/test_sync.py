from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from subify.check import CheckAborted
from subify.config import ServerConfig
from subify.prompts import MatchPromptAction, MatchPromptResult
from subify.sync import DEFAULT_RESUME, SyncConfig, SyncService, parse_args


class FakeSyncClient:
    def __init__(
        self,
        *,
        playlists: list[dict] | None = None,
        playlist_details: dict[str, dict] | None = None,
    ) -> None:
        self.playlists = playlists or []
        self.playlist_details = playlist_details or {}
        self.created: list[dict] = []
        self.requested_playlists: list[str] = []

    def search_tracks(self, query: str, **_kwargs: object) -> list[dict]:
        return [
            {
                "id": f"id-{query.split()[0].casefold()}",
                "title": query.split()[0],
                "artist": "Artist",
                "suffix": "flac",
            }
        ]

    def get_music_folders(self) -> list[dict]:
        return []

    def get_song(self, _song_id: str) -> dict | None:
        return None

    def get_playlists(self) -> list[dict]:
        return self.playlists

    def get_playlist(self, playlist_id: str) -> dict | None:
        self.requested_playlists.append(playlist_id)
        if playlist_id in self.playlist_details:
            return self.playlist_details[playlist_id]
        return next(
            (item for item in self.playlists if item["id"] == playlist_id), None
        )

    def create_playlist(
        self,
        *,
        name: str | None = None,
        playlist_id: str | None = None,
        song_ids: list[str],
    ) -> dict:
        record = {
            "id": playlist_id or "new-id",
            "name": name or "Existing",
            "entry": [{"id": song_id} for song_id in song_ids],
        }
        self.created.append(record)
        return record


def config(tmp_path: Path, **changes: object) -> SyncConfig:
    values: dict[str, object] = {
        "server": ServerConfig("https://music.example", "user", "password", delay=0),
        "input_path": tmp_path / "playlist.csv",
        "output_path": tmp_path / "sync_summary.txt",
        "playlist_id": None,
        "playlist_name": "My playlist",
        "dry_run": False,
        "auto_skip": True,
        "cache": None,
        "library_ids": (),
        "library_select": False,
        "list_libraries": False,
    }
    values.update(changes)
    return SyncConfig(**values)  # type: ignore[arg-type]


def write_playlist(path: Path) -> None:
    path.write_text(
        "title,album,artist\nFirst,Album,Artist\nSecond,Album,Artist\n",
        encoding="utf-8",
    )


def test_sync_creates_a_playlist_in_input_order(tmp_path: Path) -> None:
    sync_config = config(tmp_path)
    write_playlist(sync_config.input_path)
    client = FakeSyncClient()

    results = SyncService(sync_config, client).run()

    assert [result.song.id for result in results if result.song] == [
        "id-first",
        "id-second",
    ]
    assert client.created == [
        {
            "id": "new-id",
            "name": "My playlist",
            "entry": [{"id": "id-first"}, {"id": "id-second"}],
        }
    ]


def test_sync_updates_a_named_existing_playlist(tmp_path: Path) -> None:
    sync_config = config(tmp_path)
    sync_config.input_path.write_text(
        "title,album,artist\nSecond,Album,Artist\n", encoding="utf-8"
    )
    client = FakeSyncClient(
        playlists=[
            {"id": "playlist-id", "name": "MY PLAYLIST", "entry": [{"id": "old"}]}
        ]
    )

    SyncService(sync_config, client).run()

    assert client.created[0]["id"] == "playlist-id"
    assert client.created[0]["entry"] == [{"id": "id-second"}]


def test_sync_reloads_a_playlist_found_by_name_before_calculating_changes(
    tmp_path: Path,
) -> None:
    sync_config = config(tmp_path)
    sync_config.input_path.write_text(
        "title,album,artist\nSecond,Album,Artist\n", encoding="utf-8"
    )
    client = FakeSyncClient(
        playlists=[{"id": "playlist-id", "name": "MY PLAYLIST"}],
        playlist_details={
            "playlist-id": {
                "id": "playlist-id",
                "name": "MY PLAYLIST",
                "entry": [{"id": "id-second"}],
            }
        },
    )
    messages: list[str] = []

    SyncService(sync_config, client, output=messages.append).run()

    assert client.requested_playlists == ["playlist-id"]
    assert client.created == []
    assert "Already in playlist : 1" in messages[-1]


def test_sync_dry_run_does_not_change_the_server(tmp_path: Path) -> None:
    sync_config = config(tmp_path, dry_run=True)
    write_playlist(sync_config.input_path)
    client = FakeSyncClient()

    SyncService(sync_config, client).run()

    assert client.created == []


def test_sync_prints_the_detailed_summary(tmp_path: Path) -> None:
    sync_config = config(tmp_path)
    write_playlist(sync_config.input_path)
    messages: list[str] = []

    SyncService(sync_config, FakeSyncClient(), output=messages.append).run()

    assert messages[-1] == "\n".join(
        (
            "============================================================",
            "SYNC SUMMARY",
            "============================================================",
            "Playlist          : My playlist (id=new-id)",
            "Server            : https://music.example",
            f"CSV source        : {sync_config.input_path}",
            "CSV tracks        : 2",
            "Matched           : 2 (cache=0, auto=2, manual=0)",
            "Skipped / not found: 0",
            "------------------------------------------------------------",
            "Already in playlist : 0",
            "Added to playlist   : 2",
            "Removed from playlist: 0",
            "Reordered / moved   : 0",
            "Final playlist size : 2 (was 0)",
            "------------------------------------------------------------",
            "Changes applied to server : yes",
            "============================================================",
        )
    )
    assert sync_config.output_path.read_text(encoding="utf-8") == messages[-1] + "\n"


def test_sync_saves_and_resumes_its_current_position(
    tmp_path: Path, monkeypatch
) -> None:
    sync_config = config(tmp_path, auto_skip=False)
    sync_config.input_path.write_text(
        "title,album,artist\nFirst,Album,Artist\nMissing,Album,Artist\n",
        encoding="utf-8",
    )
    client = FakeSyncClient()
    client.search_tracks = lambda query, **_kwargs: (  # type: ignore[method-assign]
        [
            {
                "id": "id-first",
                "title": "First",
                "artist": "Artist",
                "suffix": "flac",
            }
        ]
        if query == "First Artist"
        else []
    )
    quit_question = type(
        "Question",
        (),
        {"ask": lambda self: MatchPromptResult(MatchPromptAction.QUIT)},
    )()
    monkeypatch.setattr(
        "subify.prompts.questionary.select",
        lambda _message, choices, **_kwargs: quit_question,
    )

    with pytest.raises(CheckAborted):
        SyncService(sync_config, client).run()

    resume = tmp_path / DEFAULT_RESUME.name
    assert resume.read_text(encoding="utf-8") == "1\n"

    resumed = replace(sync_config, auto_skip=True)
    monkeypatch.setattr(
        "subify.prompts.questionary.confirm",
        lambda *_args, **_kwargs: type("Question", (), {"ask": lambda self: True})(),
    )
    SyncService(resumed, client).run()

    assert not resume.exists()


def test_sync_uses_input_and_text_summary_paths(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "summary.txt"

    parsed = parse_args(
        [
            "--url",
            "https://music.example",
            "--username",
            "user",
            "--password",
            "password",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ]
    )

    assert parsed.input_path == input_path
    assert parsed.output_path == output_path


def test_sync_summary_file_strips_terminal_colours(tmp_path: Path) -> None:
    sync_config = config(tmp_path)
    service = SyncService(sync_config, FakeSyncClient())

    service._write_summary("\x1b[36mTitle\x1b[0m Artist")

    assert sync_config.output_path.read_text(encoding="utf-8") == "Title Artist\n"
