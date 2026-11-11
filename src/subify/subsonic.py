"""HTTP client for the Subsonic REST API."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping
from typing import Any

import requests

from .config import ServerConfig
from .output import verbose

API_VERSION = "1.16.1"


class SubsonicClientError(RuntimeError):
    """A transport or application-level error from a Subsonic server."""


class SubsonicClient:
    """Minimal typed client used by active Subify commands."""

    def __init__(
        self,
        server: ServerConfig,
        *,
        client_name: str = "subify",
        session: requests.Session | None = None,
    ) -> None:
        self.server = server
        self.client_name = client_name
        self.session = session
        self._thread_local = threading.local()
        self._request_lock = threading.Lock()
        self._last_request_at: float | None = None

    def _verbose(self, message: str, *, level: int = 1) -> None:
        """Print diagnostics without exposing authentication parameters."""
        if self.server.verbose >= level:
            print(verbose(message))

    def _base_params(self) -> dict[str, str]:
        return {
            "u": self.server.username,
            "p": self.server.password,
            "v": API_VERSION,
            "c": self.client_name,
            "f": "json",
        }

    def _reserve_request_slot(self) -> None:
        """Rate-limit request starts safely while allowing requests to overlap."""
        with self._request_lock:
            if self._last_request_at is not None and self.server.delay > 0:
                remaining = self.server.delay - (
                    time.monotonic() - self._last_request_at
                )
                if remaining > 0:
                    time.sleep(remaining)
            self._last_request_at = time.monotonic()

    def _session_for_request(self) -> requests.Session:
        """Use one session per worker; injected sessions stay deterministic in tests."""
        if self.session is not None:
            return self.session
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            self._thread_local.session = session
        return session

    def _request(self, endpoint: str, params: Mapping[str, Any]) -> dict[str, Any]:
        self._reserve_request_slot()
        self._verbose(f"GET /rest/{endpoint} params={dict(params)!r}", level=2)
        try:
            response = self._session_for_request().get(
                f"{self.server.base_url}/rest/{endpoint}",
                params={**self._base_params(), **params},
                timeout=self.server.timeout,
            )
        except requests.RequestException as exc:
            raise SubsonicClientError(
                f"Could not reach /rest/{endpoint}: {exc}"
            ) from exc
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text[:300]
            raise SubsonicClientError(
                f"HTTP {response.status_code} on /rest/{endpoint}: {detail}"
            ) from exc
        try:
            data = response.json()["subsonic-response"]
        except (KeyError, TypeError, ValueError) as exc:
            raise SubsonicClientError(
                f"Invalid JSON returned by /rest/{endpoint}"
            ) from exc
        if data.get("status") != "ok":
            message = data.get("error", {}).get("message", "unknown server error")
            raise SubsonicClientError(f"Subsonic error on /rest/{endpoint}: {message}")
        self._verbose(
            f"GET /rest/{endpoint} completed with HTTP {response.status_code}",
            level=2,
        )
        response_json = json.dumps(data, ensure_ascii=False, sort_keys=True)
        self._verbose(f"GET /rest/{endpoint} response={response_json}", level=3)
        return data

    def ping(self) -> dict[str, Any]:
        """Verify connectivity and credentials."""
        return self._request("ping", {})

    def search_tracks(
        self, query: str, *, song_count: int = 20, music_folder_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Search server tracks, optionally restricting the music library."""
        params: dict[str, Any] = {
            "query": query,
            "songCount": song_count,
            "artistCount": 0,
            "albumCount": 0,
        }
        if music_folder_id is not None:
            params["musicFolderId"] = music_folder_id
        result = self._request("search3", params)
        songs = result.get("searchResult3", {}).get("song", [])
        return songs if isinstance(songs, list) else []

    def get_music_folders(self) -> list[dict[str, Any]]:
        """Return music libraries exposed by the server."""
        result = self._request("getMusicFolders", {})
        folders = result.get("musicFolders", {}).get("musicFolder", [])
        return folders if isinstance(folders, list) else []

    def get_song(self, song_id: str) -> dict[str, Any] | None:
        """Return one server track by ID, if the server still exposes it."""
        result = self._request("getSong", {"id": song_id})
        song = result.get("song")
        return song if isinstance(song, dict) else None

    def get_playlists(self) -> list[dict[str, Any]]:
        """Return playlists owned by or visible to the current user."""
        result = self._request("getPlaylists", {})
        playlists = result.get("playlists", {}).get("playlist", [])
        return playlists if isinstance(playlists, list) else []

    def get_playlist(self, playlist_id: str) -> dict[str, Any] | None:
        """Return a playlist, including its ordered song list."""
        result = self._request("getPlaylist", {"id": playlist_id})
        playlist = result.get("playlist")
        return playlist if isinstance(playlist, dict) else None

    def create_playlist(
        self,
        *,
        name: str | None = None,
        playlist_id: str | None = None,
        song_ids: list[str],
    ) -> dict[str, Any] | None:
        """Create a playlist or replace the songs of an existing playlist."""
        params: dict[str, Any] = {"songId": song_ids}
        if playlist_id:
            params["playlistId"] = playlist_id
        elif name:
            params["name"] = name
        else:
            raise ValueError("a playlist name or ID is required")
        result = self._request("createPlaylist", params)
        playlist = result.get("playlist")
        return playlist if isinstance(playlist, dict) else None
