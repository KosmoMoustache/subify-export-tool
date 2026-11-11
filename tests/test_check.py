from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import pytest

from subify import SubifyApp
from subify.check import (
    DEFAULT_RESUME,
    CheckAborted,
    CheckConfig,
    CheckService,
    load_playlist,
    parse_args,
)
from subify.config import ServerConfig
from subify.match import PlaylistTrack, SubsonicTrack
from subify.prompts import MatchPromptAction, MatchPromptResult, QuestionaryPrompts


class FakeSearchClient:
    def __init__(
        self,
        responses: dict[str, list[dict]],
        folders: list[dict] | None = None,
        songs: dict[str, dict] | None = None,
    ) -> None:
        self.responses = responses
        self.folders = folders or []
        self.songs = songs or {}
        self.queries: list[str] = []
        self.library_queries: list[tuple[str, str | None]] = []

    def search_tracks(
        self,
        query: str,
        *,
        song_count: int = 20,
        music_folder_id: str | None = None,
    ) -> list[dict]:
        self.queries.append(query)
        self.library_queries.append((query, music_folder_id))
        return self.responses.get(query, [])

    def get_music_folders(self) -> list[dict]:
        return self.folders

    def get_song(self, song_id: str) -> dict | None:
        return self.songs.get(song_id)


def write_playlist(path: Path) -> None:
    path.write_text(
        "title,album,artist\n"
        "Match,Album,Artist\n"
        "Wrong Format,Album,Artist\n"
        "Missing,Album,Artist\n",
        encoding="utf-8",
    )


def config(
    tmp_path: Path, *, auto_skip: bool = True, cache: Path | None = None
) -> CheckConfig:
    return CheckConfig(
        server=ServerConfig("https://music.example", "user", "password", delay=0),
        playlist=tmp_path / "playlist.csv",
        result=tmp_path / "check_result.csv",
        expected_format="flac",
        auto_skip=auto_skip,
        cache=cache,
        library_ids=(),
        library_select=False,
        list_libraries=False,
    )


def test_check_writes_found_missing_and_format_mismatch_rows(tmp_path: Path) -> None:
    check_config = config(tmp_path)
    write_playlist(check_config.playlist)
    client = FakeSearchClient(
        {
            "Match Artist": [
                {"id": "1", "title": "Match", "artist": "Artist", "suffix": "flac"}
            ],
            "Wrong Format Artist": [
                {
                    "id": "2",
                    "title": "Wrong Format",
                    "artist": "Artist",
                    "suffix": "mp3",
                }
            ],
        }
    )

    results = CheckService(check_config, client).run()

    assert [result.status for result in results] == [
        "FOUND",
        "FORMAT-MISMATCH",
        "MISSING",
    ]
    with check_config.result.open(encoding="utf-8", newline="") as source:
        assert list(csv.DictReader(source)) == [
            {"title": "Match", "album": "Album", "artist": "Artist", "status": "FOUND"},
            {
                "title": "Wrong Format",
                "album": "Album",
                "artist": "Artist",
                "status": "FORMAT-MISMATCH",
            },
            {
                "title": "Missing",
                "album": "Album",
                "artist": "Artist",
                "status": "MISSING",
            },
        ]


