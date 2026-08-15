# yt2mp3

A tiny local backend that turns a YouTube link into a tagged 320 kbps MP3.
Runs on your Mac, on `127.0.0.1` only. You drive it with `curl`.

## Prerequisites

- Python 3.11+
- ffmpeg — for the MP3 conversion and tag/cover embedding
- deno (or node/bun) — a JavaScript runtime yt-dlp uses to decipher YouTube
  stream signatures. Without it, many current videos fail with `HTTP 403`.

```bash
brew install ffmpeg deno
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
./run.sh
```

Serves on `http://127.0.0.1:8000`.

## Use

Download a video as an MP3, saving it with the video's title as the filename
(`-OJ` tells curl to use the server-provided filename):

```bash
curl -X POST http://127.0.0.1:8000/download \
  --data-urlencode "url=https://youtu.be/dQw4w9WgXcQ" \
  -OJ
```

### Spotify track links

Paste a Spotify **track** link. The backend reads the track's metadata from the
Spotify API, finds the matching audio on YouTube, downloads it, and tags the MP3
with Spotify's title/artist/album and album cover. (Spotify audio is DRM'd and
can't be downloaded directly — the audio comes from YouTube.)

```bash
curl -X POST http://127.0.0.1:8000/download/spotify \
  --data-urlencode "url=https://open.spotify.com/track/XXXXXXXXXXXXXXXXXXXXXX" \
  -OJ
```

This needs Spotify API credentials. Create a free app at
<https://developer.spotify.com/dashboard>, copy its Client ID and Client Secret,
and export them before running (no redirect URI or user login needed):

```bash
export SPOTIFY_CLIENT_ID=your_client_id
export SPOTIFY_CLIENT_SECRET=your_client_secret
./run.sh
```

Check that ffmpeg is available:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","ffmpeg":true,"js_runtime":true,"spotify":true}
```

## API

| Method | Path                | Returns |
|--------|---------------------|---------|
| `GET`  | `/health`           | Dependency status (ffmpeg, JS runtime, Spotify creds) |
| `POST` | `/resolve`          | JSON metadata for a YouTube link — no download |
| `POST` | `/resolve/spotify`  | JSON track metadata **plus** the YouTube video that would supply the audio |
| `POST` | `/download`         | The MP3, named after the video title |
| `POST` | `/download/spotify` | The MP3, named `Artist - Title.mp3`, tagged from Spotify |

**[Full API reference → `docs/API.md`](docs/API.md)** — every parameter, all
error codes, Python/JavaScript/shell clients, and troubleshooting.

Interactive docs are served at <http://127.0.0.1:8000/docs> while it's running.

The MP3 carries ID3 title/artist tags and cover art.

## Tests

```bash
pip install -r requirements-dev.txt

# fast, offline
pytest tests/test_helpers.py

# opt-in, actually downloads a short public video
YT2MP3_INTEGRATION=1 pytest tests/test_integration.py
```

## Notes

- No auth and bound to localhost by design — single user, your machine only.
- Filenames come from the video title, so you may occasionally see suffixes
  like `(Official Video)`.
- YouTube occasionally rejects a stream URL with `HTTP 403`. The backend
  re-extracts and retries up to 3 times before returning `422`, so an
  occasional hiccup is invisible to you.
