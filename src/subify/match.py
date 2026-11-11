"""Pure track-matching rules used by the future ``check`` and ``sync`` commands.

Network searches, cache persistence, and interactive selection intentionally do
not belong here.  This module only decides which candidates are safe to match
automatically and which must be confirmed by a user.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


def normalize_text(value: str) -> str:
    """Return a comparison key independent of case, accents, and whitespace."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(without_marks.casefold().split())


def normalize_isrc(value: str | None) -> str:
    """Return a compact ISRC comparison key, or an empty string when absent."""
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


@dataclass(frozen=True)
class PlaylistTrack:
    """The match-relevant fields of a track imported from a playlist."""

    title: str
    artists: tuple[str, ...]
    album: str = ""
    isrc: str | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class SubsonicTrack:
    """The match-relevant fields returned by a Subsonic-compatible server."""

    id: str
    title: str
    artist: str
    album: str = ""
    isrc: str | None = None
    duration: int | None = None
    format: str = ""

    @classmethod
    def from_api(cls, raw: dict[str, object]) -> SubsonicTrack:
        """Create a track from a ``search3`` song payload."""
        content_type = str(raw.get("contentType") or "").split(";", 1)[0]
        detected_format = str(raw.get("suffix") or content_type.rsplit("/", 1)[-1])
        return cls(
            id=str(raw.get("id") or ""),
            title=str(raw.get("title") or ""),
            artist=str(raw.get("artist") or ""),
            album=str(raw.get("album") or ""),
            isrc=str(raw.get("isrc") or "") or None,
            duration=cls._parse_duration(raw.get("duration")),
            format=detected_format.casefold(),
        )

    @staticmethod
    def _parse_duration(value: object) -> int | None:
        try:
            duration = int(str(value or ""))
        except ValueError:
            return None
        return duration if duration > 0 else None

    @staticmethod
    def format_duration(seconds: int | None) -> str:
        if seconds is None or seconds <= 0:
            return ""
        return f"{seconds // 60}:{seconds % 60:02d}"


class MatchKind(StrEnum):
    """The rule that established a match."""

    ISRC = "isrc"
    TITLE_ARTIST_ALBUM = "title_artist_album"
    TITLE_ARTIST = "title_artist"
    TITLE_ALBUM = "title_album"
    ARTIST_ALBUM = "artist_album"
    SCORE = "score"


@dataclass(frozen=True)
class TrackMatch:
    """A safe automatic match between a playlist and server track."""

    track: PlaylistTrack
    song: SubsonicTrack
    kind: MatchKind
    score: int = 0


@dataclass(frozen=True)
class MatchResolution:
    """Automatic result or candidates that require user confirmation."""

    match: TrackMatch | None = None
    confirmation_candidates: tuple[SubsonicTrack, ...] = ()

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.confirmation_candidates)


