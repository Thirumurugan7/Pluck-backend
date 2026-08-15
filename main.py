"""yt2mp3 — local FastAPI backend that turns a YouTube or Spotify link into an MP3.

Bind to 127.0.0.1 only (see run.sh). Single user, no auth by design.

Route layout:
  /health          — dependency check
  /resolve*        — JSON metadata, no download (cheap, scriptable)
  /download*       — streams the MP3 (slow, does the real work)
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from downloader import (
    DownloadError,
    content_disposition,
    download_mp3,
    is_valid_youtube_url,
    probe_video,
    safe_filename,
)
from matcher import NoMatchError, build_query, search_youtube, search_youtube_detailed
from schemas import (
    ErrorResponse,
    HealthResponse,
    ResolveResponse,
    SpotifyResolveResponse,
)
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

DESCRIPTION = """
Turns a **YouTube** or **Spotify track** link into a tagged 320 kbps MP3.

Spotify audio is DRM-protected and cannot be downloaded. For Spotify links this
service reads the track's metadata from the Spotify Web API, finds the matching
audio on YouTube, and tags the result with Spotify's title/artist/album and
album art. Use `/resolve/spotify` to see which YouTube video would be used
before spending time on the download.

Runs on 127.0.0.1 with no authentication — single user, your machine only.
"""

TAGS_METADATA = [
    {"name": "resolve", "description": "Cheap JSON lookups. No download, no ffmpeg."},
    {"name": "download", "description": "Streams `audio/mpeg`. Takes seconds to minutes."},
    {"name": "health", "description": "Dependency status."},
]

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Warn once at startup about tools whose absence only bites mid-download."""
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
    yield


app = FastAPI(
    title="yt2mp3",
    description=DESCRIPTION,
    version="1.1.0",
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
)

# Machine-readable failure codes. Clients branch on these; `detail` is prose
# that may change wording.
CODE_INVALID_YOUTUBE_URL = "invalid_youtube_url"
CODE_INVALID_SPOTIFY_URL = "invalid_spotify_url"
CODE_INVALID_REQUEST = "invalid_request"
CODE_SPOTIFY_ERROR = "spotify_error"
CODE_NO_MATCH = "no_match"
CODE_DOWNLOAD_FAILED = "download_failed"
CODE_INTERNAL_ERROR = "internal_error"

_ERRORS = {
    400: {"model": ErrorResponse, "description": "Malformed or unsupported link."},
    422: {"model": ErrorResponse, "description": "Link is well-formed but could not be fulfilled."},
    500: {"model": ErrorResponse, "description": "Unexpected server error."},
    502: {"model": ErrorResponse, "description": "Spotify API or credential failure."},
}

# yt-dlp needs a JavaScript runtime to decipher YouTube stream signatures;
# without one, many current videos fail to download with HTTP 403.
_JS_RUNTIMES = ("deno", "node", "bun")


