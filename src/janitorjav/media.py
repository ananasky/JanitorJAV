from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class MediaToolError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    duration_seconds: float
    width: int
    height: int
    codec_name: str | None = None


class CommandRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]: ...


def _default_runner(
    command: list[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


class FFmpegTools:
    def __init__(
        self,
        *,
        ffprobe_path: str = "ffprobe",
        ffmpeg_path: str = "ffmpeg",
        runner: CommandRunner = _default_runner,
    ) -> None:
        self.ffprobe_path = ffprobe_path
        self.ffmpeg_path = ffmpeg_path
        self._runner = runner

    def probe(self, video_path: Path, *, timeout: float = 60) -> VideoMetadata:
        command = [
            self.ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height:format=duration",
            "-of",
            "json",
            str(video_path),
        ]
        try:
            result = self._runner(command, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MediaToolError(f"ffprobe failed for {video_path}: {error}") from error
        if result.returncode != 0:
            raise MediaToolError(
                f"ffprobe returned {result.returncode} for {video_path}: {result.stderr.strip()}"
            )

        try:
            payload = json.loads(result.stdout)
            stream = payload["streams"][0]
            duration = float(payload["format"]["duration"])
            width = int(stream["width"])
            height = int(stream["height"])
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise MediaToolError(f"ffprobe returned incomplete metadata for {video_path}") from error
        if duration <= 0 or width <= 0 or height <= 0:
            raise MediaToolError(f"ffprobe returned invalid metadata for {video_path}")
        return VideoMetadata(duration, width, height, stream.get("codec_name"))

    def extract_frame(
        self,
        video_path: Path,
        timestamp_seconds: float,
        output_path: Path,
        *,
        timeout: float = 120,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(f"{output_path.stem}.partial{output_path.suffix}")
        command = [
            self.ffmpeg_path,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-ss",
            f"{timestamp_seconds:.3f}",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(temporary),
        ]
        try:
            result = self._runner(command, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            temporary.unlink(missing_ok=True)
            raise MediaToolError(f"frame extraction failed for {video_path}: {error}") from error
        if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
            temporary.unlink(missing_ok=True)
            raise MediaToolError(
                f"ffmpeg returned {result.returncode} for {video_path}: {result.stderr.strip()}"
            )
        temporary.replace(output_path)
