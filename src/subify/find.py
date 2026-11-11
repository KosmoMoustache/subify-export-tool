"""Interactively link one playlist track to a Subsonic track."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import questionary
from prompt_toolkit.completion import Completer, FuzzyCompleter
from prompt_toolkit.document import Document
from questionary.prompts.autocomplete import WordCompleter

from .check import DEFAULT_PLAYLIST, MatchCache, load_playlist
from .config import ServerConfig, add_server_options, server_from_args
from .match import PlaylistTrack, SubsonicTrack
from .prompts import QuestionaryPrompts

DEFAULT_CACHE = Path("match_cache.csv")


class SearchClient(Protocol):
    """The portion of the Subsonic client used by ``find``."""

    def search_tracks(
        self, query: str, *, song_count: int = 20, music_folder_id: str | None = None
    ) -> list[dict]: ...


@dataclass(frozen=True)
class FindConfig:
    server: ServerConfig
    playlist: Path
    cache: Path


class FindAborted(Exception):
    """Raised when the user cancels an interactive find session."""


class _LimitCompleter(Completer):
    """Expose only the highest-ranked completions in an autocomplete menu."""

    def __init__(self, completer: Completer, limit: int) -> None:
        self.completer = completer
        self.limit = limit

    def get_completions(self, document: Document, complete_event):
        yield from list(self.completer.get_completions(document, complete_event))[
            : self.limit
        ]


class FindService:
    """Guide a user through choosing and saving one explicit correspondence."""

    def __init__(self, config: FindConfig, client: SearchClient) -> None:
        self.config = config
        self.client = client
        self.cache = MatchCache(config.cache)

    def run(self) -> tuple[PlaylistTrack, SubsonicTrack]:
        track = self._select_playlist_track(load_playlist(self.config.playlist))
        query = questionary.text(
            "Search Subsonic with:",
            default=" ".join((track.title, "; ".join(track.artists))).strip(),
        ).ask()
        if not query:
            raise FindAborted

        songs = tuple(
            SubsonicTrack.from_api(raw) for raw in self.client.search_tracks(query)
        )
        if not songs:
            raise ValueError(f"No Subsonic tracks found for {query!r}")
        song = self._select_subsonic_track(songs)
        self.cache.put(track, song)
        self.cache.save()
        return track, song

    @staticmethod
    def _select_playlist_track(tracks: list[PlaylistTrack]) -> PlaylistTrack:
        if not tracks:
            raise ValueError("Playlist contains no tracks")
        labels = _unique_labels(tracks)
        choices = list(labels)
        # Questionary's own completer only matches substrings.  Its fuzzy wrapper
        # makes abbreviations such as "dft pnk" useful for long playlists.
        completer = _LimitCompleter(FuzzyCompleter(WordCompleter(choices)), 5)
        selected = questionary.autocomplete(
            "Find a playlist track:", choices=choices, completer=completer
        ).ask()
        if selected is None:
            raise FindAborted
        try:
            return tracks[labels.index(selected)]
        except ValueError as exc:
            raise FindAborted from exc

    @staticmethod
    def _select_subsonic_track(songs: tuple[SubsonicTrack, ...]) -> SubsonicTrack:
        choices = [
            questionary.Choice(
                QuestionaryPrompts.format_song_fragments(song), value=song
            )
            for song in songs
        ]
        selected = questionary.select(
            "Save correspondence with:",
            choices=choices,
            style=QuestionaryPrompts.choice_style(),
        ).ask()
        if selected is None:
            raise FindAborted
        return selected


def _unique_labels(tracks: list[PlaylistTrack]) -> list[str]:
    """Return display labels that retain enough identity for duplicate rows."""
    counts: dict[str, int] = {}
    labels: list[str] = []
    for track in tracks:
        label = QuestionaryPrompts.format_track_plain(track)
        counts[label] = counts.get(label, 0) + 1
        suffix = f" [{counts[label]}]" if counts[label] > 1 else ""
        labels.append(f"{label}{suffix}")
    return labels


def parse_args(argv: list[str]) -> FindConfig:
    """Parse ``subify find`` options."""
    parser = argparse.ArgumentParser(prog="subify find", description=__doc__)
    add_server_options(parser)
    parser.add_argument("--playlist", type=Path, default=DEFAULT_PLAYLIST)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args(argv)
    return FindConfig(
        server=server_from_args(parser, args),
        playlist=args.playlist,
        cache=args.cache,
    )
