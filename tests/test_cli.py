from __future__ import annotations

from typing import Any

from subify import SubifyApp
from subify.subsonic import SubsonicClientError


class FakeClient:
    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self.response = response

    def ping(self) -> dict[str, Any]:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_test_command_reports_a_successful_connection(capsys) -> None:
    app = SubifyApp(
        [
            "test",
            "--url",
            "https://music.example",
            "--username",
            "user",
            "--password",
            "pw",
        ],
        client_factory=lambda _server: FakeClient(
            {"status": "ok", "version": "1.16.1"}
        ),  # type: ignore[arg-type]
    )

    assert app.run() == 0
    assert (
        "OK: connected as 'user', Subsonic API version 1.16.1"
        in capsys.readouterr().out
    )


def test_test_command_reports_client_errors(capsys) -> None:
    app = SubifyApp(
        [
            "test",
            "--url",
            "https://music.example",
            "--username",
            "user",
            "--password",
            "pw",
        ],
        client_factory=lambda _server: FakeClient(SubsonicClientError("denied")),  # type: ignore[arg-type]
    )

    assert app.run() == 1
    assert "FAILED: denied" in capsys.readouterr().err


def test_repeated_verbose_flags_set_the_verbosity_level() -> None:
    servers = []
    app = SubifyApp(
        [
            "test",
            "-vvv",
            "--url",
            "https://music.example",
            "--username",
            "user",
            "--password",
            "pw",
        ],
        client_factory=lambda server: (
            servers.append(server) or FakeClient({"status": "ok"})
        ),  # type: ignore[arg-type]
    )

    assert app.run() == 0
    assert servers[0].verbose == 3
