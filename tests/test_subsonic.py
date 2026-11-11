from __future__ import annotations

import pytest

from subify.config import ServerConfig
from subify.subsonic import SubsonicClient, SubsonicClientError


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.params: dict | None = None

    def get(self, _url: str, *, params: dict, timeout: float) -> FakeResponse:
        self.params = {**params, "timeout": timeout}
        return self.response


def test_ping_sends_subsonic_authentication_parameters() -> None:
    session = FakeSession(FakeResponse({"subsonic-response": {"status": "ok"}}))
    client = SubsonicClient(
        ServerConfig("https://music.example", "user", "secret", timeout=4, delay=0),
        session=session,  # type: ignore[arg-type]
    )

    assert client.ping() == {"status": "ok"}
    assert session.params == {
        "u": "user",
        "p": "secret",
        "v": "1.16.1",
        "c": "subify",
        "f": "json",
        "timeout": 4,
    }


def test_ping_turns_a_server_failure_into_a_client_error() -> None:
    session = FakeSession(
        FakeResponse(
            {"subsonic-response": {"status": "failed", "error": {"message": "denied"}}}
        )
    )
    client = SubsonicClient(
        ServerConfig("https://music.example", "user", "secret", delay=0),
        session=session,  # type: ignore[arg-type]
    )

    with pytest.raises(SubsonicClientError, match="denied"):
        client.ping()


def test_get_song_requests_a_track_by_id() -> None:
    session = FakeSession(
        FakeResponse(
            {
                "subsonic-response": {
                    "status": "ok",
                    "song": {"id": "cached-id", "title": "Cached"},
                }
            }
        )
    )
    client = SubsonicClient(
        ServerConfig("https://music.example", "user", "secret", delay=0),
        session=session,  # type: ignore[arg-type]
    )

    assert client.get_song("cached-id") == {"id": "cached-id", "title": "Cached"}
    assert session.params is not None and session.params["id"] == "cached-id"


def test_double_verbose_logs_requests_without_authentication_parameters(capsys) -> None:
    session = FakeSession(FakeResponse({"subsonic-response": {"status": "ok"}}))
    client = SubsonicClient(
        ServerConfig("https://music.example", "user", "secret", delay=0, verbose=2),
        session=session,  # type: ignore[arg-type]
    )

    client.ping()

    output = capsys.readouterr().out
    assert "[verbose] GET /rest/ping params={}" in output
    assert "[verbose] GET /rest/ping completed with HTTP 200" in output
    assert "user" not in output
    assert "secret" not in output


def test_triple_verbose_logs_the_api_response(capsys) -> None:
    session = FakeSession(FakeResponse({"subsonic-response": {"status": "ok"}}))
    client = SubsonicClient(
        ServerConfig("https://music.example", "user", "secret", delay=0, verbose=3),
        session=session,  # type: ignore[arg-type]
    )

    client.ping()

    output = capsys.readouterr().out
    assert '[verbose] GET /rest/ping response={"status": "ok"}' in output
