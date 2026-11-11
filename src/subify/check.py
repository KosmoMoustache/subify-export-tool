"""Find tracks from playlist in a Subsonic Server"""

from __future__ import annotations

import argparse
import csv
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import ServerConfig, add_server_options, server_from_args
from .match import (
    MatchKind,
    MatchResolution,
    PlaylistTrack,
    SubsonicTrack,
    TrackMatcher,
    ascii_variant,
    normalize_text,
)
from .output import verbose
from .prompts import MatchPromptAction, QuestionaryPrompts

DEFAULT_PLAYLIST = Path("d/playlist.csv")
DEFAULT_RESULT = Path("d/check_result.csv")
DEFAULT_RESUME = Path("d/resume_check")


class CheckAborted(Exception):
    """Raised when the user stops an interactive check run."""


class SearchClient(Protocol):
    """The small part of the Subsonic client required by a check."""

    def search_tracks(
        self,
        query: str,
        *,
        song_count: int = 20,
        music_folder_id: str | None = None,
    ) -> list[dict]: ...

    def get_music_folders(self) -> list[dict]: ...

    def get_song(self, song_id: str) -> dict | None: ...


@dataclass(frozen=True)
class CheckConfig:
    """Configuration for one playlist check run."""

    server: ServerConfig
    playlist: Path
    result: Path
    expected_format: str
    auto_skip: bool
    cache: Path | None
    library_ids: tuple[str, ...]
    library_select: bool
    list_libraries: bool
    score_match: bool = False
    resume: Path | None = None
    workers: int = 4


@dataclass(frozen=True)
class CheckResult:
    """A single row in the machine-readable check result file."""

    track: PlaylistTrack
    status: str
    song: SubsonicTrack | None = None
    match_source: str | None = None

    def as_row(self) -> dict[str, str]:
        return {
            "title": self.track.title,
            "album": self.track.album,
            "artist": "; ".join(self.track.artists),
            "status": self.status,
        }


