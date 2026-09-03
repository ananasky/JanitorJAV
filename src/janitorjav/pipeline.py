from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .detection import EvidenceLevel, MatchType, detect_point_text, normalize_ocr_text
from .media import FFmpegTools, MediaToolError
from .models import AssetGroup, FrameEvidence, Tag, VideoAsset
from .ocr import OCREngine, OCRLine
from .sampling import calculate_sample_points


@dataclass(frozen=True, slots=True)
class ScanPipelineConfig:
    files_only: bool = False
    high_confidence_threshold: float = 0.75
    short_video_seconds: float = 180.0
    frame_workers: int = 4


def stable_asset_id(group: AssetGroup) -> str:
    identity = f"{group.directory}\0{group.group_key}".encode("utf-8", errors="surrogatepass")
    return hashlib.sha256(identity).hexdigest()[:20]


class ScanPipeline:
    def __init__(
        self,
        media_tools: FFmpegTools,
        ocr_engine: OCREngine,
        evidence_root: Path,
        *,
        config: ScanPipelineConfig = ScanPipelineConfig(),
    ) -> None:
        self.media_tools = media_tools
        self.ocr_engine = ocr_engine
        self.evidence_root = evidence_root
        self.config = config
        self._ocr_lock = threading.Lock()

    def scan_group(self, group: AssetGroup) -> AssetGroup:
        if self.config.files_only:
            self._propagate_tags(group)
            return group
        if group.is_vr:
            for video in group.videos:
                self._probe(video, apply_short_rule=False)
            self._propagate_tags(group)
            return group

        for video in group.videos:
            if not self._probe(video, apply_short_rule=True):
                continue
            self._extract_and_recognize(group, video)
        self._propagate_tags(group)
        return group

    def _probe(self, video: VideoAsset, *, apply_short_rule: bool) -> bool:
        try:
            metadata = self.media_tools.probe(video.path)
        except MediaToolError:
            video.tags.update({Tag.PROBE_FAILED, Tag.DURATION_UNKNOWN, Tag.RESOLUTION_UNKNOWN})
            return False
        video.duration_seconds = metadata.duration_seconds
        video.width = metadata.width
        video.height = metadata.height
        if apply_short_rule and metadata.duration_seconds < self.config.short_video_seconds:
            video.tags.add(Tag.DURATION_UNDER_3M)
        return True

    def _extract_and_recognize(self, group: AssetGroup, video: VideoAsset) -> None:
        assert video.duration_seconds is not None
        video_evidence_root = self.evidence_root / stable_asset_id(group) / _video_id(video)
        extracted: list[tuple[FrameEvidence, Path]] = []

        pending: list[tuple[FrameEvidence, Path]] = []
        for index, point in enumerate(calculate_sample_points(video.duration_seconds), start=1):
            path = video_evidence_root / f"{index:02d}-{point.timestamp_seconds:.3f}.jpg"
            evidence = FrameEvidence(point.timestamp_seconds, list(point.sources), image_path=path)
            video.frames.append(evidence)
            pending.append((evidence, path))

        worker_count = max(1, min(self.config.frame_workers, len(pending)))
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="janitorjav-frame") as executor:
            futures = [
                executor.submit(
                    self.media_tools.extract_frame,
                    video.path,
                    evidence.timestamp_seconds,
                    path,
                )
                for evidence, path in pending
            ]
            for item, future in zip(pending, futures, strict=True):
                try:
                    future.result()
                except MediaToolError:
                    video.tags.add(Tag.FRAME_EXTRACT_FAILED)
                    continue
                extracted.append(item)

        if not extracted:
            return
        try:
            with self._ocr_lock:
                batches = self.ocr_engine.recognize([path for _, path in extracted])
        except Exception:
            video.tags.add(Tag.OCR_FAILED)
            return
        if len(batches) != len(extracted):
            video.tags.add(Tag.OCR_FAILED)
            return

        for (evidence, _), lines in zip(extracted, batches, strict=True):
            self._apply_ocr(evidence, video, lines)

    def _apply_ocr(
        self,
        evidence: FrameEvidence,
        video: VideoAsset,
        lines: list[OCRLine],
    ) -> None:
        evidence.ocr_text = "\n".join(line.text for line in lines)
        confidences = [line.confidence for line in lines]
        evidence.max_confidence = max(confidences, default=None)
        normalized_parts: list[str] = []

        for line in lines:
            matches = detect_point_text(
                line.text,
                confidence=line.confidence,
                high_confidence_threshold=self.config.high_confidence_threshold,
            )
            evidence.matches.extend(matches)
            normalized_parts.append(normalize_ocr_text(line.text))
            for match in matches:
                if match.evidence_level is EvidenceLevel.HIGH:
                    video.tags.add(Tag.URL_DETECTED)
                else:
                    video.tags.add(Tag.POSSIBLE_URL_DETECTED)
                if match.match_type is MatchType.IPV4:
                    video.tags.add(Tag.IP_ADDRESS_DETECTED)
        evidence.normalized_text = "\n".join(normalized_parts)

    @staticmethod
    def _propagate_tags(group: AssetGroup) -> None:
        for video in group.videos:
            group.tags.update(video.tags)


def _video_id(video: VideoAsset) -> str:
    return hashlib.sha256(str(video.path).encode("utf-8", errors="surrogatepass")).hexdigest()[:16]
