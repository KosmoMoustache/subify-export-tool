from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

from subify.check import CheckConfig, CheckService
from subify.config import ServerConfig
from subify.match import PlaylistTrack
from subify.resolution import TrackResolutionService


class FakeClient:
    def __init__(self, responses: dict[str, list[dict]]) -> None:
        self.responses = responses

    def search_tracks(self, query: str, **_kwargs: object) -> list[dict]:
        return self.responses.get(query, [])

    def get_music_folders(self) -> list[dict]:
        return []

    def get_song(self, _song_id: str) -> dict | None:
        return None


class NoPrompt:
    def format_track(self, track: PlaylistTrack) -> str:
        return track.title

    def choose_match(self, _track: PlaylistTrack, _candidates: tuple) -> object:
        raise AssertionError("a resumed track must not prompt")

    def search_terms(self, _default: str) -> str | None:
        raise AssertionError("a resumed track must not prompt")


def check_service(
    tmp_path: Path, client: FakeClient, *, prompts: object | None = None
) -> CheckService:
    return CheckService(
        CheckConfig(
            server=ServerConfig("https://music.example", "user", "password", delay=0),
            playlist=tmp_path / "playlist.csv",
            result=tmp_path / "check_result.csv",
            expected_format="flac",
            auto_skip=False,
            cache=None,
            library_ids=(),
            library_select=False,
            list_libraries=False,
        ),
        client,
        prompts=prompts,  # type: ignore[arg-type]
        output=lambda _message: None,
    )


def test_resolution_service_resolves_in_order_and_reports_progress(
    tmp_path: Path,
) -> None:
    service = check_service(
        tmp_path,
        FakeClient(
            {
                "First Artist": [{"id": "first", "title": "First", "artist": "Artist"}],
                "Second Artist": [
                    {"id": "second", "title": "Second", "artist": "Artist"}
                ],
            }
        ),
    )
    progress: list[tuple[int, int]] = []
    tracks = [
        PlaylistTrack("First", ("Artist",), "Album"),
        PlaylistTrack("Second", ("Artist",), "Album"),
    ]

    results = TrackResolutionService(service).run(
        tracks,
        on_result=lambda index, resolved: progress.append((index, len(resolved))),
    )

    assert [result.song.id for result in results if result.song] == ["first", "second"]
    assert progress == [(1, 1), (2, 2)]


def test_resolution_service_does_not_prompt_for_resumed_tracks(tmp_path: Path) -> None:
    service = check_service(tmp_path, FakeClient({}), prompts=NoPrompt())
    track = PlaylistTrack("Missing", ("Artist",), "Album")

    results = TrackResolutionService(service).run([track], resume_after=1)

    assert results[0].status == "MISSING"


def test_resolution_service_runs_initial_searches_concurrently(tmp_path: Path) -> None:
    class ConcurrentClient(FakeClient):
        def __init__(self) -> None:
            super().__init__({})
            self.active = 0
            self.maximum_active = 0
            self.lock = threading.Lock()

        def search_tracks(self, query: str, **_kwargs: object) -> list[dict]:
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
            time.sleep(0.03)
            with self.lock:
                self.active -= 1
            title = query.split()[0]
            return [{"id": title, "title": title, "artist": "Artist"}]

    client = ConcurrentClient()
    service = check_service(tmp_path, client)
    service.config = replace(service.config, workers=3)
    tracks = [PlaylistTrack(f"Song{index}", ("Artist",), "Album") for index in range(4)]

    TrackResolutionService(service).run(tracks)

    assert client.maximum_active > 1
    assert client.maximum_active <= 3
