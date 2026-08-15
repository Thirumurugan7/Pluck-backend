# Spotify Track Link → MP3 (metadata bridge)

**Date:** 2026-08-15
**Status:** Approved design

## Purpose

Add a second entry point to the local yt2mp3 backend: paste a Spotify **track**
link, get the MP3. Because Spotify audio is DRM-protected and cannot be
downloaded, the audio is sourced from YouTube; the Spotify link is used only to
look up accurate metadata (title, artist, album, cover).

## Scope

**In scope**
- `POST /download/spotify` — form field `url` (a Spotify track link) → streams one MP3.
- Metadata from the official Spotify Web API (client-credentials flow, no user login).
- YouTube match by "artist title" search, choosing the candidate whose duration
  is closest to the Spotify track's duration.
- Reuse existing `download_mp3` for the actual fetch/convert.
- Overwrite tags with Spotify metadata and embed Spotify album cover art.
- `/health` reports whether Spotify credentials are configured.

**Out of scope**
- Album / playlist links (return `400` pointing the user to a track link).
- Any attempt to pull audio from Spotify directly (not possible / not legitimate).
- Web UI (still curl-driven).

## Components

### `spotify.py`
- `is_valid_spotify_track_url(url) -> bool`
  Accepts `https://open.spotify.com/track/{id}` (with optional `/intl-xx/`
  locale segment and query params) and `spotify:track:{id}`. Rejects album/
  playlist/artist links and non-Spotify URLs. No network call.
- `extract_track_id(url) -> str`
  Returns the 22-char base62 track id, or raises `ValueError`.
- `get_access_token() -> str`
  Client-credentials POST to `https://accounts.spotify.com/api/token` using
  `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`. Caches the token in-process
  until shortly before expiry. Raises `SpotifyError` on auth failure / missing creds.
- `get_track_metadata(track_id) -> TrackMeta`
  `GET /v1/tracks/{id}`. Returns `TrackMeta(title, artist, album, duration_ms, cover_url)`
  (artist = primary artist; cover_url = largest album image). Raises `SpotifyError`.
- `spotify_creds_configured() -> bool`
  True if both env vars are present (used by `/health`).
- `TrackMeta` dataclass; `SpotifyError(Exception)`.

### `matcher.py`
- `build_query(meta) -> str` → `f"{artist} {title}"`.
- `search_youtube(query, target_duration_s, n=5) -> str`
  Uses yt-dlp `ytsearch{n}:` (flat/quick metadata) to get candidates, returns
  the watch URL of the one whose duration is closest to `target_duration_s`.
  Falls back to the first result if durations are unavailable. Raises
  `NoMatchError` if the search yields nothing.
- `pick_best_match(candidates, target_duration_s) -> candidate`
  Pure function over `[{"url","duration"}...]`; the unit-testable core of the above.

### `tagging.py`
- `apply_spotify_tags(mp3_path, meta, cover_bytes) -> None`
  Uses `mutagen` to overwrite ID3 title/artist/album and embed `cover_bytes`
  (JPEG) as `APIC`, replacing whatever the YouTube step wrote.
- `fetch_cover(url) -> bytes | None` — download the album cover; None on failure
  (tagging proceeds without a cover rather than failing the request).

### `main.py`
- `POST /download/spotify`
  - `400` if `url` is missing or not a valid Spotify **track** link.
  - `502` on `SpotifyError` (bad/missing creds or API failure) with a clear detail.
  - Resolve metadata → search YouTube → `download_mp3` → `apply_spotify_tags`.
  - `422` on `NoMatchError` or `DownloadError`.
  - Success: `FileResponse` (`audio/mpeg`), `Content-Disposition` filename
    `"{Artist} - {Title}.mp3"` via existing `content_disposition`.
  - `BackgroundTask` removes the temp dir.
- `/health` gains `"spotify": spotify_creds_configured()`. It does **not** make
  `spotify` a hard requirement for `status: ok` (YouTube downloads still work
  without it); it is reported for visibility.

## Data flow

```
curl -> POST /download/spotify (url)
     -> validate spotify track url                 [400]
     -> get_access_token (cached) + get_track_metadata   [502 on Spotify failure]
     -> build_query -> search_youtube(closest duration)  [422 NoMatch]
     -> download_mp3(video_url) -> temp .mp3             [422 DownloadError]
     -> fetch_cover + apply_spotify_tags (mutagen)
     -> FileResponse("Artist - Title.mp3")
     -> BackgroundTask: rmtree(temp)
```

## Configuration

- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` — from a Spotify developer app.
  Read from environment. `run.sh` documents them; README explains obtaining them.

## Error handling

| Situation | Result |
|---|---|
| Missing / non-track / album / playlist link | `400` with guidance |
| Missing or invalid Spotify creds / API error | `502` `{"detail": "..."}` |
| No YouTube match found | `422` |
| Download/convert failure | `422` (yt-dlp reason) |
| Cover fetch fails | tags applied without cover (no request failure) |

## Security notes

- Credentials only from environment; never logged.
- yt-dlp called via Python API on a resolved watch URL (no shell interpolation).
- Reuses `safe_filename` / `content_disposition` for header safety.

## Dependencies (new)

- `requests` — Spotify token/metadata calls and cover download.
- `mutagen` — precise ID3 tagging and cover embedding.

## Testing

- **Unit (offline):**
  - `is_valid_spotify_track_url` / `extract_track_id` — valid track forms
    (incl. `intl-xx`, `spotify:track:`), reject album/playlist/artist/junk.
  - `build_query`, `pick_best_match` (closest-duration, fallback to first, empty → error).
  - `apply_spotify_tags` on a tiny generated MP3 → assert tags/cover round-trip.
- **Integration (opt-in, needs real creds + network):** resolve a known track
  end-to-end, assert a non-empty tagged `.mp3`. Skipped unless
  `YT2MP3_INTEGRATION=1` and creds are set.

## Files

- `spotify.py`, `matcher.py`, `tagging.py` — new.
- `main.py` — add the route + health field.
- `requirements.txt` — add `requests`, `mutagen`.
- `README.md` — Spotify setup + usage.
- `tests/test_spotify.py` — unit tests.
