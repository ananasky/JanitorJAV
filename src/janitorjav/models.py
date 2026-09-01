from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class AssetGroupType(StrEnum):
    SINGLE = "single"
    CD_SET = "cd_set"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    KEEP = "keep"
    READY_TO_QUARANTINE = "ready_to_quarantine"
    QUARANTINED = "quarantined"
    QUARANTINE_FAILED = "quarantine_failed"
    RESTORED = "restored"


class Tag(StrEnum):
    URL_DETECTED = "url_detected"
    POSSIBLE_URL_DETECTED = "possible_url_detected"
    IP_ADDRESS_DETECTED = "ip_address_detected"
    DURATION_UNDER_3M = "duration_under_3m"
    LEGACY_FORMAT_RM = "legacy_format_rm"
    LEGACY_FORMAT_RMVB = "legacy_format_rmvb"
    VR_VIDEO = "vr_video"
    INCONSISTENT_VR_NAMING = "inconsistent_vr_naming"
    PROBE_FAILED = "probe_failed"
    DECODE_FAILED = "decode_failed"
    FRAME_EXTRACT_FAILED = "frame_extract_failed"
    OCR_FAILED = "ocr_failed"
    NETWORK_READ_FAILED = "network_read_failed"
    DURATION_UNKNOWN = "duration_unknown"
    RESOLUTION_UNKNOWN = "resolution_unknown"
    MISSING_NFO = "missing_nfo"
    MISSING_POSTER = "missing_poster"
    MISSING_FANART = "missing_fanart"
    MISSING_THUMB = "missing_thumb"
    SOURCE_CHANGED_SINCE_SCAN = "source_changed_since_scan"
    QUARANTINE_FAILED = "quarantine_failed"
    QUARANTINE_FILE_CONFLICT = "quarantine_file_conflict"
    FOLDER_EFFECTIVELY_EMPTY = "folder_effectively_empty"


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    path: Path
    size: int
    mtime_ns: int


@dataclass(slots=True)
class FrameEvidence:
    timestamp_seconds: float
    requested_positions: list[str]
    image_path: Path | None = None
    ocr_text: str = ""
    normalized_text: str = ""
    max_confidence: float | None = None
    matches: list[object] = field(default_factory=list)


@dataclass(slots=True)
class VideoAsset:
    path: Path
    stem: str
    extension: str
    group_key: str
    cd_number: int | None = None
    has_vr_marker: bool = False
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    associated_files: list[Path] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    frames: list[FrameEvidence] = field(default_factory=list)
    tags: set[Tag] = field(default_factory=set)


@dataclass(slots=True)
class AssetGroup:
    directory: Path
    group_key: str
    group_type: AssetGroupType
    videos: list[VideoAsset]
    tags: set[Tag] = field(default_factory=set)
    review_status: ReviewStatus = ReviewStatus.PENDING

    @property
    def is_vr(self) -> bool:
        return any(video.has_vr_marker for video in self.videos)

    @property
    def files(self) -> list[Path]:
        result: list[Path] = []
        for video in self.videos:
            result.append(video.path)
            result.extend(video.associated_files)
        return result

