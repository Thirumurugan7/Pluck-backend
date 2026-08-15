"""Spotify Web API helpers: link parsing + metadata via client-credentials.

Spotify audio is DRM-protected and cannot be downloaded. This module only reads
metadata (title, artist, album, cover) so the audio can be matched and fetched
from YouTube elsewhere.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

import requests

_TOKEN_URL = "https://accounts.spotify.com/api/token"
_TRACK_URL = "https://api.spotify.com/v1/tracks/{id}"

# 22-char base62 Spotify id.
_ID = r"([A-Za-z0-9]{22})"
# open.spotify.com/track/<id> with optional /intl-xx/ locale segment + query.
_TRACK_HTTP_RE = re.compile(
    r"^https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?track/" + _ID + r"(?:[/?#].*)?$",
    re.IGNORECASE,
)
_TRACK_URI_RE = re.compile(r"^spotify:track:" + _ID + r"$", re.IGNORECASE)

_HTTP_TIMEOUT = 15


class SpotifyError(Exception):
    """Raised on missing credentials or any Spotify API failure."""


@dataclass
class TrackMeta:
    title: str
    artist: str
    album: str
    duration_ms: int
    cover_url: str | None


def is_valid_spotify_track_url(url: str) -> bool:
    """True if ``url`` is a Spotify *track* link (not album/playlist/artist)."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    return bool(_TRACK_HTTP_RE.match(url) or _TRACK_URI_RE.match(url))


def extract_track_id(url: str) -> str:
    """Return the 22-char track id from a Spotify track link, or raise ValueError."""
    if url and isinstance(url, str):
        url = url.strip()
        m = _TRACK_HTTP_RE.match(url) or _TRACK_URI_RE.match(url)
        if m:
            return m.group(1)
    raise ValueError("Not a Spotify track link.")


def spotify_creds_configured() -> bool:
    return bool(os.environ.get("SPOTIFY_CLIENT_ID") and os.environ.get("SPOTIFY_CLIENT_SECRET"))


# Simple in-process token cache: (token, expiry_epoch).
_token_cache: tuple[str, float] | None = None


def get_access_token() -> str:
    """Fetch (and cache) a client-credentials access token."""
    global _token_cache
    now = time.time()
    if _token_cache and _token_cache[1] > now + 30:
        return _token_cache[0]

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SpotifyError(
            "Spotify credentials missing. Set SPOTIFY_CLIENT_ID and "
            "SPOTIFY_CLIENT_SECRET in the environment."
        )

    try:
        resp = requests.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SpotifyError(f"Could not reach Spotify auth: {exc}") from exc

    if resp.status_code != 200:
        raise SpotifyError(
            f"Spotify auth failed ({resp.status_code}). Check your client id/secret."
        )

    payload = resp.json()
    token = payload["access_token"]
    expires_in = payload.get("expires_in", 3600)
    _token_cache = (token, now + float(expires_in))
    return token


def get_track_metadata(track_id: str) -> TrackMeta:
    """Fetch track metadata from the Spotify Web API."""
    token = get_access_token()
    try:
        resp = requests.get(
            _TRACK_URL.format(id=track_id),
            headers={"Authorization": f"Bearer {token}"},
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SpotifyError(f"Could not reach Spotify API: {exc}") from exc

    if resp.status_code == 404:
        raise SpotifyError("Spotify track not found.")
    if resp.status_code != 200:
        raise SpotifyError(f"Spotify API error ({resp.status_code}).")

    data = resp.json()
    artists = data.get("artists") or []
    artist = artists[0]["name"] if artists else "Unknown Artist"
    album_obj = data.get("album") or {}
    images = album_obj.get("images") or []
    cover_url = images[0]["url"] if images else None  # first = largest

    return TrackMeta(
        title=data.get("name") or "Unknown Title",
        artist=artist,
        album=album_obj.get("name") or "",
        duration_ms=int(data.get("duration_ms") or 0),
        cover_url=cover_url,
    )
