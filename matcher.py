"""Match a Spotify track to a YouTube video by search + closest duration."""

from __future__ import annotations

from typing import NotRequired, Optional, Sequence, TypedDict

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError as YtDlpDownloadError

from spotify import TrackMeta


class Candidate(TypedDict):
    url: str
    duration: Optional[float]  # seconds, or None if unknown
    title: NotRequired[Optional[str]]


class NoMatchError(Exception):
    """Raised when a YouTube search yields no usable result."""


def build_query(meta: TrackMeta) -> str:
    """Search text for finding the track on YouTube."""
    return f"{meta.artist} {meta.title}".strip()


def pick_best_match(
    candidates: Sequence[Candidate], target_duration_s: Optional[float]
) -> Candidate:
    """Choose the candidate whose duration is closest to the target.

    Falls back to the first candidate when the target or all durations are
    unknown. Pure function — no network.
    """
    if not candidates:
        raise NoMatchError("No YouTube results to choose from.")

    if not target_duration_s:
        return candidates[0]

    with_duration = [c for c in candidates if c.get("duration")]
    if not with_duration:
        return candidates[0]

    return min(
        with_duration,
        key=lambda c: abs((c["duration"] or 0) - target_duration_s),
    )


def search_youtube(query: str, target_duration_s: Optional[float], n: int = 5) -> str:
    """Search YouTube for ``query`` and return the best-matching watch URL."""
    return search_youtube_detailed(query, target_duration_s, n)["url"]


def search_youtube_detailed(
    query: str, target_duration_s: Optional[float], n: int = 5
) -> Candidate:
    """Like ``search_youtube``, but returns the whole candidate.

    Callers that want to show *what* was matched (title, duration) before
    committing to a download need more than the URL.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,   # fast: metadata only, no per-video page fetch
        "noplaylist": True,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    except YtDlpDownloadError as exc:
        raise NoMatchError(f"YouTube search failed: {exc}") from exc

    entries = (info or {}).get("entries") or []
    candidates: list[Candidate] = []
    for e in entries:
        url = e.get("url") or e.get("webpage_url")
        if not url:
            continue
        # extract_flat gives bare ids for ytsearch; normalise to a watch URL.
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"
        candidates.append(
            {"url": url, "duration": e.get("duration"), "title": e.get("title")}
        )

    if not candidates:
        raise NoMatchError(f"No YouTube results for '{query}'.")

    return pick_best_match(candidates, target_duration_s)
