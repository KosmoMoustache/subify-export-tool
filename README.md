# Subify | Spotify - Subsonic help tool

## How to use

Get your Spotify Playlist export in CSV format (e.g., <https://exportify.net/>), then run:

Convert the Spotify CSV to Subify CSV:

```bash
subify convert
```

Check wich tracks are already in your Subsonic library:

```bash
subify check
```

Generate a wishlist for missing tracks in your library:

```bash
# CSV for input to sockseek
subify generate sockseek

# Newline delimited file
subify generate wishlist
```

Synchronize your Subsonic library with the Spotify playlist:

```bash
subify sync
```
