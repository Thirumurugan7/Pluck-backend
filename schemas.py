"""Response models for the yt2mp3 API.

These exist so the OpenAPI spec at /openapi.json describes real shapes rather
than bare dicts, and so clients have something stable to code against.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Every failure from this API has this shape."""

    detail: str = Field(description="Human-readable explanation.")
    code: str = Field(
        description="Stable machine-readable code. Branch on this, not on `detail`."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "detail": "Provide a valid YouTube URL.",
                "code": "invalid_youtube_url",
            }
        }
    }


class HealthResponse(BaseModel):
    status: str = Field(description='"ok" when ffmpeg and a JS runtime are present.')
    ffmpeg: bool = Field(description="ffmpeg found on PATH (required to convert).")
    js_runtime: bool = Field(
        description="deno/node/bun found on PATH (required to decipher YouTube streams)."
    )
    spotify: bool = Field(
        description="Spotify credentials configured. Only /…/spotify routes need this."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "ok",
                "ffmpeg": True,
                "js_runtime": True,
                "spotify": True,
            }
        }
    }


class ResolveResponse(BaseModel):
    """What a YouTube link points at, without downloading it."""

    title: str
    duration_s: Optional[float] = Field(description="Video length in seconds.")
    uploader: Optional[str] = Field(description="Channel name.")
    thumbnail: Optional[str]
    webpage_url: str = Field(description="Canonical watch URL.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "Rick Astley - Never Gonna Give You Up (Official Video)",
                "duration_s": 213.0,
                "uploader": "Rick Astley",
                "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
                "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            }
        }
    }


class SpotifyResolveResponse(BaseModel):
    """Spotify's metadata plus the YouTube video that would supply the audio.

    Spotify audio is DRM-protected, so the audio always comes from YouTube.
    Check `duration_delta_s` and `matched_title` before downloading: a large
    delta or an odd title means the matcher found a cover, live version, or
    edit rather than the track you asked for.
    """

    title: str
    artist: str
    album: str
    duration_s: float = Field(description="Spotify's track length in seconds.")
    cover_url: Optional[str] = Field(description="Spotify album art (embedded as ID3 APIC).")
    matched_url: str = Field(description="YouTube video the audio would come from.")
    matched_title: Optional[str]
    matched_duration_s: Optional[float]
    duration_delta_s: Optional[float] = Field(
        description="abs(spotify - youtube) in seconds. Under ~2s is a confident match."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "Blinding Lights",
                "artist": "The Weeknd",
                "album": "After Hours",
                "duration_s": 200.04,
                "cover_url": "https://i.scdn.co/image/ab67616d0000b273…",
                "matched_url": "https://www.youtube.com/watch?v=fHI8X4OXluQ",
                "matched_title": "The Weeknd - Blinding Lights (Official Video)",
                "matched_duration_s": 199.0,
                "duration_delta_s": 1.04,
            }
        }
    }
