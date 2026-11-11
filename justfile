set shell := ["pwsh", "-NoProfile", "-Command"]
set positional-arguments := true
set script-interpreter := ["pwsh", "-NoProfile", "-File"]

# run the initial rewrite quality gate locally
quality:
    uv run python -m ruff check .
    uv run python -m ruff format --check .
    uv run python -m ty check src/subify
    uv run python -m pytest

format:
    uv run python -m ruff format .

# Test connection to Subsonic server
[script]
test-test *args:
    & uv run python -m subify test @args

# Test connection to Subsonic server using creds.test.txt crendentials
[script]
test *args:
    & uv run python -m subify test --config creds.test.txt @args

# convert a Spotify CSV export to a Subify playlist CSV
[script]
convert *args:
    & uv run python -m subify convert @args

# check which tracks from a Spotify CSV are missing on the server
[script]
check *args:
    & uv run python -m subify check @args

# interactively save a playlist-to-Subsonic track correspondence
[script]
find *args:
    & uv run python -m subify find @args

# generate Sockseek or wishlist files from check results
[script]
generate *args:
    & uv run python -m subify generate @args

# create or update a Subsonic playlist from a playlist CSV
[script]
sync *args:
    & uv run python -m subify sync @args
