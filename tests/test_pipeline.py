import threading
import time
from pathlib import Path

from janitorjav.media import VideoMetadata
from janitorjav.models import AssetGroup, AssetGroupType, Tag, VideoAsset
from janitorjav.ocr import OCRLine
from janitorjav.pipeline import ScanPipeline, ScanPipelineConfig


class FakeMediaTools:
    def __init__(self, duration: float = 600) -> None:
        self.duration = duration

    def probe(self, video_path: Path) -> VideoMetadata:
        return VideoMetadata(self.duration, 1920, 1080, "h264")

    def extract_frame(self, video_path: Path, timestamp_seconds: float, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"jpeg")


class FakeOCR:
    name = "fake"

    def recognize(self, image_paths: list[Path]) -> list[list[OCRLine]]:
        results = [[] for _ in image_paths]
        results[0] = [OCRLine("visit ab.cd", 0.9)]
        results[-1] = [OCRLine("192.168.1.10", 0.4)]
        return results


def _group(tmp_path: Path, *, vr: bool = False) -> AssetGroup:
    path = tmp_path / ("ABC-123-VR.mp4" if vr else "ABC-123.mp4")
    path.touch()
    video = VideoAsset(
        path=path,
        stem=path.stem,
        extension=".mp4",
        group_key="ABC-123",
        has_vr_marker=vr,
    )
    tags = {Tag.VR_VIDEO} if vr else set()
    return AssetGroup(tmp_path, "ABC-123", AssetGroupType.SINGLE, [video], tags=tags)


def test_pipeline_extracts_all_points_and_propagates_matches(tmp_path: Path) -> None:
    group = _group(tmp_path)
    pipeline = ScanPipeline(FakeMediaTools(), FakeOCR(), tmp_path / "evidence")

    pipeline.scan_group(group)

    video = group.videos[0]
    assert len(video.frames) == 10
    assert video.duration_seconds == 600
    assert (video.width, video.height) == (1920, 1080)
    assert Tag.URL_DETECTED in group.tags
    assert Tag.POSSIBLE_URL_DETECTED in group.tags
    assert Tag.IP_ADDRESS_DETECTED in group.tags
    assert all(frame.image_path and frame.image_path.exists() for frame in video.frames)


def test_short_video_is_tagged(tmp_path: Path) -> None:
    group = _group(tmp_path)
    pipeline = ScanPipeline(FakeMediaTools(duration=120), FakeOCR(), tmp_path / "evidence")
    pipeline.scan_group(group)
    assert Tag.DURATION_UNDER_3M in group.tags


def test_vr_is_probed_but_not_sampled(tmp_path: Path) -> None:
    group = _group(tmp_path, vr=True)
    pipeline = ScanPipeline(FakeMediaTools(), FakeOCR(), tmp_path / "evidence")
    pipeline.scan_group(group)
    video = group.videos[0]
    assert video.duration_seconds == 600
    assert video.frames == []
    assert group.tags == {Tag.VR_VIDEO}


def test_frame_extraction_uses_configured_parallelism(tmp_path: Path) -> None:
    class ConcurrentMediaTools(FakeMediaTools):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def extract_frame(self, video_path: Path, timestamp_seconds: float, output_path: Path) -> None:
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.02)
            super().extract_frame(video_path, timestamp_seconds, output_path)
            with self.lock:
                self.active -= 1

    media = ConcurrentMediaTools()
    pipeline = ScanPipeline(
        media,
        FakeOCR(),
        tmp_path / "evidence",
        config=ScanPipelineConfig(frame_workers=3),
    )

    pipeline.scan_group(_group(tmp_path))

    assert media.max_active == 3
