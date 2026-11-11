# Subify

Subify is a CLI tool that ease the managment syncing of Spotify playlists to a Subsonic server.

## Global Architecture

Only CLI for the moment, but the architecture is designed to be easily extended to a GUI in the future. The code is organized in a modular way, with clear separation of concerns between the different components. The Subsonic Client is responsible for handling all communication with the Subsonic server, while the CLI handles user input and output. The tests are organized in a separate module to facilitate maintenance and extension of the tests.

Asynchronous and multi-threaded requests are used to avoid blocking the interface and allow the user to continue interacting with the program while requests are being processed.

## Files Definition

- CurrentCheckResume: A text file with the current track being processed, used to resume the operation in case of interruption. (track number)
- CurrentSyncResume: A text file with the current track being processed (track number), used to resume an interrupted sync.
- CredentialsFile: A text file with new lines separated with URL=, USERNAME=, PASSWORD=
- SpotifyPlaylist: A Spotify playlist CSV (Track URI,ISRC,Track Name,Album Name,Artist Name(s),Release Date,Duration (ms),Popularity,Explicit,Added By,Added At,Genres,Record Label,Danceability,Energy,Key,Loudness,Mode,Speechiness,Acousticness,Instrumentalness,Liveness,Valence,Tempo,Time Signature)
- FilePlaylist: A CSV file (ISRC (optional), title, album, artist, duration_ms)
- CheckResult: A CSV file (title, album, artist, status), status can be one of the following:
  - Missing tracks: Tracks that are in the FilePlaylist but not found on the Subsonic server.
  - Format mismatch: Tracks that are found on the Subsonic server but have a different format than expected (e.g., MP3 vs FLAC).
  - Found tracks: Tracks that are found on the Subsonic server and match the expected format.
- SockseekFile: A CSV file(title,artist, album)
- CacheFile: A CSV used in match logic to cache user-confirmed correspondences between input tracks and Subsonic tracks. Its columns are `title,album,artist,subsonic_id`; matching normalizes text fields while preserving their original values in the file.
- WishlistFile: A text file with one line per track that is not found on the Subsonic server or does not match the expected format.
- SyncSummary: A text file new lines separated with the summary of the sync operation, including the number of tracks added, updated, and any errors encountered.

## Module: Subsonic Client

Handle every request to the Subsonic server and provide a simple interface to interact with it.

## Module:CLI

### Commands

General Options: (global options for all commands)

- `--config`: CredentialsFile. (default creds.txt)
- `--url`: URL of the Subsonic server. (overrides the config file)
- `--username`: The username for the Subsonic server. (overrides the config file)
- `--password`: The password for the Subsonic server. (overrides the config file)
- `--timeout`: timeout for the Subsonic client
- `--delay`: delay between requests for the Subsonic client
- `-v`, `--verbose`: show the chosen matching step; repeat for HTTP requests (`-vv`) and API responses (`-vvv`)

- `--library`: Only query the specified library id on the Subsonic server. default to none (options only apply to commands that query the Subsonic server, such as check and sync)
- `--library-select`: interactively choose which music libraries to search on the Subsonic server
- `--list-libraries`: list the music libraries on the server and exit

#### Test

Test the connection to the remote server and check if the credentials are valid.

#### Check

Build a correspondence between the input FilePlaylist and the Subsonic server tracks by reading the input csv and searching tracks on the Subsonic server using the searching functionality. Output a CheckResult file with the results of the check. Take a FilePlaylist and output a CheckResult. When the user quit the program, the current track being processed is saved in the CurrentCheckResume file, so that the user can resume the operation later. If the CurrentCheckResume file exists, the program will ask the user if they want to resume from the last save position or start from the beginning.

Options:

- `--playlist`: The FilePlaylist input file. (default: playlist.csv)
- `--auto-skip`: Whether to automatically skip tracks that are not found on the Subsonic server or don't match the expected format. (default: False)
- `--cache`: CacheFile input (default: False)
- `--result`: CheckResult output file (default: check_result.csv)
- `--format`: expected format for the tracks (default: flac)
<!-- - `--resume`: resume from the last save position (auto-skipping already-processed tracks) -->
<!-- - `--quiet`: suppress per-track progress output -->
<!-- - `--workers`: number of concurrent search requests (default: 8; 1 disables parallelism) -->

