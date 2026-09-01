import json
import subprocess
from pathlib import Path

import pytest

from janitorjav.media import FFmpegTools, MediaToolError


def test_probe_parses_first_video_stream(tmp_path: Path) -> None:
    video = tmp_path / "video.mkv"
    video.touch()
    payload = {
        "streams": [{"codec_name": "h264", "width": 1920, "height": 1080}],
        "format": {"duration": "123.45"},
    }

    def runner(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        assert command[-1] == str(video)
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    metadata = FFmpegTools(runner=runner).probe(video)
    assert metadata.duration_seconds == 123.45
    assert (metadata.width, metadata.height) == (1920, 1080)
    assert metadata.codec_name == "h264"


def test_probe_rejects_incomplete_output(tmp_path: Path) -> None:
    def runner(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, '{"streams":[]}', "")

    with pytest.raises(MediaToolError, match="incomplete metadata"):
        FFmpegTools(runner=runner).probe(tmp_path / "broken.mp4")

