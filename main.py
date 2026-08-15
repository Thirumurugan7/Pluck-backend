"""yt2mp3 — local FastAPI backend that turns a YouTube link into an MP3.

Bind to 127.0.0.1 only (see run.sh). Single user, no auth by design.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from downloader import (
    DownloadError,
    content_disposition,
    download_mp3,
    is_valid_youtube_url,
    safe_filename,
)
from matcher import NoMatchError, build_query, search_youtube
from spotify import (
    SpotifyError,
    extract_track_id,
    get_track_metadata,
    is_valid_spotify_track_url,
    spotify_creds_configured,
)
from tagging import apply_spotify_tags, fetch_cover

logger = logging.getLogger("yt2mp3")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="yt2mp3", description="Local YouTube→MP3 downloader")


# yt-dlp needs a JavaScript runtime to decipher YouTube stream signatures;
# without one, many current videos fail to download with HTTP 403.
_JS_RUNTIMES = ("deno", "node", "bun")


def _has_js_runtime() -> bool:
    return any(shutil.which(rt) for rt in _JS_RUNTIMES)


@app.on_event("startup")
def _warn_missing_tools() -> None:
    if shutil.which("ffmpeg") is None:
        logger.warning(
            "ffmpeg not found on PATH. Install it with `brew install ffmpeg` "
            "or /download will fail."
        )
    if not _has_js_runtime():
        logger.warning(
            "No JavaScript runtime found. Install one with `brew install deno` "
            "or many YouTube downloads will fail with HTTP 403."
        )


@app.get("/health")
def health() -> JSONResponse:
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    js_ok = _has_js_runtime()
    healthy = ffmpeg_ok and js_ok
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "ffmpeg": ffmpeg_ok,
            "js_runtime": js_ok,
            # Reported for visibility; not required for YouTube downloads.
            "spotify": spotify_creds_configured(),
        },
    )


@app.post("/download")
def download(url: str = Form(...)) -> FileResponse:
    if not is_valid_youtube_url(url):
        raise HTTPException(status_code=400, detail="Provide a valid YouTube URL.")

    workdir = Path(tempfile.mkdtemp(prefix="yt2mp3_"))
    try:
        result = download_mp3(url, workdir)
    except DownloadError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:  # noqa: BLE001 — clean up then surface a generic 500
        shutil.rmtree(workdir, ignore_errors=True)
        logger.exception("Unexpected error while downloading %s", url)
        raise HTTPException(status_code=500, detail="Unexpected error during download.")

    filename = f"{safe_filename(result.title)}.mp3"
    return FileResponse(
        path=result.path,
        media_type="audio/mpeg",
        headers={"Content-Disposition": content_disposition(filename)},
        background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True),
    )


@app.post("/download/spotify")
def download_spotify(url: str = Form(...)) -> FileResponse:
    if not is_valid_spotify_track_url(url):
        raise HTTPException(
            status_code=400,
            detail="Provide a Spotify track link (open.spotify.com/track/...). "
            "Album and playlist links are not supported.",
        )

    # Resolve metadata from Spotify (audio itself comes from YouTube).
    try:
        track_id = extract_track_id(url)
        meta = get_track_metadata(track_id)
    except SpotifyError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    workdir = Path(tempfile.mkdtemp(prefix="yt2mp3_sp_"))
    try:
        target_s = (meta.duration_ms / 1000.0) if meta.duration_ms else None
        video_url = search_youtube(build_query(meta), target_s)
        result = download_mp3(video_url, workdir)
        apply_spotify_tags(result.path, meta, fetch_cover(meta.cover_url))
    except (NoMatchError, DownloadError) as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:  # noqa: BLE001
        shutil.rmtree(workdir, ignore_errors=True)
        logger.exception("Unexpected error for Spotify url %s", url)
        raise HTTPException(status_code=500, detail="Unexpected error during download.")

    filename = f"{safe_filename(f'{meta.artist} - {meta.title}')}.mp3"
    return FileResponse(
        path=result.path,
        media_type="audio/mpeg",
        headers={"Content-Disposition": content_disposition(filename)},
        background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True),
    )
