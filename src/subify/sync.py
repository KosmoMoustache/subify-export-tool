"""Implementation of the ``subify sync`` command."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .check import CheckAborted, CheckConfig, CheckResult, CheckService, load_playlist
from .config import ServerConfig, add_server_options, server_from_args
from .match import normalize_text
from .output import strip_ansi
from .prompts import QuestionaryPrompts
from .resolution import TrackResolutionService

DEFAULT_PLAYLIST = Path("d/playlist.csv")
DEFAULT_OUTPUT = Path("d/sync_summary.txt")
DEFAULT_RESUME = Path("d/resume_sync")


class SyncClient(Protocol):
    def search_tracks(
        self,
        query: str,
        *,
        song_count: int = 20,
        music_folder_id: str | None = None,
    ) -> list[dict]: ...

    def get_music_folders(self) -> list[dict]: ...

    def get_song(self, song_id: str) -> dict | None: ...

    def get_playlists(self) -> list[dict]: ...

    def get_playlist(self, playlist_id: str) -> dict | None: ...

    def create_playlist(
        self,
        *,
        name: str | None = None,
        playlist_id: str | None = None,
        song_ids: list[str],
    ) -> dict | None: ...


@dataclass(frozen=True)
class SyncConfig:
    server: ServerConfig
    input_path: Path
    output_path: Path
    playlist_id: str | None
    playlist_name: str | None
    dry_run: bool
    auto_skip: bool
    cache: Path | None
    library_ids: tuple[str, ...]
    library_select: bool
    list_libraries: bool
    score_match: bool = False
    resume: Path | None = None
    workers: int = 4


@dataclass(frozen=True)
class RemotePlaylist:
    id: str
    name: str
    song_ids: tuple[str, ...]

    @classmethod
    def from_api(cls, raw: dict) -> RemotePlaylist:
        songs = raw.get("entry") or raw.get("song") or []
        return cls(
            id=str(raw.get("id") or ""),
            name=str(raw.get("name") or ""),
            song_ids=tuple(
                str(song.get("id") or "")
                for song in songs
                if isinstance(song, dict) and song.get("id")
            ),
        )


class SyncService:
    """Resolve input tracks, then create or update a remote playlist."""

    def __init__(
        self,
        config: SyncConfig,
        client: SyncClient,
        *,
        prompts: QuestionaryPrompts | None = None,
        output: Callable[[str], None] = print,
    ) -> None:
        self.config = config
        self.client = client
        self.prompts = prompts or QuestionaryPrompts()
        self.output = output
        self._searched_library_ids: tuple[str, ...] = ()

    def run(self) -> list[CheckResult]:
        if self.config.list_libraries:
            self._list_libraries()
            return []
        tracks = load_playlist(self.config.input_path)
        target = self._find_target()
        results = self._resolve_tracks(tracks)
        song_ids = [
            result.song.id for result in results if result.song and result.song.id
        ]
        diff = self._diff(target.song_ids if target else (), song_ids)
        final_playlist, changes_applied = self._apply(target, song_ids)
        summary = self._build_summary(
            target, final_playlist, results, diff, changes_applied, len(song_ids)
        )
        self._write_summary(summary)
        self.output(summary)
        self._clear_resume()
        return results

    def _matching_service(self) -> CheckService:
        return CheckService(
            CheckConfig(
                server=self.config.server,
                playlist=self.config.input_path,
                result=self.config.input_path.with_suffix(".sync-results.csv"),
                expected_format="",
                auto_skip=self.config.auto_skip,
                cache=self.config.cache,
                library_ids=self.config.library_ids,
                library_select=self.config.library_select,
                list_libraries=False,
                score_match=self.config.score_match,
                resume=None,
                workers=self.config.workers,
            ),
            self.client,
            prompts=self.prompts,
            output=self.output,
        )

    def _resolve_tracks(self, tracks: list) -> list[CheckResult]:
        service = self._matching_service()
        service.libraries_for_search()
        self._searched_library_ids = service._selected_library_ids or ()
        resume_after = min(self._read_resume_position(), len(tracks))
        if resume_after and self.prompts.resume_check(resume_after):
            self.output(f"Resuming sync after {resume_after} processed track(s).")
        else:
            resume_after = 0
        resolver = TrackResolutionService(service)
        try:
            return resolver.run(
                tracks,
                resume_after=resume_after,
                on_result=lambda index, _results: self._write_resume_position(index),
            )
        except CheckAborted:
            raise

    def _find_target(self) -> RemotePlaylist | None:
        if self.config.playlist_id:
            raw = self.client.get_playlist(self.config.playlist_id)
            if raw is None:
                raise ValueError(
                    f"Playlist id '{self.config.playlist_id}' was not found"
                )
            return RemotePlaylist.from_api(raw)
        name = self._playlist_name
        summary = next(
            (
                raw
                for raw in self.client.get_playlists()
                if normalize_text(str(raw.get("name") or "")) == normalize_text(name)
            ),
            None,
        )
        if summary is None:
            return None
        playlist_id = str(summary.get("id") or "")
        raw = self.client.get_playlist(playlist_id) if playlist_id else None
        return RemotePlaylist.from_api(raw or summary)

    @property
    def _playlist_name(self) -> str:
        return self.config.playlist_name or self.config.input_path.stem

    def _apply(
        self, target: RemotePlaylist | None, song_ids: list[str]
    ) -> tuple[RemotePlaylist, bool]:
        if self.config.dry_run:
            self.output("DRY RUN: no changes were made to the server.")
            return target or RemotePlaylist("", self._playlist_name, ()), False
        if target and target.song_ids == tuple(song_ids):
            self.output("Playlist is already up to date.")
            return target, False
        raw = (
            self.client.create_playlist(playlist_id=target.id, song_ids=song_ids)
            if target
            else self.client.create_playlist(
                name=self._playlist_name, song_ids=song_ids
            )
        )
        return (
            RemotePlaylist.from_api(
                raw or {"id": target.id if target else "", "name": self._playlist_name}
            ),
            True,
        )

    def _list_libraries(self) -> None:
        self.output(f"Music libraries on {self.config.server.base_url}:")
        for folder in self.client.get_music_folders():
            self.output(f"  {folder.get('id', '?')}  {folder.get('name', '?')}")

    @staticmethod
    def _diff(existing: tuple[str, ...], desired: list[str]) -> dict[str, int]:
        common = sum((Counter(existing) & Counter(desired)).values())
        moved = sum(
            [index for index, song_id in enumerate(existing) if song_id == current]
            != [index for index, song_id in enumerate(desired) if song_id == current]
            for current in set(existing) & set(desired)
        )
        return {
            "already": common,
            "added": len(desired) - common,
            "removed": len(existing) - common,
            "reordered": moved,
        }

    def _library_names(self) -> tuple[str, ...]:
        if not self._searched_library_ids:
            return ()
        names_by_id = {
            str(folder.get("id")): str(folder.get("name") or folder.get("id"))
            for folder in self.client.get_music_folders()
            if folder.get("id") is not None
        }
        return tuple(
            names_by_id.get(library_id, library_id)
            for library_id in self._searched_library_ids
        )

    def _build_summary(
        self,
        old: RemotePlaylist | None,
        final: RemotePlaylist,
        results: list[CheckResult],
        diff: dict[str, int],
        changes_applied: bool,
        final_size: int,
    ) -> str:
        found = sum(result.song is not None for result in results)
        skipped = [result.track for result in results if result.song is None]
        automatic = sum(result.match_source == "automatic" for result in results)
        cached = sum(result.match_source == "cache" for result in results)
        manual = sum(result.match_source == "manual" for result in results)
        old_size = len(old.song_ids) if old else 0
        lines = [
            "=" * 60,
            "SYNC SUMMARY",
            "=" * 60,
            f"Playlist          : {final.name} (id={final.id or 'new'})",
            f"Server            : {self.config.server.base_url}",
            f"CSV source        : {self.config.input_path}",
        ]
        if libraries := self._library_names():
            lines.append("Libraries searched : " + ", ".join(libraries))
        lines.extend(
            (
                f"CSV tracks        : {len(results)}",
                f"Matched           : {found} "
                f"(cache={cached}, auto={automatic}, manual={manual})",
                f"Skipped / not found: {len(skipped)}",
                "-" * 60,
                f"Already in playlist : {diff['already']}",
                f"Added to playlist   : {diff['added']}",
                f"Removed from playlist: {diff['removed']}",
                f"Reordered / moved   : {diff['reordered']}",
                f"Final playlist size : {final_size} (was {old_size})",
                "-" * 60,
                "Changes applied to server : "
                + ("yes" if changes_applied else "NO (dry-run / no change)"),
            )
        )
        if skipped:
            lines.append("Skipped tracks:")
            lines.extend(f"  - {self.prompts.format_track(track)}" for track in skipped)
        lines.append("=" * 60)
        return "\n".join(lines)

    def _write_summary(self, summary: str) -> None:
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.output_path.write_text(strip_ansi(summary) + "\n", encoding="utf-8")

    @property
    def _resume_path(self) -> Path:
        return self.config.resume or self.config.output_path.with_name(
            DEFAULT_RESUME.name
        )

    def _read_resume_position(self) -> int:
        try:
            return max(0, int(self._resume_path.read_text(encoding="utf-8").strip()))
        except (OSError, ValueError):
            return 0

    def _write_resume_position(self, processed_tracks: int) -> None:
        path = self._resume_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{processed_tracks}\n", encoding="utf-8")

    def _clear_resume(self) -> None:
        try:
            self._resume_path.unlink()
        except FileNotFoundError:
            pass


def parse_args(argv: list[str]) -> SyncConfig:
    parser = argparse.ArgumentParser(prog="subify sync", description=__doc__)
    add_server_options(parser)
    parser.add_argument(
        "--input", dest="input_path", type=Path, default=DEFAULT_PLAYLIST
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--playlist-id")
    parser.add_argument("--playlist-name")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--auto-skip", action="store_true")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--workers", type=_positive_int, default=4)
    parser.add_argument("--library", dest="library_ids", action="append", default=[])
    parser.add_argument("--library-select", action="store_true")
    parser.add_argument("--list-libraries", action="store_true")
    parser.add_argument(
        "--score-match", action=argparse.BooleanOptionalAction, default=False
    )
    parser.add_argument("--resume-file", type=Path)
    args = parser.parse_args(argv)
    return SyncConfig(
        server=server_from_args(parser, args),
        input_path=args.input_path,
        output_path=args.output,
        playlist_id=args.playlist_id,
        playlist_name=args.playlist_name,
        dry_run=args.dry_run,
        auto_skip=args.auto_skip,
        cache=args.cache,
        library_ids=tuple(args.library_ids),
        library_select=args.library_select,
        list_libraries=args.list_libraries,
        score_match=args.score_match,
        resume=args.resume_file,
        workers=args.workers,
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed
