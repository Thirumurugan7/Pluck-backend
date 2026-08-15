"""Download logic and helpers for yt2mp3.

Kept free of web-framework concerns so the helpers stay easy to unit-test and
the HTTP layer in main.py stays thin.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError as YtDlpDownloadError


# Accept the common YouTube URL shapes: watch, youtu.be, shorts, embed.
# Host must be an actual youtube host (optionally with a subdomain like www/m/music).
_YOUTUBE_URL_RE = re.compile(
    r"^https?://"
    r"(?:[\w-]+\.)*"                      # optional subdomains
    r"(?:youtube\.com|youtu\.be)"         # host
    r"/",                                  # must have a path
    re.IGNORECASE,
)

# Characters illegal in filenames on macOS / in HTTP headers, plus control chars.
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_MAX_FILENAME_LEN = 150

# YouTube intermittently answers a freshly-issued stream URL with 403, and
# occasionally drops the connection mid-transfer. Re-extracting gets a new URL,
# so those are worth one or two more tries; anything else (private/removed
# video, bad link) fails the same way every time and is surfaced immediately.
MAX_DOWNLOAD_ATTEMPTS = 3
_RETRY_DELAY_S = 2.0
_TRANSIENT_ERROR_RE = re.compile(
    r"HTTP Error (?:403|429|5\d\d)"
    r"|unable to download video data"
    r"|read operation timed out"
    r"|connection (?:reset|aborted)"
    r"|temporary failure",
    re.IGNORECASE,
)


def _is_transient(message: str) -> bool:
    return bool(_TRANSIENT_ERROR_RE.search(message))


class DownloadError(Exception):
    """Raised when yt-dlp fails to fetch or convert the requested video."""


@dataclass
class DownloadResult:
    path: Path
    title: str


@dataclass
class VideoInfo:
    """What a video *is*, without downloading it."""

    title: str
    duration_s: float | None
    uploader: str | None
    thumbnail: str | None
    webpage_url: str


def is_valid_youtube_url(url: str) -> bool:
    """True if ``url`` is a plausible YouTube link. No network call."""
    if not url or not isinstance(url, str):
        return False
    return bool(_YOUTUBE_URL_RE.match(url.strip()))


def safe_filename(title: str) -> str:
    """Turn a video title into a filesystem/header-safe base name (no extension).

    Strips illegal characters, collapses whitespace, caps length, and always
    returns a non-empty value.
    """
    if not title:
        return "audio"
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Avoid names that are only dots or empty after cleaning.
    cleaned = cleaned.strip(".")
    if not cleaned:
        return "audio"
    return cleaned[:_MAX_FILENAME_LEN].strip()


def content_disposition(filename: str) -> str:
    """Build a Content-Disposition header that ``curl -OJ`` can parse.

    Emits a plain ``filename="..."`` (ASCII-folded so the header stays
    latin-1 encodable, which curl -J reads) plus a ``filename*`` for clients
    that support the RFC 5987 unicode form.
    """
    ascii_name = filename.encode("ascii", "ignore").decode("ascii").strip()
    if not ascii_name or ascii_name in {".mp3", ""}:
        ascii_name = "audio.mp3"
    # Quoted-string value: strip any residual quotes/backslashes for safety.
    ascii_name = ascii_name.replace('"', "").replace("\\", "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _extract_with_retry(url: str, ydl_opts: dict, download: bool = True) -> dict:
    """Run yt-dlp, retrying transient failures with a fresh extraction.

    Raises ``DownloadError`` once the failure is permanent or the attempts
    are spent.
    """
    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
        try:
            with YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=download)
        except YtDlpDownloadError as exc:
            if attempt == MAX_DOWNLOAD_ATTEMPTS or not _is_transient(str(exc)):
                raise DownloadError(str(exc)) from exc
            time.sleep(_RETRY_DELAY_S * attempt)
    raise DownloadError("Download failed after retries.")  # unreachable


def probe_video(url: str) -> VideoInfo:
    """Read a video's metadata without downloading or converting anything."""
    info = _extract_with_retry(
        url,
        {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True},
        download=False,
    )

    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]

    return VideoInfo(
        title=info.get("title") or "audio",
        duration_s=info.get("duration"),
        uploader=info.get("uploader") or info.get("channel"),
        thumbnail=info.get("thumbnail"),
        webpage_url=info.get("webpage_url") or url,
    )


def download_mp3(url: str, workdir: Path) -> DownloadResult:
    """Download ``url`` as a 320k MP3 into ``workdir`` with tags + cover art.

    Returns the path to the produced ``.mp3`` and the video title.
    Raises ``DownloadError`` on any yt-dlp failure.
    """
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(workdir / "%(title)s.%(ext)s"),
        "writethumbnail": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            },
            {"key": "FFmpegMetadata"},          # write id3 title/artist
            {"key": "EmbedThumbnail"},          # embed cover art
        ],
    }

    info = _extract_with_retry(url, ydl_opts)

    # A single video may still be wrapped in an "entries" list by yt-dlp.
    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]

    title = info.get("title") or "audio"

    mp3_files = sorted(workdir.glob("*.mp3"))
    if not mp3_files:
        raise DownloadError("Conversion produced no MP3 file.")

    return DownloadResult(path=mp3_files[0], title=title)
