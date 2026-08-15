# yt2mp3 API Reference

Local HTTP API that turns a **YouTube** or **Spotify track** link into a tagged
320 kbps MP3.

- **Base URL:** `http://127.0.0.1:8000`
- **Auth:** none — the server binds to localhost only, single user by design
- **Request format:** `application/x-www-form-urlencoded` (all `POST` bodies)
- **Interactive docs:** <http://127.0.0.1:8000/docs> · raw spec at `/openapi.json`

> **Where the audio comes from.** Spotify audio is DRM-protected and cannot be
> downloaded by any third-party client. For Spotify links this API reads
> *metadata* from the Spotify Web API, then sources the *audio* from YouTube and
> stamps Spotify's title/artist/album and cover art onto it. Use
> [`/resolve/spotify`](#post-resolvespotify) to see exactly which YouTube video
> will be used before you download.

---

## Contents

- [Quick start](#quick-start)
- [Endpoints](#endpoints)
  - [`GET /health`](#get-health)
  - [`POST /resolve`](#post-resolve)
  - [`POST /resolve/spotify`](#post-resolvespotify)
  - [`POST /download`](#post-download)
  - [`POST /download/spotify`](#post-downloadspotify)
- [Errors](#errors)
- [Client snippets](#client-snippets)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)

---

## Quick start

```bash
# 1. start the server
./run.sh

# 2. check its dependencies
curl http://127.0.0.1:8000/health

# 3. download something (-OJ saves using the server-provided filename)
curl -X POST http://127.0.0.1:8000/download \
  --data-urlencode "url=https://youtu.be/dQw4w9WgXcQ" -OJ
```

---

## Endpoints

At a glance:

| Method | Path | Returns | Typical time |
|---|---|---|---|
| `GET` | `/health` | JSON dependency status | instant |
| `POST` | `/resolve` | JSON video metadata | ~1 s |
| `POST` | `/resolve/spotify` | JSON track metadata + YouTube match | ~2 s |
| `POST` | `/download` | `audio/mpeg` stream | 10–60 s |
| `POST` | `/download/spotify` | `audio/mpeg` stream | 15–90 s |

---

### `GET /health`

Reports whether the external tools the service depends on are present.

**Response `200` — healthy**

```json
{ "status": "ok", "ffmpeg": true, "js_runtime": true, "spotify": true }
```

| Field | Meaning |
|---|---|
| `status` | `"ok"` when ffmpeg **and** a JS runtime are present, else `"degraded"` |
| `ffmpeg` | Required to convert and tag. Without it every download fails. |
| `js_runtime` | `deno`, `node`, or `bun`. Required to decipher YouTube stream signatures; without it most downloads fail with `HTTP 403`. |
| `spotify` | Whether credentials are configured. Only the `/…/spotify` routes need this, so it never affects `status`. |

**Response `503`** — same body with `"status": "degraded"` when ffmpeg or the JS
runtime is missing.

```bash
curl http://127.0.0.1:8000/health
```

---

### `POST /resolve`

Look up what a YouTube link points at, without downloading it. Cheap enough to
call on every paste.

| Param | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | A `watch`, `youtu.be`, `shorts`, or `embed` link |

**Response `200`**

```json
{
  "title": "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)",
  "duration_s": 213.0,
  "uploader": "Rick Astley",
  "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
  "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
}
```

`duration_s`, `uploader`, and `thumbnail` may be `null` for unusual videos.

**Errors:** `400` `invalid_youtube_url` · `422` `download_failed` (private,
removed, or region-blocked video)

```bash
curl -X POST http://127.0.0.1:8000/resolve \
  --data-urlencode "url=https://youtu.be/dQw4w9WgXcQ"
```

---

### `POST /resolve/spotify`

Read a Spotify track's metadata **and** show which YouTube video would supply
its audio — the preview step before committing to a download.

| Param | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | A Spotify **track** link, or a `spotify:track:<id>` URI. Album, playlist, and artist links are rejected. |

**Response `200`**

```json
{
  "title": "Dheema",
  "artist": "Anirudh Ravichander",
  "album": "Love Insurance Kompany (Original Motion Picture Soundtrack)",
  "duration_s": 235.102,
  "cover_url": "https://i.scdn.co/image/ab67616d0000b27333c6ec99236141977db9f410",
  "matched_url": "https://www.youtube.com/watch?v=H1frBzuWqqM",
  "matched_title": "Love Insurance Kompany - Dheema Video | Pradeep Ranganathan | …",
  "matched_duration_s": 238.0,
  "duration_delta_s": 2.898
}
```

**Judging the match.** The matcher searches `"{artist} {title}"` and picks the
result whose duration is closest to Spotify's. Two fields tell you whether to
trust it:

- **`duration_delta_s`** — under ~2 s is a confident match. A large delta means
  an extended mix, a loop, or the wrong song entirely.
- **`matched_title`** — matching purely on duration means a lyric video or
  re-upload can win over the official audio. If the title looks wrong, use
  `/download` with a YouTube URL you picked yourself.

**Errors:** `400` `invalid_spotify_url` · `502` `spotify_error` · `422` `no_match`

```bash
curl -X POST http://127.0.0.1:8000/resolve/spotify \
  --data-urlencode "url=https://open.spotify.com/track/7tbCtSE51CsYyTmAEfnxFm"
```

---

### `POST /download`

Download a YouTube video as a 320 kbps MP3 with ID3 tags and the video
thumbnail embedded as cover art.

| Param | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | A `watch`, `youtu.be`, `shorts`, or `embed` link |

**Response `200`** — the raw MP3 with:

```
Content-Type: audio/mpeg
Content-Disposition: attachment; filename="<video title>.mp3"; filename*=UTF-8''<video%20title>.mp3
```

The filename comes from the video title, so expect suffixes like
`(Official Video)`. Pass `-OJ` to curl to honor it; without `-J`, curl names the
file after the URL path (`download`) instead.

Transient YouTube failures (`403`, `429`, `5xx`, timeouts) are retried up to
3 times internally before the request fails, so a single hiccup stays invisible.

**Errors:** `400` `invalid_youtube_url` · `422` `download_failed` ·
`500` `internal_error`

```bash
curl -X POST http://127.0.0.1:8000/download \
  --data-urlencode "url=https://youtu.be/dQw4w9WgXcQ" -OJ
```

---

### `POST /download/spotify`

Resolve a Spotify track, fetch the matching audio from YouTube, and overwrite
the tags with Spotify's title/artist/album plus the album cover.

| Param | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | A Spotify **track** link or `spotify:track:<id>` URI |

**Response `200`** — the MP3, named `Artist - Title.mp3`, carrying:

- ID3 `TIT2` / `TPE1` / `TALB` copied verbatim from Spotify
- Spotify's album art embedded as `APIC` (byte-identical to what Spotify serves)

If the cover download fails the request still succeeds — you get the MP3 with
tags and no artwork.

**Requires** `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`; see
[Configuration](#configuration).

**Errors:** `400` `invalid_spotify_url` · `502` `spotify_error` ·
`422` `no_match` / `download_failed` · `500` `internal_error`

```bash
curl -X POST http://127.0.0.1:8000/download/spotify \
  --data-urlencode "url=https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b" -OJ
```

---

## Errors

Every failure returns the same JSON shape:

```json
{ "detail": "Provide a valid YouTube URL.", "code": "invalid_youtube_url" }
```

**Branch on `code`, not on `detail`** — the prose may be reworded, the codes are
stable.

| Code | HTTP | Meaning | What to do |
|---|---|---|---|
| `invalid_youtube_url` | 400 | Not a recognizable YouTube link | Check the URL |
| `invalid_spotify_url` | 400 | Not a Spotify *track* link (album/playlist/artist links land here) | Open the track itself and copy its link |
| `invalid_request` | 422 | The `url` form field is missing or malformed | Send `--data-urlencode "url=…"` |
| `spotify_error` | 502 | Missing/invalid credentials, or the Spotify API failed | Check your env vars, then Spotify's status |
| `no_match` | 422 | YouTube search returned nothing usable | Try `/download` with a YouTube URL you choose |
| `download_failed` | 422 | yt-dlp could not fetch or convert (private, removed, region-locked, or 403 after 3 retries) | `detail` carries yt-dlp's reason |
| `internal_error` | 500 | Unexpected server-side failure | Check the server log |

---

## Client snippets

### Shell function

Drop this in your `~/.zshrc` — it takes either link type and picks the endpoint
for you:

```bash
mp3() {
  local url="$1" endpoint="download"
  [[ "$url" == *"spotify.com"* || "$url" == spotify:* ]] && endpoint="download/spotify"
  curl -sS -X POST "http://127.0.0.1:8000/$endpoint" \
    --data-urlencode "url=$url" -OJ -w '%{http_code}\n'
}
# mp3 https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b
```

### Python

```python
import re
import requests

BASE = "http://127.0.0.1:8000"


def preview(url: str) -> dict:
    """See what would be downloaded, without downloading it."""
    route = "/resolve/spotify" if "spotify" in url else "/resolve"
    resp = requests.post(BASE + route, data={"url": url}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def download(url: str, out_dir: str = ".") -> str:
    """Download to out_dir, using the server-provided filename."""
    route = "/download/spotify" if "spotify" in url else "/download"
    resp = requests.post(BASE + route, data={"url": url}, timeout=600, stream=True)

    if resp.status_code != 200:
        err = resp.json()
        raise RuntimeError(f"[{err['code']}] {err['detail']}")

    disposition = resp.headers.get("content-disposition", "")
    name = re.search(r'filename="([^"]+)"', disposition)
    path = f"{out_dir}/{name.group(1) if name else 'audio.mp3'}"

    with open(path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            fh.write(chunk)
    return path


print(preview("https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b"))
print(download("https://youtu.be/dQw4w9WgXcQ"))
```

### JavaScript (Node 18+ / browser)

```js
const BASE = "http://127.0.0.1:8000";

async function preview(url) {
  const route = url.includes("spotify") ? "/resolve/spotify" : "/resolve";
  const resp = await fetch(BASE + route, {
    method: "POST",
    body: new URLSearchParams({ url }),
  });
  const body = await resp.json();
  if (!resp.ok) throw new Error(`[${body.code}] ${body.detail}`);
  return body;
}

async function download(url) {
  const route = url.includes("spotify") ? "/download/spotify" : "/download";
  const resp = await fetch(BASE + route, {
    method: "POST",
    body: new URLSearchParams({ url }),
  });

  if (!resp.ok) {
    const err = await resp.json();
    throw new Error(`[${err.code}] ${err.detail}`);
  }

  const disposition = resp.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "audio.mp3";
  return { filename, blob: await resp.blob() };
}

console.log(await preview("https://youtu.be/dQw4w9WgXcQ"));
```

In Node, write the blob out with
`fs.writeFileSync(filename, Buffer.from(await blob.arrayBuffer()))`.

---

## Configuration

| Variable | Needed for | Notes |
|---|---|---|
| `SPOTIFY_CLIENT_ID` | `/resolve/spotify`, `/download/spotify` | From a Spotify developer app |
| `SPOTIFY_CLIENT_SECRET` | same | Never logged; read from the environment only |

Create a free app at <https://developer.spotify.com/dashboard>. No redirect URI
or user login is needed — this uses the client-credentials flow, which reaches
public catalog metadata only.

```bash
export SPOTIFY_CLIENT_ID=your_client_id
export SPOTIFY_CLIENT_SECRET=your_client_secret
./run.sh
```

Verify with `curl http://127.0.0.1:8000/health` → `"spotify": true`.

---

## Troubleshooting

**Every download fails with `HTTP 403`.** Install a JavaScript runtime:
`brew install deno`. yt-dlp needs one to decipher YouTube stream signatures.
Confirm with `/health` → `"js_runtime": true`. Occasional one-off 403s are
normal and already retried internally.

**`curl` saved a file literally named `download`.** You used `-O` without `-J`.
Use `-OJ` so curl honors the `Content-Disposition` filename.

**`curl: (23) Failure writing output to destination`.** The server sent the MP3
fine (you'll see `200`) — `curl -J` simply refuses to overwrite a file that
already exists. Delete or rename the existing file, or drop `-J` and choose the
name yourself with `-o "name.mp3"`.

**`502 spotify_error` saying credentials are missing.** The variables must be
exported in the shell that starts the server — a `.env` file is not read. Export
them, restart, and re-check `/health`.

**Wrong song, or a live/cover version.** The matcher ranks by duration alone.
Call `/resolve/spotify` first: if `matched_title` looks wrong or
`duration_delta_s` is large, pick the video yourself and use `/download`.

**Conversion produced no MP3.** ffmpeg is missing or failed — `brew install
ffmpeg` and confirm `/health` → `"ffmpeg": true`.

**Downloads are slow.** Expected: the file is fetched, then transcoded to
320 kbps by ffmpeg. Use `/resolve` first to confirm you want it before waiting.

---

## Notes on quality

The MP3 is 320 kbps, but that number describes the *output* encoder, not the
source. YouTube serves roughly 130 kbps Opus, which ffmpeg re-encodes to
320 kbps MP3 — a lossy-to-lossy transcode. The file faithfully reproduces its
source; it is not CD quality, and 192 kbps would sound the same at 60% of the
size. For genuinely lossless audio, buy the track from Bandcamp or Qobuz.
