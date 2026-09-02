from __future__ import annotations

from pathlib import Path
from typing import Any

from .detection import DetectionMatch
from .models import AssetGroup, FrameEvidence, VideoAsset


def match_to_dict(match: object) -> dict[str, Any]:
    if not isinstance(match, DetectionMatch):
        return {"value": str(match)}
    return {
        "type": match.match_type.value,
        "raw_text": match.raw_text,
        "normalized_text": match.normalized_text,
        "confidence": match.confidence,
        "evidence_level": match.evidence_level.value,
        "start": match.start,
        "end": match.end,
    }


def frame_to_dict(frame: FrameEvidence) -> dict[str, Any]:
    return {
        "timestamp_seconds": frame.timestamp_seconds,
        "requested_positions": frame.requested_positions,
        "image_path": str(frame.image_path) if frame.image_path else None,
        "ocr_text": frame.ocr_text,
        "normalized_text": frame.normalized_text,
        "max_confidence": frame.max_confidence,
        "matches": [match_to_dict(item) for item in frame.matches],
    }


def video_to_dict(video: VideoAsset) -> dict[str, Any]:
    return {
        "path": str(video.path),
        "stem": video.stem,
        "extension": video.extension,
        "group_key": video.group_key,
        "cd_number": video.cd_number,
        "has_vr_marker": video.has_vr_marker,
        "duration_seconds": video.duration_seconds,
        "width": video.width,
        "height": video.height,
        "associated_files": [str(path) for path in video.associated_files],
        "missing_files": video.missing_files,
        "frames": [frame_to_dict(frame) for frame in video.frames],
        "tags": sorted(tag.value for tag in video.tags),
    }


def group_to_dict(group: AssetGroup, *, asset_id: str) -> dict[str, Any]:
    durations = [video.duration_seconds for video in group.videos if video.duration_seconds is not None]
    return {
        "asset_id": asset_id,
        "directory": str(group.directory),
        "group_key": group.group_key,
        "group_type": group.group_type.value,
        "is_vr": group.is_vr,
        "videos": [video_to_dict(video) for video in group.videos],
        "files": [str(path) for path in group.files],
        "tags": sorted(tag.value for tag in group.tags),
        "review_status": group.review_status.value,
        "total_duration_seconds": sum(durations) if durations else None,
        "max_width": max((video.width or 0 for video in group.videos), default=0) or None,
        "max_height": max((video.height or 0 for video in group.videos), default=0) or None,
    }


def snapshot_paths(record: dict[str, Any]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for value in record.get("files", []):
        path = Path(value)
        try:
            stat = path.stat()
        except OSError:
            continue
        result[str(path)] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return result

