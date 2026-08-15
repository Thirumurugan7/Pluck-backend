"""Offline HTTP-layer tests: routing, JSON shapes, and the error-code taxonomy.

Everything that touches the network (yt-dlp, Spotify) is monkeypatched, so this
suite runs without credentials, ffmpeg, or a connection.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from downloader import DownloadError, DownloadResult, VideoInfo  # noqa: E402
from matcher import NoMatchError  # noqa: E402
from spotify import SpotifyError, TrackMeta  # noqa: E402

_YT = "https://youtu.be/dQw4w9WgXcQ"
_SP = "https://open.spotify.com/track/0eGsygTp906u18L0Oimnem"

_META = TrackMeta(
    title="Blinding Lights",
    artist="The Weeknd",
    album="After Hours",
    duration_ms=200040,
    cover_url="https://i.scdn.co/image/abc",
)


@pytest.fixture
def client():
    return TestClient(main.app)


# --- /health -----------------------------------------------------------------


def test_health_reports_each_dependency(client, monkeypatch):
    monkeypatch.setattr(main.shutil, "which", lambda tool: "/usr/bin/" + tool)
    monkeypatch.setattr(main, "spotify_creds_configured", lambda: True)

    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "ffmpeg": True,
        "js_runtime": True,
        "spotify": True,
    }


def test_health_is_degraded_without_ffmpeg(client, monkeypatch):
    monkeypatch.setattr(main.shutil, "which", lambda tool: None)
    monkeypatch.setattr(main, "spotify_creds_configured", lambda: False)

    resp = client.get("/health")

    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


# --- POST /resolve -----------------------------------------------------------


def test_resolve_returns_video_metadata(client, monkeypatch):
    monkeypatch.setattr(
        main,
        "probe_video",
        lambda url: VideoInfo(
            title="Never Gonna Give You Up",
            duration_s=213.0,
            uploader="Rick Astley",
            thumbnail="https://i.ytimg.com/vi/x/hq.jpg",
            webpage_url=url,
        ),
    )

    resp = client.post("/resolve", data={"url": _YT})

    assert resp.status_code == 200
    assert resp.json() == {
        "title": "Never Gonna Give You Up",
        "duration_s": 213.0,
        "uploader": "Rick Astley",
        "thumbnail": "https://i.ytimg.com/vi/x/hq.jpg",
        "webpage_url": _YT,
    }


def test_resolve_rejects_non_youtube_url(client):
    resp = client.post("/resolve", data={"url": "https://vimeo.com/1"})

    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_youtube_url"


def test_resolve_surfaces_download_failure(client, monkeypatch):
    def boom(url):
        raise DownloadError("Video unavailable")

    monkeypatch.setattr(main, "probe_video", boom)

    resp = client.post("/resolve", data={"url": _YT})

    assert resp.status_code == 422
    assert resp.json()["code"] == "download_failed"
    assert "unavailable" in resp.json()["detail"]


# --- POST /resolve/spotify ---------------------------------------------------


def test_resolve_spotify_previews_the_youtube_match(client, monkeypatch):
    monkeypatch.setattr(main, "extract_track_id", lambda url: "id")
    monkeypatch.setattr(main, "get_track_metadata", lambda tid: _META)
    monkeypatch.setattr(
        main,
        "search_youtube_detailed",
        lambda q, target: {
            "url": "https://www.youtube.com/watch?v=abc",
            "title": "The Weeknd - Blinding Lights (Lyrics)",
            "duration": 199.0,
        },
    )

    resp = client.post("/resolve/spotify", data={"url": _SP})
    body = resp.json()

    assert resp.status_code == 200
    assert body["title"] == "Blinding Lights"
    assert body["artist"] == "The Weeknd"
    assert body["album"] == "After Hours"
    assert body["duration_s"] == pytest.approx(200.04)
    assert body["cover_url"] == "https://i.scdn.co/image/abc"
    assert body["matched_url"] == "https://www.youtube.com/watch?v=abc"
    assert body["matched_title"] == "The Weeknd - Blinding Lights (Lyrics)"
    assert body["matched_duration_s"] == 199.0
    # The delta is what tells a caller the match is trustworthy.
    assert body["duration_delta_s"] == pytest.approx(1.04, abs=0.01)


def test_resolve_spotify_rejects_album_link(client):
    resp = client.post(
        "/resolve/spotify",
        data={"url": "https://open.spotify.com/album/0eGsygTp906u18L0Oimnem"},
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_spotify_url"


def test_resolve_spotify_reports_credential_failure(client, monkeypatch):
    def boom(tid):
        raise SpotifyError("Spotify credentials missing.")

    monkeypatch.setattr(main, "extract_track_id", lambda url: "id")
    monkeypatch.setattr(main, "get_track_metadata", boom)

    resp = client.post("/resolve/spotify", data={"url": _SP})

    assert resp.status_code == 502
    assert resp.json()["code"] == "spotify_error"


def test_resolve_spotify_reports_no_match(client, monkeypatch):
    def boom(query, target):
        raise NoMatchError("No YouTube results.")

    monkeypatch.setattr(main, "extract_track_id", lambda url: "id")
    monkeypatch.setattr(main, "get_track_metadata", lambda tid: _META)
    monkeypatch.setattr(main, "search_youtube_detailed", boom)

    resp = client.post("/resolve/spotify", data={"url": _SP})

    assert resp.status_code == 422
    assert resp.json()["code"] == "no_match"


# --- POST /download ----------------------------------------------------------


def _fake_download(tmp_path, title="Song"):
    def _download(url, workdir):
        mp3 = Path(workdir) / "out.mp3"
        mp3.write_bytes(b"ID3fake-audio")
        return DownloadResult(path=mp3, title=title)

    return _download


def test_download_streams_mp3_with_filename(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "download_mp3", _fake_download(tmp_path))

    resp = client.post("/download", data={"url": _YT})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert 'filename="Song.mp3"' in resp.headers["content-disposition"]
    assert resp.content == b"ID3fake-audio"


def test_download_rejects_non_youtube_url(client):
    resp = client.post("/download", data={"url": "not a url"})

    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_youtube_url"


def test_download_reports_download_failure(client, monkeypatch):
    def boom(url, workdir):
        raise DownloadError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(main, "download_mp3", boom)

    resp = client.post("/download", data={"url": _YT})

    assert resp.status_code == 422
    assert resp.json()["code"] == "download_failed"


def test_missing_url_field_is_a_documented_error(client):
    resp = client.post("/download", data={})

    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_request"


# --- POST /download/spotify --------------------------------------------------


def test_download_spotify_names_file_artist_and_title(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "extract_track_id", lambda url: "id")
    monkeypatch.setattr(main, "get_track_metadata", lambda tid: _META)
    monkeypatch.setattr(main, "search_youtube", lambda q, target: "https://youtu.be/abc")
    monkeypatch.setattr(main, "download_mp3", _fake_download(tmp_path))
    monkeypatch.setattr(main, "fetch_cover", lambda url: None)
    monkeypatch.setattr(main, "apply_spotify_tags", lambda path, meta, cover: None)

    resp = client.post("/download/spotify", data={"url": _SP})

    assert resp.status_code == 200
    assert 'filename="The Weeknd - Blinding Lights.mp3"' in (
        resp.headers["content-disposition"]
    )


def test_download_spotify_reports_spotify_error(client, monkeypatch):
    def boom(tid):
        raise SpotifyError("Bad credentials.")

    monkeypatch.setattr(main, "extract_track_id", lambda url: "id")
    monkeypatch.setattr(main, "get_track_metadata", boom)

    resp = client.post("/download/spotify", data={"url": _SP})

    assert resp.status_code == 502
    assert resp.json()["code"] == "spotify_error"


# --- OpenAPI -----------------------------------------------------------------


def test_openapi_documents_every_endpoint(client):
    spec = client.get("/openapi.json").json()

    for path in ("/health", "/resolve", "/resolve/spotify", "/download", "/download/spotify"):
        assert path in spec["paths"], f"{path} missing from OpenAPI spec"

    resolve = spec["paths"]["/resolve"]["post"]
    assert resolve["summary"]
    assert "400" in resolve["responses"] and "422" in resolve["responses"]
