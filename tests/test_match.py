from __future__ import annotations

from subify.match import (
    MatchKind,
    PlaylistTrack,
    SubsonicTrack,
    TrackMatcher,
    normalize_text,
)


def song(
    id: str,
    title: str,
    artist: str,
    album: str = "",
    isrc: str | None = None,
) -> SubsonicTrack:
    return SubsonicTrack(id, title, artist, album, isrc)


def test_isrc_match_has_priority_over_all_other_rules() -> None:
    track = PlaylistTrack(
        "Correct title", ("Correct artist",), "Correct album", "US-ABC-12-34567"
    )
    candidates = [
        song("all-fields", "Correct title", "Correct artist", "Correct album"),
        song("isrc", "Different title", "Different artist", isrc="usabc1234567"),
    ]

    resolution = TrackMatcher().resolve(track, candidates)

    assert resolution.match is not None
    assert resolution.match.song.id == "isrc"
    assert resolution.match.kind is MatchKind.ISRC


def test_title_and_artist_match_is_accent_and_case_insensitive() -> None:
    track = PlaylistTrack("Beyonce Song", ("BEYONCÉ",))
    candidate = song("1", "Beyoncé Song", "Beyoncé")

    resolution = TrackMatcher().resolve(track, [candidate])

    assert resolution.match is not None
    assert resolution.match.kind is MatchKind.TITLE_ARTIST
    assert resolution.match.song == candidate


def test_artist_and_album_match_is_used_after_title_artist() -> None:
    track = PlaylistTrack(
        "Album version", ("The Artist",), "The Album", duration_ms=180_000
    )
    candidate = SubsonicTrack(
        "1", "Different title", "the artist", "THE ALBUM", duration=180
    )

    resolution = TrackMatcher().resolve(track, [candidate])

    assert resolution.match is not None
    assert resolution.match.kind is MatchKind.ARTIST_ALBUM


def test_match_uses_inclusion_rules_in_the_documented_order() -> None:
    track = PlaylistTrack("Song", ("The Artist",), "The Album", duration_ms=180_000)
    candidates = [
        song("artist-album", "Different title", "The Artist", "The Album"),
        song("title-album", "Song (Live)", "Other Artist", "The Album Deluxe"),
        song("title-artist", "Song (Live)", "The Artist feat. Guest", "Other"),
        song(
            "all-fields",
            "Song (Live)",
            "The Artist feat. Guest",
            "The Album Deluxe",
        ),
    ]

    resolution = TrackMatcher().resolve(track, candidates)

    assert resolution.match is not None
    assert resolution.match.song.id == "all-fields"
    assert resolution.match.kind.value == "title_artist_album"


def test_title_artist_and_title_album_matches_accept_included_text() -> None:
    track = PlaylistTrack("Song", ("The Artist",), "The Album")
    title_artist = song("title-artist", "Song (Live)", "The Artist feat. Guest")
    title_album = song("title-album", "Song (Live)", "Other", "The Album Deluxe")

    title_artist_resolution = TrackMatcher().resolve(track, [title_artist])
    title_album_resolution = TrackMatcher().resolve(track, [title_album])

    assert title_artist_resolution.match is not None
    assert title_artist_resolution.match.kind.value == "title_artist"
    assert title_album_resolution.match is not None
    assert title_album_resolution.match.kind.value == "title_album"


def test_artist_album_match_requires_a_duration_within_five_seconds() -> None:
    track = PlaylistTrack("Song", ("The Artist",), "The Album", duration_ms=180_000)
    close_duration = SubsonicTrack(
        "close",
        "Different title",
        "The Artist feat. Guest",
        "The Album Deluxe",
        duration=184,
    )
    far_duration = SubsonicTrack(
        "far",
        "Different title",
        "The Artist feat. Guest",
        "The Album Deluxe",
        duration=186,
    )

    close_resolution = TrackMatcher().resolve(track, [close_duration])
    far_resolution = TrackMatcher().resolve(track, [far_duration])

    assert close_resolution.match is not None
    assert close_resolution.match.kind.value == "artist_album"
    assert far_resolution.match is None
    assert far_resolution.confirmation_candidates == (far_duration,)


def test_title_only_candidates_require_confirmation() -> None:
    track = PlaylistTrack("Same title", ("Wanted artist",))
    candidate = song("1", "same title", "Other artist")

    resolution = TrackMatcher().resolve(track, [candidate])

    assert resolution.match is None
    assert resolution.needs_confirmation
    assert resolution.confirmation_candidates == (candidate,)


def test_score_matching_is_opt_in_and_uses_the_best_candidate() -> None:
    track = PlaylistTrack("Song", ("The Artist",))
    candidate = song("1", "Song", "Artist The feat. Guest")

    without_score = TrackMatcher().resolve(track, [candidate])
    with_score = TrackMatcher().resolve(track, [candidate], score_match=True)

    assert without_score.match is None
    assert with_score.match is not None
    assert with_score.match.kind is MatchKind.SCORE
    assert with_score.match.song == candidate
    assert with_score.match.score == 52


def test_normalize_text_removes_accents_and_collapses_whitespace() -> None:
    assert normalize_text("  Café\u00a0DÓLOR  ") == "cafe dolor"


def test_perso() -> None:
    track = PlaylistTrack("Pop Corn", ("Marsheaux",), "Ebay Queen")
    candidate = song("1", "Pop Corn", "Marsheaux", "Eaby Queen")

    resolution = TrackMatcher().resolve(track, [candidate])

    assert resolution.match is not None
    assert resolution.match.kind is MatchKind.TITLE_ARTIST
    assert resolution.match.song == candidate