def test_check_uses_a_cached_song_id_when_a_search_candidate_is_available(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache.txt"
    cache.write_text(
        "title,album,artist,subsonic_id\nMatch,Album,Artist,cached-id\n",
        encoding="utf-8",
    )
    check_config = config(tmp_path, cache=cache)
    check_config.playlist.write_text(
        "title,album,artist\nMatch,Album,Artist\n", encoding="utf-8"
    )
    client = FakeSearchClient(
        {
            "Match Artist": [
                {
                    "id": "cached-id",
                    "title": "Renamed",
                    "artist": "Other",
                    "suffix": "flac",
                }
            ]
        }
    )

    result = CheckService(check_config, client).run()[0]

    assert result.status == "FOUND"
    assert result.song is not None and result.song.id == "cached-id"


def test_check_resolves_a_cached_song_id_without_a_search_result(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache.csv"
    cache.write_text(
        "title,album,artist,subsonic_id\nMatch,Album,Artist,cached-id\n",
        encoding="utf-8",
    )
    check_config = config(tmp_path, cache=cache)
    check_config.playlist.write_text(
        "title,album,artist\nMatch,Album,Artist\n", encoding="utf-8"
    )
    client = FakeSearchClient(
        {},
        songs={
            "cached-id": {
                "id": "cached-id",
                "title": "Renamed",
                "artist": "Other",
                "suffix": "flac",
            }
        },
    )

    result = CheckService(check_config, client).run()[0]

    assert result.status == "FOUND"
    assert result.song is not None and result.song.id == "cached-id"


def test_cache_lookup_normalizes_its_track_fields(tmp_path: Path) -> None:
    cache = tmp_path / "cache.csv"
    cache.write_text(
        "title,album,artist,subsonic_id\n"
        "Beyoncé Song,The Album,Léonie Pernet; Malik Djoudi,cached-id\n",
        encoding="utf-8",
    )
    check_config = config(tmp_path, cache=cache)
    check_config.playlist.write_text(
        "title,album,artist\n"
        "  beyonce song  , the album ,leonie pernet;   malik djoudi\n",
        encoding="utf-8",
    )
    client = FakeSearchClient(
        {},
        songs={
            "cached-id": {
                "id": "cached-id",
                "title": "Different server title",
                "artist": "Different artist",
                "suffix": "flac",
            }
        },
    )

    result = CheckService(check_config, client).run()[0]

    assert result.song is not None and result.song.id == "cached-id"


def test_cache_is_used_only_after_an_automatic_match_fails(tmp_path: Path) -> None:
    cache = tmp_path / "cache.txt"
    cache.write_text(
        "title,album,artist,subsonic_id\nMatch,Album,Artist,cached-id\n",
        encoding="utf-8",
    )
    check_config = config(tmp_path, cache=cache)
    check_config.playlist.write_text(
        "title,album,artist\nMatch,Album,Artist\n", encoding="utf-8"
    )
    client = FakeSearchClient(
        {
            "Match Artist": [
                {
                    "id": "cached-id",
                    "title": "Different",
                    "artist": "Other",
                    "suffix": "flac",
                },
                {
                    "id": "automatic-id",
                    "title": "Match",
                    "artist": "Artist",
                    "album": "Album",
                    "suffix": "flac",
                },
            ]
        }
    )

    result = CheckService(check_config, client).run()[0]

    assert result.song is not None and result.song.id == "automatic-id"


def test_title_search_results_are_offered_when_no_candidate_is_plausible(
    tmp_path: Path, monkeypatch
) -> None:
    check_config = config(tmp_path, auto_skip=False)
    check_config.playlist.write_text(
        "title,album,artist\nInput,Album,Artist\n", encoding="utf-8"
    )
    client = FakeSearchClient(
        {
            "Input": [
                {
                    "id": "suggestion",
                    "title": "Unexpected Server Title",
                    "artist": "Other Artist",
                    "album": "Other Album",
                }
            ]
        }
    )
    captured: list[list] = []
    question = type(
        "Question",
        (),
        {"ask": lambda self: MatchPromptResult(MatchPromptAction.SKIP)},
    )()

    def select(_message: str, *, choices: list, **_kwargs: object) -> object:
        captured.append(choices)
        return question

    monkeypatch.setattr("subify.prompts.questionary.select", select)

    CheckService(check_config, client).run()

    assert captured[0][1].value.song is not None
    assert captured[0][1].value.song.id == "suggestion"


def test_interactive_candidates_mix_ascii_title_and_modified_title_searches(
    tmp_path: Path, monkeypatch
) -> None:
    check_config = config(tmp_path, auto_skip=False)
    check_config.playlist.write_text(
        "title,album,artist\nBeyoncé (Live) - Remix,Album,Artist\n",
        encoding="utf-8",
    )
    client = FakeSearchClient(
        {
            "Beyoncé (Live) - Remix Artist": [
                {"id": "full", "title": "Full", "artist": "Other"}
            ],
            "Beyonce (Live) - Remix Artist": [
                {"id": "ascii-full", "title": "ASCII full", "artist": "Other"}
            ],
            "Beyoncé (Live) - Remix": [
                {"id": "title", "title": "Title", "artist": "Other"}
            ],
            "Beyonce (Live) - Remix": [
                {"id": "ascii-title", "title": "ASCII title", "artist": "Other"}
            ],
            "Beyoncé": [{"id": "modified", "title": "Modified", "artist": "Other"}],
            "Beyonce": [{"id": "full", "title": "Duplicate", "artist": "Other"}],
        }
    )
    captured: list[list] = []
    question = type(
        "Question",
        (),
        {"ask": lambda self: MatchPromptResult(MatchPromptAction.SKIP)},
    )()
    monkeypatch.setattr(
        "subify.prompts.questionary.select",
        lambda _message, choices, **_kwargs: captured.append(choices) or question,
    )

    CheckService(check_config, client).run()

    candidate_ids = [choice.value.song.id for choice in captured[0][1:6]]
    assert candidate_ids == [
        "full",
        "ascii-full",
        "title",
        "ascii-title",
        "modified",
    ]


def test_load_playlist_keeps_track_duration_in_milliseconds(tmp_path: Path) -> None:
    playlist = tmp_path / "playlist.csv"
    playlist.write_text(
        "title,album,artist,duration_ms\nSong,Album,Artist,180000\n",
        encoding="utf-8",
    )

    track = load_playlist(playlist)[0]

    assert track.duration_ms == 180_000


def test_check_retries_the_initial_query_with_an_ascii_variant(tmp_path: Path) -> None:
    check_config = config(tmp_path)
    check_config.playlist.write_text(
        "title,album,artist\nBeyonc\u00e9 Song,Album,Artist\n", encoding="utf-8"
    )
    client = FakeSearchClient(
        {
            "Beyonce Song Artist": [
                {
                    "id": "1",
                    "title": "Beyonce Song",
                    "artist": "Artist",
                    "suffix": "flac",
                }
            ]
        }
    )

    result = CheckService(check_config, client).run()[0]

    assert result.status == "FOUND"
    assert client.queries == ["Beyonc\u00e9 Song Artist", "Beyonce Song Artist"]


def test_cli_dispatches_the_check_command(tmp_path: Path, capsys) -> None:
    playlist = tmp_path / "playlist.csv"
    playlist.write_text("title,album,artist\nMatch,Album,Artist\n", encoding="utf-8")
    result = tmp_path / "result.csv"
    client = FakeSearchClient(
        {
            "Match Artist": [
                {"id": "1", "title": "Match", "artist": "Artist", "suffix": "flac"}
            ]
        }
    )
    app = SubifyApp(
        [
            "check",
            "--url",
            "https://music.example",
            "--username",
            "user",
            "--password",
            "password",
            "--playlist",
            str(playlist),
            "--result",
            str(result),
            "--auto-skip",
        ],
        client_factory=lambda _server: client,  # type: ignore[arg-type]
    )

    assert app.run() == 0
    assert "Checked 1 track(s): 1 found." in capsys.readouterr().out
    assert result.exists()


def test_library_selection_restricts_each_search_to_selected_libraries(
    tmp_path: Path, monkeypatch
) -> None:
    check_config = replace(config(tmp_path), library_select=True)
    check_config.playlist.write_text(
        "title,album,artist\nMatch,Album,Artist\n", encoding="utf-8"
    )
    client = FakeSearchClient(
        {"Match Artist": [{"id": "1", "title": "Match", "artist": "Artist"}]},
        folders=[{"id": "one", "name": "One"}, {"id": "two", "name": "Two"}],
    )
    question = type("Question", (), {"ask": lambda self: ["two"]})()
    calls: list[tuple[str, list]] = []

    def checkbox(message: str, choices: list) -> object:
        calls.append((message, choices))
        return question

    monkeypatch.setattr("subify.prompts.questionary.checkbox", checkbox)

    CheckService(check_config, client).run()

    assert client.library_queries == [("Match Artist", "two")]
    assert calls[0][0] == "Select music libraries (leave empty to search all):"


def test_list_libraries_prints_server_folders(tmp_path: Path) -> None:
    client = FakeSearchClient(
        {}, folders=[{"id": "1", "name": "Main"}, {"id": "2", "name": "Archive"}]
    )
    messages: list[str] = []

    CheckService(config(tmp_path), client, output=messages.append).list_libraries()

    assert messages == [
        "Music libraries on https://music.example:",
        "  1  Main",
        "  2  Archive",
    ]


def test_check_prints_a_progress_line_for_each_result(tmp_path: Path) -> None:
    check_config = config(tmp_path)
    check_config.playlist.write_text(
        "title,album,artist\nMatch,Album,Artist\n", encoding="utf-8"
    )
    client = FakeSearchClient(
        {
            "Match Artist": [
                {"id": "1", "title": "Match", "artist": "Artist", "suffix": "flac"}
            ]
        }
    )
    messages: list[str] = []

    CheckService(check_config, client, output=messages.append).run()

    assert messages == ["[1/1] FOUND: Match Artist Album [flac]"]


def test_score_match_option_is_disabled_by_default_and_can_be_enabled() -> None:
    shared_options = [
        "--url",
        "https://music.example",
        "--username",
        "user",
        "--password",
        "password",
    ]

    assert not parse_args(shared_options).score_match
    assert parse_args([*shared_options, "--score-match"]).score_match
    disabled = parse_args([*shared_options, "--score-match", "--no-score-match"])
    assert not disabled.score_match


def test_check_uses_score_matching_when_enabled(tmp_path: Path) -> None:
    check_config = replace(config(tmp_path), score_match=True)
    check_config.playlist.write_text(
        "title,album,artist\nSong,Album,The Artist\n", encoding="utf-8"
    )
    client = FakeSearchClient(
        {
            "Song The Artist": [
                {
                    "id": "1",
                    "title": "Song",
                    "artist": "The Artist feat. Guest",
                    "suffix": "flac",
                }
            ]
        }
    )

    result = CheckService(check_config, client).run()[0]

    assert result.status == "FOUND"
    assert result.song is not None and result.song.id == "1"


def test_verbose_reports_the_automatic_match_step(tmp_path: Path) -> None:
    check_config = config(tmp_path)
    check_config = replace(check_config, server=replace(check_config.server, verbose=1))
    check_config.playlist.write_text(
        "title,album,artist\nMatch,Album,Artist\n", encoding="utf-8"
    )
    client = FakeSearchClient(
        {
            "Match Artist": [
                {"id": "1", "title": "Match", "artist": "Artist", "suffix": "flac"}
            ]
        }
    )
    messages: list[str] = []

    CheckService(check_config, client, output=messages.append).run()

    assert messages == [
        "[verbose] [1/1] matched via title + artist: Match Artist Album",
        "[1/1] FOUND: Match Artist Album [flac]",
    ]


def test_quit_saves_processed_results_and_resume_position(
    tmp_path: Path, monkeypatch
) -> None:
    cache = tmp_path / "cache.txt"
    check_config = config(tmp_path, auto_skip=False, cache=cache)
    write_playlist(check_config.playlist)
    client = FakeSearchClient(
        {
            "Match Artist": [
                {"id": "1", "title": "Match", "artist": "Artist", "suffix": "flac"}
            ]
        }
    )
    question = type(
        "Question",
        (),
        {"ask": lambda self: MatchPromptResult(MatchPromptAction.QUIT)},
    )()
    monkeypatch.setattr(
        "subify.prompts.questionary.select",
        lambda _message, choices, **_kwargs: question,
    )
    messages: list[str] = []

    with pytest.raises(CheckAborted):
        CheckService(check_config, client, output=messages.append).run()

    assert not cache.exists()
    assert (tmp_path / DEFAULT_RESUME.name).read_text(encoding="utf-8") == "1\n"
    with check_config.result.open(encoding="utf-8", newline="") as result_file:
        assert list(csv.DictReader(result_file)) == [
            {"title": "Match", "album": "Album", "artist": "Artist", "status": "FOUND"}
        ]
    assert (
        "[2/3] MISSING: Wrong Format Artist Album (choose a match or skip)" in messages
    )
    assert messages[-1] == f"Saved 1 processed track(s) to {check_config.result}."


def test_only_a_user_selected_match_is_saved_to_the_cache(
    tmp_path: Path, monkeypatch
) -> None:
    cache = tmp_path / "cache.csv"
    check_config = config(tmp_path, auto_skip=False, cache=cache)
    check_config.playlist.write_text(
        "title,album,artist\nSong,Album,Artist\n", encoding="utf-8"
    )
    selected_song = SubsonicTrack("manual-id", "Song", "Other", "Elsewhere")
    client = FakeSearchClient(
        {
            "Song Artist": [
                {
                    "id": selected_song.id,
                    "title": selected_song.title,
                    "artist": selected_song.artist,
                    "album": selected_song.album,
                    "suffix": "flac",
                }
            ]
        }
    )
    question = type(
        "Question",
        (),
        {
            "ask": lambda self: MatchPromptResult(
                MatchPromptAction.SELECT, selected_song
            )
        },
    )()
    monkeypatch.setattr(
        "subify.prompts.questionary.select",
        lambda _message, choices, **_kwargs: question,
    )

    CheckService(check_config, client).run()

    assert (
        cache.read_text(encoding="utf-8")
        == "title,album,artist,subsonic_id\nSong,Album,Artist,manual-id\n"
    )


def test_check_resumes_from_saved_results(tmp_path: Path, monkeypatch) -> None:
    check_config = config(tmp_path, auto_skip=False)
    write_playlist(check_config.playlist)
    check_config.result.write_text(
        "title,album,artist,status\nMatch,Album,Artist,FOUND\n", encoding="utf-8"
    )
    resume = tmp_path / DEFAULT_RESUME.name
    resume.write_text("1\n", encoding="utf-8")
    client = FakeSearchClient(
        {
            "Wrong Format Artist": [
                {
                    "id": "2",
                    "title": "Wrong Format",
                    "artist": "Artist",
                    "suffix": "flac",
                }
            ]
        }
    )
    monkeypatch.setattr(
        "subify.prompts.questionary.confirm",
        lambda *_args, **_kwargs: type("Question", (), {"ask": lambda self: True})(),
    )
    monkeypatch.setattr(
        "subify.prompts.questionary.select",
        lambda _message, choices, **_kwargs: type(
            "Question",
            (),
            {"ask": lambda self: MatchPromptResult(MatchPromptAction.SKIP)},
        )(),
    )

    results = CheckService(check_config, client).run()

    assert [result.status for result in results] == ["FOUND", "FOUND", "MISSING"]
    assert client.queries == ["Wrong Format Artist", "Missing Artist", "Missing"]
    assert not resume.exists()


def test_match_prompt_separates_candidates_from_actions(monkeypatch) -> None:
    recorded_choices: list[list] = []
    messages: list[str] = []
    question = type(
        "Question",
        (),
        {"ask": lambda self: MatchPromptResult(MatchPromptAction.SKIP)},
    )()

    def select(message: str, *, choices: list, **kwargs: object) -> object:
        messages.append(message)
        recorded_choices.append(choices)
        assert "style" in kwargs
        return question

    monkeypatch.setattr("subify.prompts.questionary.select", select)
    prompt = QuestionaryPrompts()
    track = PlaylistTrack("Title", ("Artist",), "Album")
    song = SubsonicTrack("id", "Title", "Artist", "Album", format="flac")

    prompt.choose_match(track, (song,))
    prompt.choose_match(track, ())

    assert recorded_choices[0][0].__class__.__name__ == "Separator"
    assert recorded_choices[0][2].__class__.__name__ == "Separator"
    assert all(
        choice.__class__.__name__ != "Separator" for choice in recorded_choices[1]
    )
    assert "\x1b" not in messages[0]
    assert recorded_choices[0][1].title[0][0] == "class:track-title"


def test_match_prompt_formats_candidates_as_an_aligned_table() -> None:
    candidates = (
        SubsonicTrack("1", "Short", "Artist", "Album", duration=65, format="flac"),
        SubsonicTrack(
            "long-id", "Much longer title", "A", "Longer album", format="mp3"
        ),
    )

    header, rows = QuestionaryPrompts._candidate_table(candidates)

    assert header == (
        "Title             | Artist | Album        | Duration | Format | ID     "
    )
    assert rows == [
        "Short             | Artist | Album        | 1:05     | flac   | 1      ",
        "Much longer title | A      | Longer album | ?        | mp3    | long-id",
    ]


def test_match_search_prompt_is_prepopulated_with_title_and_artist(monkeypatch) -> None:
    captured: dict[str, str] = {}
    question = type("Question", (), {"ask": lambda self: "new search"})()

    def text(message: str, *, default: str) -> object:
        captured["message"] = message
        captured["default"] = default
        return question

    monkeypatch.setattr("subify.prompts.questionary.text", text)

    selection = QuestionaryPrompts().search_terms("Song The Artist")

    assert selection == "new search"
    assert captured == {
        "message": "Search Subsonic with:",
        "default": "Song The Artist",
    }