class MatchCache:
    """CSV cache mapping playlist tracks to Subsonic track IDs."""

    fieldnames = ("title", "album", "artist", "subsonic_id")

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._entries: dict[tuple[str, str, str], tuple[tuple[str, str, str], str]] = (
            self._read() if path else {}
        )

    @staticmethod
    def key(track: PlaylistTrack) -> tuple[str, str, str]:
        return (
            normalize_text(track.title),
            normalize_text(track.album),
            normalize_text("; ".join(track.artists)),
        )

    def get(self, track: PlaylistTrack) -> str | None:
        entry = self._entries.get(self.key(track))
        return entry[1] if entry else None

    def put(self, track: PlaylistTrack, song: SubsonicTrack) -> None:
        if self.path and song.id:
            original = (track.title, track.album, "; ".join(track.artists))
            self._entries[self.key(track)] = (original, song.id)

    def save(self) -> None:
        if self.path is None:
            return
        if not self._entries and not self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(
                output, fieldnames=self.fieldnames, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(
                {
                    "title": title,
                    "album": album,
                    "artist": artist,
                    "subsonic_id": song_id,
                }
                for (title, album, artist), song_id in self._entries.values()
            )

    def _read(
        self,
    ) -> dict[tuple[str, str, str], tuple[tuple[str, str, str], str]]:
        if self.path is None:
            return {}
        try:
            source = self.path.open(encoding="utf-8-sig", newline="")
        except OSError:
            return {}
        with source:
            reader = csv.DictReader(source)
            if reader.fieldnames != list(self.fieldnames):
                return {}
            entries = {}
            for row in reader:
                if not all(row.get(field) for field in self.fieldnames):
                    continue
                original = (row["title"], row["album"], row["artist"])
                normalized = (
                    normalize_text(original[0]),
                    normalize_text(original[1]),
                    normalize_text(original[2]),
                )
                entries[normalized] = (original, row["subsonic_id"])
            return entries


def load_playlist(path: Path) -> list[PlaylistTrack]:
    """Read the documented ``title,album,artist`` CSV playlist format."""
    try:
        source = path.open(encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ValueError(f"Could not read playlist {path}: {exc}") from exc
    with source:
        reader = csv.DictReader(source)
        headers = {
            header.casefold().strip(): header for header in reader.fieldnames or []
        }
        required = {"title", "album", "artist"}
        missing = required - headers.keys()
        if missing:
            raise ValueError(
                f"Playlist is missing column(s): {', '.join(sorted(missing))}"
            )
        tracks = []
        for row in reader:
            title = (row.get(headers["title"]) or "").strip()
            artists = tuple(
                artist.strip()
                for artist in (row.get(headers["artist"]) or "").split(";")
                if artist.strip()
            )
            if title:
                tracks.append(
                    PlaylistTrack(
                        title=title,
                        artists=artists,
                        album=(row.get(headers["album"]) or "").strip(),
                        isrc=(row.get(headers.get("isrc", "")) or "").strip() or None,
                        duration_ms=_parse_duration_ms(
                            row.get(headers.get("duration_ms", ""))
                        ),
                    )
                )
    return tracks


def _parse_duration_ms(value: str | None) -> int | None:
    try:
        duration_ms = int(value or "")
    except ValueError:
        return None
    return duration_ms if duration_ms > 0 else None


class CheckService:
    """Check each playlist track against Subsonic search results."""

    def __init__(
        self,
        config: CheckConfig,
        client: SearchClient,
        *,
        matcher: TrackMatcher | None = None,
        prompts: QuestionaryPrompts | None = None,
        output: Callable[[str], None] = print,
    ) -> None:
        self.config = config
        self.client = client
        self.matcher = matcher or TrackMatcher()
        self.cache = MatchCache(config.cache)
        self.prompts = prompts or QuestionaryPrompts()
        self.output = output
        self._selected_library_ids: tuple[str, ...] | None = None

    def run(self) -> list[CheckResult]:
        """Execute the check and write its CSV result."""
        tracks = load_playlist(self.config.playlist)
        results = self._resume_results(tracks)
        from .resolution import TrackResolutionService

        resolver = TrackResolutionService(self)

        def save_result(_index: int, resolved: list[CheckResult]) -> None:
            results.append(resolved[-1])
            self._write_resume_position(len(results))

        try:
            resolver.run(
                tracks[len(results) :],
                start_index=len(results) + 1,
                total=len(tracks),
                on_result=save_result,
            )
        except CheckAborted:
            self.cache.save()
            self._write_results(results)
            self._write_resume_position(len(results))
            self.output(
                f"Saved {len(results)} processed track(s) to {self.config.result}."
            )
            raise
        self.cache.save()
        self._write_results(results)
        self._clear_resume()
        return results

    @property
    def _resume_path(self) -> Path:
        """Return the checkpoint path, beside results for programmatic callers."""
        return self.config.resume or self.config.result.with_name(DEFAULT_RESUME.name)

    def _resume_results(self, tracks: list[PlaylistTrack]) -> list[CheckResult]:
        """Load validated partial results after the user accepts a checkpoint."""
        processed_tracks = self._read_resume_position()
        if not processed_tracks:
            return []
        processed_tracks = min(processed_tracks, len(tracks))
        if not self.prompts.resume_check(processed_tracks):
            return []
        try:
            with self.config.result.open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))
        except OSError:
            self.output(
                "Cannot resume: the partial result file is unavailable; restarting."
            )
            return []
        if len(rows) < processed_tracks or any(
            not self._result_row_matches(track, row)
            for track, row in zip(tracks[:processed_tracks], rows, strict=False)
        ):
            self.output(
                "Cannot resume: the partial result file does not match the playlist; "
                "restarting."
            )
            return []
        self.output(f"Resuming check after {processed_tracks} processed track(s).")
        return [
            CheckResult(track, row["status"])
            for track, row in zip(tracks[:processed_tracks], rows, strict=False)
        ]

    @staticmethod
    def _result_row_matches(track: PlaylistTrack, row: dict[str, str]) -> bool:
        return (
            row.get("title") == track.title
            and row.get("album") == track.album
            and row.get("artist") == "; ".join(track.artists)
            and bool(row.get("status"))
        )

    def _read_resume_position(self) -> int:
        try:
            value = self._resume_path.read_text(encoding="utf-8").strip()
            return max(0, int(value))
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

    def list_libraries(self) -> None:
        """Print the libraries available from the server."""
        folders = self.client.get_music_folders()
        self.output(f"Music libraries on {self.config.server.base_url}:")
        if not folders:
            self.output("  (none reported by the server)")
            return
        for folder in folders:
            self.output(f"  {folder.get('id', '?')}  {folder.get('name', '?')}")

    def resolve_track(
        self,
        track: PlaylistTrack,
        *,
        index: int,
        total: int,
        interactive: bool = True,
        initial_candidates: list[SubsonicTrack] | None = None,
    ) -> CheckResult:
        selected_by_user = False
        match_source: str | None = None
        query = self._query(track)
        candidates = (
            initial_candidates
            if initial_candidates is not None
            else self._search(query)
        )
        resolution = self.matcher.resolve(track, candidates, score_match=False)
        if resolution.match is None:
            ascii_query = ascii_variant(query)
            if ascii_query and ascii_query != query:
                ascii_candidates = self._search(ascii_query)
                candidates = self._merge_candidates(candidates, ascii_candidates)
                resolution = self.matcher.resolve(track, candidates, score_match=False)
        if resolution.match is None and self.config.score_match:
            resolution = self.matcher.resolve(track, candidates, score_match=True)

        song = self._automatic_song(resolution)
        if song is not None and resolution.match is not None:
            match_source = "automatic"
            self._match_verbose(
                index,
                total,
                track,
                self._match_kind_label(resolution.match.kind, resolution.match.score),
            )
        if song is None:
            song = self._cached_song(track, candidates)
            if song is not None:
                match_source = "cache"
                self._match_verbose(index, total, track, "cache")
        if song is None and interactive and not self.config.auto_skip:
            title_candidates = tuple(self._interactive_candidates(track, candidates))
            song = self._resolve_interactively(
                track, title_candidates, query=query, index=index, total=total
            )
            if song is not None:
                selected_by_user = True
                match_source = "manual"
                self._match_verbose(index, total, track, "manual selection")
        if song is None:
            return CheckResult(track, "MISSING")
        if selected_by_user:
            self.cache.put(track, song)
        status = "FOUND" if self._format_matches(song) else "FORMAT-MISMATCH"
        return CheckResult(track, status, song, match_source)

    def search_initial(self, track: PlaylistTrack) -> list[SubsonicTrack]:
        """Perform the primary Subsonic search for one playlist track."""
        return self._search(self._query(track))

    @staticmethod
    def _query(track: PlaylistTrack) -> str:
        return " ".join((track.title, *track.artists)).strip()

    def _search(self, query: str) -> list[SubsonicTrack]:
        library_ids = self.libraries_for_search()
        raw_songs = (
            [
                raw
                for library_id in library_ids
                for raw in self.client.search_tracks(query, music_folder_id=library_id)
            ]
            if library_ids
            else self.client.search_tracks(query)
        )
        seen_ids: set[str] = set()
        songs: list[SubsonicTrack] = []
        for raw in raw_songs:
            song = SubsonicTrack.from_api(raw)
            if song.id and song.id not in seen_ids:
                seen_ids.add(song.id)
                songs.append(song)
        return songs

    def _search_with_ascii_variant(self, query: str) -> list[SubsonicTrack]:
        """Search a query and, only if necessary, its ASCII equivalent."""
        candidates = self._search(query)
        ascii_query = ascii_variant(query)
        if candidates or not ascii_query or ascii_query == query:
            return candidates
        return self._search(ascii_query)

    def _search_all_variants(self, query: str) -> list[SubsonicTrack]:
        """Search both the original query and its ASCII variant when distinct."""
        candidates = self._search(query)
        ascii_query = ascii_variant(query)
        if not ascii_query or ascii_query == query:
            return candidates
        return self._merge_candidates(candidates, self._search(ascii_query))

    def _interactive_candidates(
        self, track: PlaylistTrack, initial: list[SubsonicTrack]
    ) -> list[SubsonicTrack]:
        """Mix broad fallback searches before asking the user to select a track."""
        modified_title = self._modified_title(track.title)
        searches = [
            initial,
            self._search_all_variants(track.title),
        ]
        if modified_title and modified_title != track.title:
            searches.append(self._search_all_variants(modified_title))
        mixed: list[SubsonicTrack] = []
        for search in searches:
            mixed = self._merge_candidates(mixed, search)
        return mixed

    @staticmethod
    def _modified_title(title: str) -> str:
        """Remove parenthesized text and a dash-separated title suffix."""
        without_parentheses = re.sub(r"\s*\([^)]*\)", "", title).strip()
        return re.split(r"\s+-\s+", without_parentheses, maxsplit=1)[0].strip()

    @staticmethod
    def _merge_candidates(
        first: list[SubsonicTrack], second: list[SubsonicTrack]
    ) -> list[SubsonicTrack]:
        seen_ids: set[str] = set()
        merged: list[SubsonicTrack] = []
        for song in [*first, *second]:
            if song.id and song.id not in seen_ids:
                seen_ids.add(song.id)
                merged.append(song)
        return merged

    def libraries_for_search(self) -> tuple[str, ...]:
        if self._selected_library_ids is not None:
            return self._selected_library_ids
        if self.config.library_ids:
            self._selected_library_ids = self.config.library_ids
            return self._selected_library_ids
        if not self.config.library_select:
            self._selected_library_ids = ()
            return self._selected_library_ids

        folders = self.client.get_music_folders()
        if not folders:
            self.output(
                "No music libraries reported by the server; searching all libraries."
            )
            self._selected_library_ids = ()
            return self._selected_library_ids
        selected_ids = self.prompts.select_libraries(folders)
        if not selected_ids:
            self._selected_library_ids = ()
            return self._selected_library_ids
        available_ids = {
            str(folder["id"]) for folder in folders if folder.get("id") is not None
        }
        self._selected_library_ids = tuple(
            library_id for library_id in selected_ids if library_id in available_ids
        )
        if self._selected_library_ids:
            self.output(
                "Search restricted to: " + ", ".join(self._selected_library_ids)
            )
        else:
            self.output("No valid library selected; searching all libraries.")
        return self._selected_library_ids

    def _cached_song(
        self, track: PlaylistTrack, candidates: list[SubsonicTrack]
    ) -> SubsonicTrack | None:
        song_id = self.cache.get(track)
        if not song_id:
            return None
        raw_song = self.client.get_song(song_id)
        if raw_song is not None:
            song = SubsonicTrack.from_api(raw_song)
            if song.id == song_id:
                return song
        return next((song for song in candidates if song.id == song_id), None)

    @staticmethod
    def _automatic_song(resolution: MatchResolution) -> SubsonicTrack | None:
        return resolution.match.song if resolution.match else None

    def _match_verbose(
        self, index: int, total: int, track: PlaylistTrack, method: str
    ) -> None:
        if self.config.server.verbose >= 1:
            self.output(
                verbose(
                    f"[{index}/{total}] matched via {method}: "
                    f"{self.prompts.format_track(track)}"
                )
            )

    @staticmethod
    def _match_kind_label(kind: MatchKind, score: int) -> str:
        labels = {
            MatchKind.ISRC: "ISRC",
            MatchKind.TITLE_ARTIST_ALBUM: "title + artist + album",
            MatchKind.TITLE_ARTIST: "title + artist",
            MatchKind.TITLE_ALBUM: "title + album",
            MatchKind.ARTIST_ALBUM: "artist + album",
        }
        return f"score ({score})" if kind is MatchKind.SCORE else labels[kind]

    def _format_matches(self, song: SubsonicTrack) -> bool:
        return (
            not self.config.expected_format
            or song.format == self.config.expected_format
        )

    def _resolve_interactively(
        self,
        track: PlaylistTrack,
        candidates: tuple[SubsonicTrack, ...],
        *,
        query: str,
        index: int,
        total: int,
    ) -> SubsonicTrack | None:
        """Choose a result, search with new terms, skip, or stop the run."""
        current_candidates = candidates
        while True:
            self.output(
                f"[{index}/{total}] MISSING: {self.prompts.format_track(track)} "
                "(choose a match or skip)"
            )
            selection = self.prompts.choose_match(track, current_candidates)
            if selection.action is MatchPromptAction.SKIP:
                return None
            if selection.action is MatchPromptAction.SELECT:
                return selection.song
            if selection.action is MatchPromptAction.QUIT:
                raise CheckAborted
            new_query = self.prompts.search_terms(query)
            if new_query:
                query = new_query
                current_candidates = tuple(self._search_with_ascii_variant(query))

    def print_result(self, index: int, total: int, result: CheckResult) -> None:
        suffix = f" [{result.song.format or '?'}]" if result.song else ""
        self.output(
            f"[{index}/{total}] {result.status}: "
            f"{self.prompts.format_track(result.track)}{suffix}"
        )

    def _write_results(self, results: list[CheckResult]) -> None:
        self.config.result.parent.mkdir(parents=True, exist_ok=True)
        with self.config.result.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(
                output, fieldnames=["title", "album", "artist", "status"]
            )
            writer.writeheader()
            writer.writerows(result.as_row() for result in results)


