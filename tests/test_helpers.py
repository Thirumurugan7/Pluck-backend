"""Offline unit tests for the pure helpers. No network, no ffmpeg needed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from downloader import (  # noqa: E402
    content_disposition,
    is_valid_youtube_url,
    safe_filename,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "http://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtube.com/shorts/abc123",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RD",
        "  https://youtu.be/dQw4w9WgXcQ  ",  # surrounding whitespace
    ],
)
def test_valid_youtube_urls(url):
    assert is_valid_youtube_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "https://vimeo.com/12345",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "ftp://youtube.com/watch?v=x",
        "https://youtube.com",          # host only, no path
        "https://notyoutube.com/x",
        "https://youtube.com.evil.com/x",  # host is evil.com, not youtube
    ],
)
def test_invalid_youtube_urls(url):
    assert is_valid_youtube_url(url) is False


def test_valid_url_rejects_non_string():
    assert is_valid_youtube_url(None) is False  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Never Gonna Give You Up", "Never Gonna Give You Up"),
        ("AC/DC - Thunderstruck", "ACDC - Thunderstruck"),
        ('Weird: "quotes" <tags>?*|', "Weird quotes tags"),
        ("  spaced   out  ", "spaced out"),
        ("../../etc/passwd", "etcpasswd"),
        ("", "audio"),
        ("...", "audio"),
        ("\x00\x01control", "control"),
    ],
)
def test_safe_filename(title, expected):
    assert safe_filename(title) == expected


def test_safe_filename_caps_length():
    long_title = "x" * 500
    result = safe_filename(long_title)
    assert len(result) <= 150
    assert result == "x" * 150


def test_safe_filename_has_no_path_separators():
    result = safe_filename("a/b\\c")
    assert "/" not in result and "\\" not in result


def test_content_disposition_ascii_has_plain_filename():
    # curl -OJ needs a plain filename="..." token to save the file.
    header = content_disposition("Me at the zoo.mp3")
    assert 'filename="Me at the zoo.mp3"' in header
    assert "filename*=UTF-8''Me%20at%20the%20zoo.mp3" in header


def test_content_disposition_unicode_is_header_safe():
    # Non-latin titles must still yield a latin-1 encodable header.
    header = content_disposition("曲名.mp3")
    header.encode("latin-1")  # must not raise
    assert "filename*=UTF-8''" in header
    # ASCII fallback kicks in since the name is all non-ascii.
    assert 'filename="audio.mp3"' in header


def test_content_disposition_strips_quotes():
    header = content_disposition('ev"il.mp3')
    assert 'filename="evil.mp3"' in header
