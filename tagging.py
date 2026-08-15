"""Apply accurate Spotify metadata (tags + cover art) to a downloaded MP3."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import requests
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1
from mutagen.id3._util import ID3NoHeaderError

from spotify import TrackMeta

_HTTP_TIMEOUT = 15


def fetch_cover(url: Optional[str]) -> Optional[bytes]:
    """Download album cover bytes; return None on any failure."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=_HTTP_TIMEOUT)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except requests.RequestException:
        pass
    return None


def apply_spotify_tags(
    mp3_path: Path, meta: TrackMeta, cover_bytes: Optional[bytes]
) -> None:
    """Overwrite title/artist/album tags and embed cover art via mutagen."""
    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()

    tags.setall("TIT2", [TIT2(encoding=3, text=meta.title)])
    tags.setall("TPE1", [TPE1(encoding=3, text=meta.artist)])
    if meta.album:
        tags.setall("TALB", [TALB(encoding=3, text=meta.album)])

    if cover_bytes:
        # Replace any existing embedded picture with the Spotify cover.
        tags.delall("APIC")
        tags.add(
            APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,           # front cover
                desc="Cover",
                data=cover_bytes,
            )
        )

    tags.save(mp3_path, v2_version=3)