#### Convert

Take SpotifyPlaylist and output a FilePlaylist

- `--input`: The SpotifyPlaylist input file. (default: Liked_Songs.csv)
- `--output`: The FilePlaylist output file. (default: playlist.csv)

#### Generate

##### Sockeek

Generate a download list for [Sockseek](https://github.com/fiso64/sockseek), take a CheckResult and output a SockseekFile with the tracks that are not found on the Subsonic server or don't match the expected format.

- `--input`: The CheckResult input file. (default: check_result.csv)
- `--output`: The SockseekFile output file. (default: sockseek_list.csv)
- `--include-format-mismatch`: include tracks with format mismatch in the SockseekFile (default: True)

##### Wishlist

Take a CheckResult and output a WishlistFile with the tracks that are not found on the Subsonic server or don't match the expected format.

- `--input`: The CheckResult input file. (default: check_result.csv)
- `--output`: The WishlistFile output file. (default: wishlist.txt)

#### Sync

Create a playlist (or update if it already exists) on the Subsonic server and add the tracks that are found. The order of the tracks will be the same as in the input FilePlaylist. Track are matches using the same logic as in the Check command. A summary is printed at the end of the operation with the playlist name, server, csv source, library selected, number of tracks, number of track matches with theirs status (cache, auto, manual), number of tracks already, added, removed, reorganized in the playlist, the final playlist size and the listo of skipped tracks. Take a FilePlaylist as input. Output a SyncSummary

- `--input`: The FilePlaylist input file. (default: playlist.csv)
- `--playlist-id`: The playlist id to update on the Subsonic server. If not provided, a new playlist will be created.
- `--playlist-name`: The playlist name
- `--dry-run`: If provided, only print the actions that would be taken without actually updating the playlist
- `--output`: The SyncSummary output file. (default: sync_summary.txt)

## Tests

### Subsonic Client

Test the Subsonic Client with a mocked server to ensure that all requests are handled correctly and the responses are parsed as expected.

## Track matches logic

Match an input track with tracks on the Subsonic server using the following logic:

1. ISRC.
2. Title, artist and album by normalized text inclusion.
3. Title and artist by normalized text inclusion.
4. Title and album by normalized text inclusion.
5. Artist and album by normalized text inclusion, with a duration difference below five seconds.
6. Retry the query with an ASCII-only variant.
7. Optional score matching, enabled with `--score-match`.
8. CacheFile lookup.
9. User confirmation using candidates matching title/artist/album combinations, then free-text search.

When user input is required, save the correspondence in the CacheFile for future use.

The query should have some parameters to filter the search results, such as the library to search in, and the maximum number of results to return. The user should be able to select the correct track from the search results if multiple matches are found, or provide a new input if no match is found.

Example: The track "Song Title" by "Artist Name" from the album "Album Name" is in the input FilePlaylist. If the track is not found, before asking the user, the program will check if the track is in the CacheFile. If not asking the user, and if a result is found by the user on the Subsonic server, save the correspondence in the CacheFile.

```txt
UI of the user input:
 ? '{Query}' id={SUBSONIC TRACK ID }
 Query result
 { RESULT 1}
 { RESULT 2}
 ...
---------------

Skip the trick
Search with differents terms
Quit (save the current position and exit)
```

## DX

Toolings:

- Python
- UV
<!-- - PySide6 for the GUI -->
- asyncio
- thread pools

- Ruff (linter, formatter)
- ty (type checker)
- pytest (test framework)
- pre-commit (run ruff, ty, pytest on pre-commit)

The GUI is an idea for the future, not something that is planned for the moment. The current focus is on the CLI and the core functionality of the tool. The GUI will be designed to be a thin layer on top of the CLI, reusing the same commands and options.
