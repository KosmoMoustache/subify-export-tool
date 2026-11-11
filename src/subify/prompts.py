"""Reusable Questionary prompts for interactive Subify commands."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum

import questionary
from prompt_toolkit.styles import Style

from .match import PlaylistTrack, SubsonicTrack
from .output import track_label

_TRACK_CHOICE_STYLE = Style.from_dict(
    {
        "track-title": "ansicyan",
        "track-artist": "ansigreen",
        "track-album": "ansiyellow",
    }
)


class MatchPromptAction(StrEnum):
    """Actions offered while resolving an ambiguous track match."""

    SELECT = "select"
    SKIP = "skip"
    SEARCH = "search"
    QUIT = "quit"


@dataclass(frozen=True)
class MatchPromptResult:
    """A user's choice from an ambiguous-match prompt."""

    action: MatchPromptAction
    song: SubsonicTrack | None = None


class QuestionaryPrompts:
    """Standard interactive prompts shared by check, sync, and future commands."""

    def select_libraries(self, folders: list[dict]) -> tuple[str, ...] | None:
        """Ask which server libraries should be searched."""
        choices = [
            questionary.Choice(
                title=f"{folder.get('name', '?')} [{folder.get('id', '?')}]",
                value=str(folder["id"]),
            )
            for folder in folders
            if folder.get("id") is not None
        ]
        selected = questionary.checkbox(
            "Select music libraries (leave empty to search all):", choices=choices
        ).ask()
        return tuple(selected) if selected else None

    @staticmethod
    def resume_check(processed_tracks: int) -> bool:
        """Ask whether a partially completed check should be resumed."""
        return bool(
            questionary.confirm(
                f"Resume the previous check after {processed_tracks} track(s)?",
                default=True,
            ).ask()
        )

    def choose_match(
        self, track: PlaylistTrack, candidates: tuple[SubsonicTrack, ...]
    ) -> MatchPromptResult:
        """Present candidates and the shared skip/search/quit actions."""
        choices = []
        if candidates:
            header, labels = self._candidate_table(candidates)
            widths = self._candidate_widths(candidates)
            choices.append(questionary.Separator(header))
            choices.extend(
                questionary.Choice(
                    title=self._candidate_fragments(song, widths),
                    value=MatchPromptResult(MatchPromptAction.SELECT, song),
                )
                for song, _label in zip(candidates, labels, strict=True)
            )
            choices.append(questionary.Separator())
        choices.extend(
            (
                questionary.Choice(
                    title="Skip this track",
                    value=MatchPromptResult(MatchPromptAction.SKIP),
                ),
                questionary.Choice(
                    title="Search with different terms",
                    value=MatchPromptResult(MatchPromptAction.SEARCH),
                ),
                questionary.Choice(
                    title="Quit (save matched tracks and exit)",
                    value=MatchPromptResult(MatchPromptAction.QUIT),
                ),
            )
        )
        selection = questionary.select(
            "Choose a match:",
            choices=choices,
            style=_TRACK_CHOICE_STYLE,
        ).ask()
        return selection or MatchPromptResult(MatchPromptAction.SKIP)

    @classmethod
    def _candidate_table(
        cls, candidates: tuple[SubsonicTrack, ...]
    ) -> tuple[str, list[str]]:
        """Format candidates as a fixed-width table for terminal selection."""
        headers = ("Title", "Artist", "Album", "Duration", "Format", "ID")
        rows = [
            (
                song.title or "?",
                song.artist or "?",
                song.album or "?",
                SubsonicTrack.format_duration(song.duration) or "?",
                song.format or "?",
                song.id or "?",
            )
            for song in candidates
        ]
        widths = cls._candidate_widths(candidates)
        return (
            cls._table_row(headers, widths),
            [cls._table_row(row, widths) for row in rows],
        )

    @classmethod
    def _candidate_widths(cls, candidates: tuple[SubsonicTrack, ...]) -> list[int]:
        headers = ("Title", "Artist", "Album", "Duration", "Format", "ID")
        rows = [cls._candidate_values(song) for song in candidates]
        return [
            max(cls._display_width(value) for value in column)
            for column in zip(headers, *rows, strict=True)
        ]

    @staticmethod
    def _candidate_values(song: SubsonicTrack) -> tuple[str, str, str, str, str, str]:
        return (
            song.title or "?",
            song.artist or "?",
            song.album or "?",
            SubsonicTrack.format_duration(song.duration) or "?",
            song.format or "?",
            song.id or "?",
        )

    @classmethod
    def _candidate_fragments(
        cls, song: SubsonicTrack, widths: list[int]
    ) -> list[tuple[str, str]]:
        """Build a Questionary formatted title with field-specific colours."""
        styles = (
            "class:track-title",
            "class:track-artist",
            "class:track-album",
            "",
            "",
            "",
        )
        fragments: list[tuple[str, str]] = []
        for index, (value, width, style) in enumerate(
            zip(cls._candidate_values(song), widths, styles, strict=True)
        ):
            if index:
                fragments.append(("", " | "))
            fragments.append(
                (style, f"{value}{' ' * (width - cls._display_width(value))}")
            )
        return fragments

    @classmethod
    def _table_row(cls, values: tuple[str, ...], widths: list[int]) -> str:
        return " | ".join(
            f"{value}{' ' * (width - cls._display_width(value))}"
            for value, width in zip(values, widths, strict=True)
        )

    @staticmethod
    def _display_width(value: str) -> int:
        """Return the number of terminal cells required by a Unicode string."""
        return sum(
            0
            if unicodedata.combining(character)
            else 2
            if unicodedata.east_asian_width(character) in {"F", "W"}
            else 1
            for character in value
        )

    @staticmethod
    def search_terms(default: str) -> str | None:
        """Ask for alternate Subsonic search terms, prefilled for editing."""
        return questionary.text("Search Subsonic with:", default=default).ask()

    @staticmethod
    def format_track(track: PlaylistTrack) -> str:
        """Return the common human-readable playlist-track label."""
        return track_label(track.title, "; ".join(track.artists), track.album)

    @staticmethod
    def format_track_plain(track: PlaylistTrack) -> str:
        """Return a label safe for Questionary's interactive controls."""
        return " ".join(
            value
            for value in (track.title, "; ".join(track.artists), track.album)
            if value
        )

    @staticmethod
    def format_song(song: SubsonicTrack) -> str:
        """Return the common human-readable server-track label."""
        label = track_label(song.title, song.artist, song.album)
        if duration := SubsonicTrack.format_duration(song.duration):
            label += f" ({duration})"
        return f"{label} [{song.format or '?'}] #id={song.id}"

    @staticmethod
    def format_song_fragments(song: SubsonicTrack) -> list[tuple[str, str]]:
        """Format a server-track choice without embedding ANSI escapes.

        Questionary renders prompt-toolkit fragments itself, so ANSI sequences
        from :func:`format_song` would otherwise be shown literally.
        """
        fragments = [
            ("class:track-title", song.title or "?"),
            ("", " "),
            ("class:track-artist", song.artist or "?"),
            ("", " "),
            ("class:track-album", song.album or "?"),
        ]
        if duration := SubsonicTrack.format_duration(song.duration):
            fragments.append(("", f" ({duration})"))
        fragments.append(("", f" [{song.format or '?'}] #id={song.id}"))
        return fragments

    @staticmethod
    def choice_style() -> Style:
        """Return the shared style for coloured interactive track choices."""
        return _TRACK_CHOICE_STYLE