class TrackMatcher:
    """Resolve server candidates according to Subify's matching priority."""

    score_threshold = 50
    duration_tolerance_ms = 5_000

    def resolve(
        self,
        track: PlaylistTrack,
        candidates: list[SubsonicTrack],
        *,
        score_match: bool = False,
    ) -> MatchResolution:
        """Return the first unambiguous automatic match or title-only candidates."""
        candidates = self._unique_candidates(candidates)

        isrc_match = self._by_isrc(track, candidates)
        if isrc_match is not None:
            return MatchResolution(TrackMatch(track, isrc_match, MatchKind.ISRC))

        title_artist_album_match = self._by_title_artist_album(track, candidates)
        if title_artist_album_match is not None:
            return MatchResolution(
                TrackMatch(
                    track, title_artist_album_match, MatchKind.TITLE_ARTIST_ALBUM
                )
            )

        title_artist_match = self._by_title_artist(track, candidates)
        if title_artist_match is not None:
            return MatchResolution(
                TrackMatch(track, title_artist_match, MatchKind.TITLE_ARTIST)
            )

        title_album_match = self._by_title_album(track, candidates)
        if title_album_match is not None:
            return MatchResolution(
                TrackMatch(track, title_album_match, MatchKind.TITLE_ALBUM)
            )

        artist_album_match = self._by_artist_album(track, candidates)
        if artist_album_match is not None:
            return MatchResolution(
                TrackMatch(track, artist_album_match, MatchKind.ARTIST_ALBUM)
            )

        if score_match:
            scored_match = self._by_score(track, candidates)
            if scored_match is not None:
                song, score = scored_match
                return MatchResolution(TrackMatch(track, song, MatchKind.SCORE, score))

        return MatchResolution(
            confirmation_candidates=self.confirmation_candidates(track, candidates)
        )

    def confirmation_candidates(
        self, track: PlaylistTrack, candidates: list[SubsonicTrack]
    ) -> tuple[SubsonicTrack, ...]:
        """Return partial matches suitable for explicit user confirmation."""
        return tuple(
            song
            for song in self._unique_candidates(candidates)
            if self._title_matches(track, song)
            or self._artist_matches(track, song)
            and self._album_matches(track, song)
        )

    @staticmethod
    def _unique_candidates(candidates: list[SubsonicTrack]) -> list[SubsonicTrack]:
        seen_ids: set[str] = set()
        unique: list[SubsonicTrack] = []
        for candidate in candidates:
            if candidate.id and candidate.id not in seen_ids:
                seen_ids.add(candidate.id)
                unique.append(candidate)
        return unique

    @staticmethod
    def _included_text(left: str, right: str) -> bool:
        left_normalized = normalize_text(left)
        right_normalized = normalize_text(right)
        return bool(left_normalized and right_normalized) and (
            left_normalized in right_normalized or right_normalized in left_normalized
        )

    def _by_title_artist_album(
        self, track: PlaylistTrack, candidates: list[SubsonicTrack]
    ) -> SubsonicTrack | None:
        return next(
            (
                song
                for song in candidates
                if self._title_matches(track, song)
                and self._artist_matches(track, song)
                and self._album_matches(track, song)
            ),
            None,
        )

    @staticmethod
    def _by_isrc(
        track: PlaylistTrack, candidates: list[SubsonicTrack]
    ) -> SubsonicTrack | None:
        isrc = normalize_isrc(track.isrc)
        if not isrc:
            return None
        return next(
            (song for song in candidates if normalize_isrc(song.isrc) == isrc), None
        )

    def _by_title_artist(
        self, track: PlaylistTrack, candidates: list[SubsonicTrack]
    ) -> SubsonicTrack | None:
        for song in candidates:
            if self._title_matches(track, song) and self._artist_matches(track, song):
                return song
        return None

    def _by_title_album(
        self, track: PlaylistTrack, candidates: list[SubsonicTrack]
    ) -> SubsonicTrack | None:
        return next(
            (
                song
                for song in candidates
                if self._title_matches(track, song) and self._album_matches(track, song)
            ),
            None,
        )

    def _by_artist_album(
        self, track: PlaylistTrack, candidates: list[SubsonicTrack]
    ) -> SubsonicTrack | None:
        for song in candidates:
            if (
                self._artist_matches(track, song)
                and self._album_matches(track, song)
                and self._duration_matches(track, song)
            ):
                return song
        return None

    def _title_matches(self, track: PlaylistTrack, song: SubsonicTrack) -> bool:
        return self._included_text(track.title, song.title)

    def _artist_matches(self, track: PlaylistTrack, song: SubsonicTrack) -> bool:
        return any(self._included_text(artist, song.artist) for artist in track.artists)

    def _album_matches(self, track: PlaylistTrack, song: SubsonicTrack) -> bool:
        return self._included_text(track.album, song.album)

    def _duration_matches(self, track: PlaylistTrack, song: SubsonicTrack) -> bool:
        return (
            track.duration_ms is not None
            and song.duration is not None
            and abs(track.duration_ms - song.duration * 1_000)
            < self.duration_tolerance_ms
        )

    def _by_score(
        self, track: PlaylistTrack, candidates: list[SubsonicTrack]
    ) -> tuple[SubsonicTrack, int] | None:
        scored_candidates = [(song, self._score(track, song)) for song in candidates]
        if not scored_candidates:
            return None
        song, score = max(scored_candidates, key=lambda candidate: candidate[1])
        return (song, score) if score >= self.score_threshold else None

    def _score(self, track: PlaylistTrack, song: SubsonicTrack) -> int:
        """Score a candidate with the legacy title/artist heuristic."""
        score = self._text_score(track.title, song.title, exact=40, partial=20)
        artist_scores = [
            self._text_score(artist, song.artist, exact=30, partial=12)
            for artist in track.artists
            if normalize_text(artist)
        ]
        score += max(artist_scores) if artist_scores else 0
        if track.duration_ms is not None and song.duration is not None:
            difference = abs(track.duration_ms - song.duration * 1_000)
            if difference < 5_000:
                score += 15
            elif difference < 30_000:
                score += 5
            else:
                score -= 15
        return score

    @staticmethod
    def _text_score(expected: str, actual: str, *, exact: int, partial: int) -> int:
        expected_normalized = normalize_text(expected)
        actual_normalized = normalize_text(actual)
        if not expected_normalized or not actual_normalized:
            return -25
        if expected_normalized == actual_normalized:
            return exact
        if TrackMatcher._included_text(expected, actual):
            return partial
        if len(set(expected_normalized.split()) & set(actual_normalized.split())) >= 2:
            return partial
        return -25


def ascii_variant(value: str) -> str:
    """Return an ASCII-only search variant while preserving readable letters."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    return decomposed.encode("ascii", "ignore").decode("ascii")
