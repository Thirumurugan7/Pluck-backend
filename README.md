# yt2mp3

A tiny local backend that turns a YouTube link into a tagged 320 kbps MP3.
Runs on your Mac, on `127.0.0.1` only. You drive it with `curl`.

## Prerequisites

- Python 3.11+
- ffmpeg:
  ```bash
  brew install ffmpeg
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

Check that ffmpeg is available:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","ffmpeg":true}
```

## API

| Method | Path        | Body (form)      | Result |
|--------|-------------|------------------|--------|
| POST   | `/download` | `url=<youtube>`  | streams `audio/mpeg`; filename from the video title. `400` bad URL, `422` download failure |
| GET    | `/health`   | —                | `200` if ffmpeg present, else `503` |

The MP3 carries ID3 title/artist tags and the video thumbnail as cover art.

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
