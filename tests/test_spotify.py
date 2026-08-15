"""Offline unit tests for the Spotify → MP3 helpers."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spotify import (  # noqa: E402
    TrackMeta,
    extract_track_id,
    is_valid_spotify_track_url,
)
from matcher import NoMatchError, build_query, pick_best_match  # noqa: E402


_TID = "0eGsygTp906u18L0Oimnem"  # 22-char example id


@pytest.mark.parametrize(
    "url",
    [
        f"https://open.spotify.com/track/{_TID}",
        f"http://open.spotify.com/track/{_TID}",
        f"https://open.spotify.com/track/{_TID}?si=abc123",
        f"https://open.spotify.com/intl-de/track/{_TID}",
        f"https://open.spotify.com/intl-pt/track/{_TID}?si=x",
        f"spotify:track:{_TID}",
        f"  https://open.spotify.com/track/{_TID}  ",
    ],
)
def test_valid_track_urls(url):
    assert is_valid_spotify_track_url(url) is True
    assert extract_track_id(url) == _TID


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        f"https://open.spotify.com/album/{_TID}",
        f"https://open.spotify.com/playlist/{_TID}",
        f"https://open.spotify.com/artist/{_TID}",
        "https://open.spotify.com/track/short",
        "https://youtube.com/watch?v=x",
        f"https://open.spotify.com.evil.com/track/{_TID}",
    ],
)
def test_invalid_track_urls(url):
    assert is_valid_spotify_track_url(url) is False


def test_extract_track_id_raises_on_bad_input():
    with pytest.raises(ValueError):
        extract_track_id("https://open.spotify.com/album/" + _TID)


def test_build_query():
    meta = TrackMeta("Blinding Lights", "The Weeknd", "After Hours", 200040, None)
    assert build_query(meta) == "The Weeknd Blinding Lights"


def test_pick_best_match_closest_duration():
    candidates = [
        {"url": "a", "duration": 600},   # extended, far off
        {"url": "b", "duration": 201},   # closest
        {"url": "c", "duration": 240},
    ]
    assert pick_best_match(candidates, 200)["url"] == "b"


def test_pick_best_match_falls_back_to_first_without_target():
    candidates = [{"url": "a", "duration": 300}, {"url": "b", "duration": 200}]
    assert pick_best_match(candidates, None)["url"] == "a"


def test_pick_best_match_falls_back_when_no_durations():
    candidates = [{"url": "a", "duration": None}, {"url": "b", "duration": None}]
    assert pick_best_match(candidates, 200)["url"] == "a"


def test_pick_best_match_empty_raises():
    with pytest.raises(NoMatchError):
        pick_best_match([], 200)


def test_apply_spotify_tags_roundtrip(tmp_path):
    """Generate a tiny MP3, apply tags + cover, read them back."""
    import shutil
    import subprocess

    from mutagen.id3 import ID3

    from tagging import apply_spotify_tags

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")

    mp3 = tmp_path / "tone.mp3"
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-b:a", "128k", "-y", str(mp3)],
        check=True, capture_output=True,
    )

    meta = TrackMeta("My Song", "My Artist", "My Album", 1000, None)
    fake_cover = b"\xff\xd8\xff" + b"0" * 100  # jpeg-ish bytes
    apply_spotify_tags(mp3, meta, fake_cover)

    tags = ID3(mp3)
    assert tags["TIT2"].text[0] == "My Song"
    assert tags["TPE1"].text[0] == "My Artist"
    assert tags["TALB"].text[0] == "My Album"
    assert tags.getall("APIC") and tags.getall("APIC")[0].data == fake_cover