class ApiError(HTTPException):
    """HTTPException that also carries a stable error code."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


@app.exception_handler(HTTPException)
async def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    """Give every error the same {detail, code} body."""
    code = getattr(exc, "code", None) or CODE_INTERNAL_ERROR
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail), "code": code},
    )


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """A missing or malformed form field — most often `url` was not sent."""
    missing = ", ".join(str(e["loc"][-1]) for e in exc.errors()) or "url"
    return JSONResponse(
        status_code=422,
        content={
            "detail": f"Missing or invalid form field(s): {missing}. "
            "Send the link as form data, e.g. --data-urlencode 'url=…'.",
            "code": CODE_INVALID_REQUEST,
        },
    )


def _has_js_runtime() -> bool:
    return any(shutil.which(rt) for rt in _JS_RUNTIMES)


@app.get(
    "/health",
    tags=["health"],
    summary="Check ffmpeg, JS runtime, and Spotify credentials",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A required tool is missing."}},
)
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


@app.post(
    "/resolve",
    tags=["resolve"],
    summary="Look up a YouTube video's metadata without downloading",
    response_model=ResolveResponse,
    responses=_ERRORS,
)
def resolve(url: str = Form(..., description="A YouTube watch, youtu.be, or shorts link.")):
    if not is_valid_youtube_url(url):
        raise ApiError(400, CODE_INVALID_YOUTUBE_URL, "Provide a valid YouTube URL.")

    try:
        info = probe_video(url)
    except DownloadError as exc:
        raise ApiError(422, CODE_DOWNLOAD_FAILED, str(exc))

    return ResolveResponse(
        title=info.title,
        duration_s=info.duration_s,
        uploader=info.uploader,
        thumbnail=info.thumbnail,
        webpage_url=info.webpage_url,
    )


@app.post(
    "/resolve/spotify",
    tags=["resolve"],
    summary="Preview a Spotify track and the YouTube video that would supply its audio",
    response_model=SpotifyResolveResponse,
    responses=_ERRORS,
)
def resolve_spotify(
    url: str = Form(..., description="A Spotify *track* link or spotify:track: URI."),
):
    meta = _spotify_metadata(url)

    try:
        target_s = (meta.duration_ms / 1000.0) if meta.duration_ms else None
        match = search_youtube_detailed(build_query(meta), target_s)
    except NoMatchError as exc:
        raise ApiError(422, CODE_NO_MATCH, str(exc))

    matched_duration = match.get("duration")
    delta = (
        abs(matched_duration - target_s)
        if matched_duration is not None and target_s is not None
        else None
    )

    return SpotifyResolveResponse(
        title=meta.title,
        artist=meta.artist,
        album=meta.album,
        duration_s=meta.duration_ms / 1000.0,
        cover_url=meta.cover_url,
        matched_url=match["url"],
        matched_title=match.get("title"),
        matched_duration_s=matched_duration,
        duration_delta_s=delta,
    )


@app.post(
    "/download",
    tags=["download"],
    summary="Download a YouTube video as a tagged 320 kbps MP3",
    response_class=FileResponse,
    responses={
        200: {
            "content": {"audio/mpeg": {}},
            "description": "The MP3. Filename comes from the video title via Content-Disposition.",
        },
        **_ERRORS,
    },
)
def download(url: str = Form(..., description="A YouTube watch, youtu.be, or shorts link.")):
    if not is_valid_youtube_url(url):
        raise ApiError(400, CODE_INVALID_YOUTUBE_URL, "Provide a valid YouTube URL.")

    workdir = Path(tempfile.mkdtemp(prefix="yt2mp3_"))
    try:
        result = download_mp3(url, workdir)
    except DownloadError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise ApiError(422, CODE_DOWNLOAD_FAILED, str(exc))
    except Exception:  # noqa: BLE001 — clean up then surface a generic 500
        shutil.rmtree(workdir, ignore_errors=True)
        logger.exception("Unexpected error while downloading %s", url)
        raise ApiError(500, CODE_INTERNAL_ERROR, "Unexpected error during download.")

    filename = f"{safe_filename(result.title)}.mp3"
    return _mp3_response(result.path, filename, workdir)


@app.post(
    "/download/spotify",
    tags=["download"],
    summary="Download a Spotify track's audio (sourced from YouTube) as a tagged MP3",
    response_class=FileResponse,
    responses={
        200: {
            "content": {"audio/mpeg": {}},
            "description": 'The MP3, named "Artist - Title.mp3", tagged with Spotify metadata.',
        },
        **_ERRORS,
    },
)
def download_spotify(
    url: str = Form(..., description="A Spotify *track* link or spotify:track: URI."),
):
    meta = _spotify_metadata(url)

    workdir = Path(tempfile.mkdtemp(prefix="yt2mp3_sp_"))
    try:
        target_s = (meta.duration_ms / 1000.0) if meta.duration_ms else None
        video_url = search_youtube(build_query(meta), target_s)
        result = download_mp3(video_url, workdir)
        apply_spotify_tags(result.path, meta, fetch_cover(meta.cover_url))
    except NoMatchError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise ApiError(422, CODE_NO_MATCH, str(exc))
    except DownloadError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise ApiError(422, CODE_DOWNLOAD_FAILED, str(exc))
    except Exception:  # noqa: BLE001
        shutil.rmtree(workdir, ignore_errors=True)
        logger.exception("Unexpected error for Spotify url %s", url)
        raise ApiError(500, CODE_INTERNAL_ERROR, "Unexpected error during download.")

    filename = f"{safe_filename(f'{meta.artist} - {meta.title}')}.mp3"
    return _mp3_response(result.path, filename, workdir)


def _spotify_metadata(url: str):
    """Validate a Spotify track link and fetch its metadata, as an ApiError on failure."""
    if not is_valid_spotify_track_url(url):
        raise ApiError(
            400,
            CODE_INVALID_SPOTIFY_URL,
            "Provide a Spotify track link (open.spotify.com/track/...). "
            "Album and playlist links are not supported.",
        )
    try:
        return get_track_metadata(extract_track_id(url))
    except SpotifyError as exc:
        raise ApiError(502, CODE_SPOTIFY_ERROR, str(exc))
    except ValueError as exc:
        raise ApiError(400, CODE_INVALID_SPOTIFY_URL, str(exc))


def _mp3_response(path: Path, filename: str, workdir: Path) -> FileResponse:
    """Stream the finished MP3 and delete its temp dir once the response is sent."""
    return FileResponse(
        path=path,
        media_type="audio/mpeg",
        headers={"Content-Disposition": content_disposition(filename)},
        background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True),
    )
