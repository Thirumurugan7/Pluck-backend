"""Opt-in integration test that actually downloads a short public video.

Skipped by default so the normal suite stays offline and fast.
Run it explicitly with:  YT2MP3_INTEGRATION=1 pytest tests/test_integration.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from downloader import download_mp3  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("YT2MP3_INTEGRATION") != "1",
    reason="set YT2MP3_INTEGRATION=1 to run network-dependent test",
)

# "Me at the zoo" — the first, very short YouTube video.
_SHORT_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_download_produces_mp3():
    workdir = Path(tempfile.mkdtemp(prefix="yt2mp3_test_"))
    try:
        result = download_mp3(_SHORT_VIDEO, workdir)
        assert result.path.exists()
        assert result.path.suffix == ".mp3"
        assert result.path.stat().st_size > 0
        assert result.title
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