def parse_args(argv: list[str]) -> CheckConfig:
    """Parse the active check command options."""
    parser = argparse.ArgumentParser(prog="subify check", description=__doc__)
    add_server_options(parser)
    parser.add_argument(
        "--playlist",
        type=Path,
        default=DEFAULT_PLAYLIST,
        help=f"Input playlist file (default: {DEFAULT_PLAYLIST})",
    )
    parser.add_argument(
        "--result",
        type=Path,
        default=DEFAULT_RESULT,
        help=f"(default: {DEFAULT_RESULT})",
    )
    parser.add_argument(
        "--auto-skip",
        action="store_true",
        help="skip unresolvable tracks without prompting",
    )
    parser.add_argument(
        "--score-match",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="enable score-based automatic matching after exact rules",
    )
    parser.add_argument("--cache", type=Path, help="match cache file")
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=4,
        help="concurrent Subsonic search requests (default: 4; use 1 to disable)",
    )
    parser.add_argument(
        "--resume-file",
        type=Path,
        default=None,
        help=(
            "checkpoint file used to resume an interrupted check "
            f"(default: {DEFAULT_RESUME} beside the result file)"
        ),
    )
    parser.add_argument(
        "--format",
        dest="expected_format",
        default="flac",
        help="expected audio format, e.g. flac, mp3; "
        "mismatch will be reported as FORMAT-MISMATCH (default: flac)",
    )
    parser.add_argument(
        "--library",
        dest="library_ids",
        action="append",
        default=[],
        help="only search this music library ID (repeatable)",
    )
    parser.add_argument(
        "--library-select",
        action="store_true",
        help="interactively choose music libraries to search",
    )
    parser.add_argument(
        "--list-libraries",
        action="store_true",
        help="list music libraries on the server and exit",
    )
    args = parser.parse_args(argv)
    return CheckConfig(
        server=server_from_args(parser, args),
        playlist=args.playlist,
        result=args.result,
        expected_format=args.expected_format.casefold(),
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
