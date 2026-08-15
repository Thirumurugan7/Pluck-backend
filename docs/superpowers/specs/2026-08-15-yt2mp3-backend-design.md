# yt2mp3 — Local YouTube→MP3 Backend

**Date:** 2026-08-15
**Status:** Approved design

## Purpose

A personal, local backend that turns a YouTube link into a tagged 320 kbps MP3.
Single user, runs on the author's Mac, driven from the terminal with `curl`.
No web frontend, no deployment.

## Scope

**In scope**
- One FastAPI service bound to `127.0.0.1`.
- `POST /download` — accepts a YouTube URL, returns the finished `.mp3` bytes.
- `GET /health` — reports whether `ffmpeg` is available.
- 320 kbps MP3 output (fixed).
- Embedded ID3 metadata (title, artist) and cover art from the video thumbnail.
- Response filename derived from the sanitized video title.

**Out of scope (deliberately)**
- Web page / UI.
- Playlist handling / zip output.
- Per-request bitrate selection.
- Authentication (localhost, single user).
- Deployment / always-on hosting.

## Stack & dependencies

- **Python 3.11+**, **FastAPI**, **uvicorn**.
- **yt-dlp** used as a Python library (not shelled out) — avoids command injection and gives structured info.
- **ffmpeg** (installed via Homebrew) — invoked by yt-dlp's post-processors for audio extraction, metadata, and thumbnail embedding.

## Components

### `downloader.py`
Pure-ish module holding the download logic and small helpers, so the web layer stays thin and the helpers are unit-testable.

- `is_valid_youtube_url(url: str) -> bool`
  Accepts standard YouTube forms: `youtube.com/watch?v=<id>`, `youtu.be/<id>`, `youtube.com/shorts/<id>`, with or without `https://` / `www.`, and extra query params. Rejects anything else. No network call.
- `safe_filename(title: str) -> str`
  Strips path separators and characters illegal on macOS/HTTP headers, collapses whitespace, trims length (~150 chars), guarantees a non-empty fallback (`"audio"`). Always ends in `.mp3` at the call site.
- `download_mp3(url: str, workdir: Path) -> DownloadResult`
  Runs yt-dlp into `workdir` with:
  - `format="bestaudio/best"`
  - post-processors: `FFmpegExtractAudio` (codec `mp3`, quality `320`), `FFmpegMetadata`, `EmbedThumbnail`
  - `writethumbnail=True`, `outtmpl` into `workdir`
  Returns `DownloadResult(path: Path, title: str)` — the path to the produced `.mp3` and the info-dict title.
  Raises `DownloadError(message)` on any yt-dlp failure (unavailable/private/age-restricted/network).

### `main.py`
FastAPI app and HTTP concerns only.

- `POST /download`
  - Form field `url` (required).
  - `400` if `url` missing or `is_valid_youtube_url` is false.
  - Creates a temp dir, calls `download_mp3`.
  - `422` with the error message if `DownloadError` is raised.
  - On success: `FileResponse` (media type `audio/mpeg`) with
    `Content-Disposition: attachment; filename="<safe_filename(title)>.mp3"`.
  - Registers a `BackgroundTask` that removes the temp dir after the response is sent.
- `GET /health`
  - Returns `{"status": "ok", "ffmpeg": true}` if `ffmpeg` resolves on PATH, else `{"status": "degraded", "ffmpeg": false}` with `503`.
- Startup: log a clear warning if `ffmpeg` is not found.
- App binds to `127.0.0.1` (enforced in `run.sh` / uvicorn args).

## Data flow

```
curl -> POST /download (url)
     -> validate url                       [400 on bad input]
     -> mkdtemp workdir
     -> yt-dlp bestaudio + ffmpeg pp        [422 on download failure]
        (extract mp3 320k, write tags, embed cover)
     -> locate produced .mp3, read title
     -> FileResponse(mp3, filename from title)
     -> BackgroundTask: rmtree(workdir)
```

## Error handling

| Situation | Result |
|---|---|
| Missing / non-YouTube `url` | `400` `{"detail": "..."}` |
| Video unavailable / private / age-restricted / network error | `422` `{"detail": "<yt-dlp reason>"}` |
| ffmpeg missing | `/health` → `503`; startup logs a clear install hint |
| Unexpected server error | `500` (FastAPI default), temp dir still cleaned up |

## Security notes

- Bind to `127.0.0.1` only — not reachable off the machine.
- yt-dlp called via its Python API with a parsed URL; no shell string interpolation.
- `safe_filename` prevents header injection / path traversal in `Content-Disposition`.
- Temp dir per request, always removed via `BackgroundTask`.

## Testing

- **Unit (offline, default):**
  - `is_valid_youtube_url` — accepts the supported forms, rejects junk / non-YouTube / empty.
  - `safe_filename` — strips separators & illegal chars, handles unicode, empties → `"audio"`, length cap.
- **Integration (opt-in, skipped by default):** one test that downloads a known short public video and asserts a non-empty `.mp3` with an audio MIME type. Marked so the default suite stays offline and fast.

## Files

- `main.py` — FastAPI app, routes, HTTP concerns.
- `downloader.py` — url validation, filename sanitizer, yt-dlp download.
- `requirements.txt` — `fastapi`, `uvicorn`, `yt-dlp` (+ test deps).
- `run.sh` — `uvicorn main:app --host 127.0.0.1 --port 8000`.
- `README.md` — prerequisites (`brew install ffmpeg`), install, run, and the `curl` example.

## Usage (target)

```
$ ./run.sh
$ curl -X POST localhost:8000/download \
    --data-urlencode "url=https://youtu.be/dQw4w9WgXcQ" \
    -OJ                       # -OJ = save using the server's filename
-> Rick Astley - Never Gonna Give You Up.mp3
```
