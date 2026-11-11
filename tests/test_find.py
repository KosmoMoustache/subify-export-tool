from __future__ import annotations

from pathlib import Path

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

from subify.config import ServerConfig
from subify.find import FindConfig, FindService, _LimitCompleter
from subify.prompts import QuestionaryPrompts


class FakeClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search_tracks(self, query: str, **_kwargs: object) -> list[dict]:
        self.queries.append(query)
        return [
            {
                "id": "server-id",
                "title": "Server title",
                "artist": "Server artist",
                "album": "Server album",
            }
        ]


def _config(tmp_path: Path) -> FindConfig:
    playlist = tmp_path / "playlist.csv"
    playlist.write_text(
        "title,album,artist\nPlaylist title,Playlist album,Playlist artist\n",
        encoding="utf-8",
    )
    return FindConfig(
        ServerConfig("https://music.example", "user", "pw"),
        playlist,
        tmp_path / "cache.csv",
    )


def test_find_selects_tracks_and_saves_the_correspondence(
    tmp_path, monkeypatch
) -> None:
    class Prompt:
        def __init__(self, result) -> None:
            self.result = result

        def ask(self):
            return self.result

    def autocomplete(*_args, **_kwargs):
        return Prompt("Playlist title Playlist artist Playlist album")

    def text(*_args, **_kwargs):
        return Prompt("custom query")

    def select(*_args, **kwargs):
        return Prompt(kwargs["choices"][0].value)

    monkeypatch.setattr("subify.find.questionary.autocomplete", autocomplete)
    monkeypatch.setattr("subify.find.questionary.text", text)
    monkeypatch.setattr("subify.find.questionary.select", select)
    client = FakeClient()

    track, song = FindService(_config(tmp_path), client).run()

    assert track.title == "Playlist title"
    assert song.id == "server-id"
    assert client.queries == ["custom query"]
    assert (tmp_path / "cache.csv").read_text(encoding="utf-8") == (
        "title,album,artist,subsonic_id\n"
        "Playlist title,Playlist album,Playlist artist,server-id\n"
    )


def test_playlist_completer_limits_results_to_five() -> None:
    class ManyCompletions(Completer):
        def get_completions(self, _document, _complete_event):
            yield from (Completion(str(index)) for index in range(10))

    completions = list(
        _LimitCompleter(ManyCompletions(), 5).get_completions(
            Document(""), CompleteEvent()
        )
    )

    assert [completion.text for completion in completions] == ["0", "1", "2", "3", "4"]


def test_find_uses_questionary_fragments_for_coloured_song_choices(
    tmp_path, monkeypatch
) -> None:
    class Prompt:
        def __init__(self, result) -> None:
            self.result = result

        def ask(self):
            return self.result

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "subify.find.questionary.autocomplete",
        lambda *_args, **_kwargs: Prompt(
            "Playlist title Playlist artist Playlist album"
        ),
    )
    monkeypatch.setattr(
        "subify.find.questionary.text", lambda *_args, **_kwargs: Prompt("q")
    )

    def select(*_args, **kwargs):
        captured.update(kwargs)
        return Prompt(kwargs["choices"][0].value)

    monkeypatch.setattr("subify.find.questionary.select", select)

    FindService(_config(tmp_path), FakeClient()).run()

    choice = captured["choices"][0]
    assert choice.title == [
        ("class:track-title", "Server title"),
        ("", " "),
        ("class:track-artist", "Server artist"),
        ("", " "),
        ("class:track-album", "Server album"),
        ("", " [?] #id=server-id"),
    ]
    assert captured["style"] is QuestionaryPrompts.choice_style()
