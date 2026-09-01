from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import AssetGroup, AssetGroupType, Tag, VideoAsset


DEFAULT_VIDEO_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".m4v",
        ".ts",
        ".mts",
        ".m2ts",
        ".webm",
        ".flv",
        ".mpg",
        ".mpeg",
        ".rm",
        ".rmvb",
    }
)

DEFAULT_SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".vtt", ".sub"})

_CD_TOKEN = re.compile(r"^cd(?P<number>\d+)$", re.IGNORECASE)
_VR_TOKEN = re.compile(r"^vr$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedVideoName:
    original_stem: str
    group_key: str
    cd_number: int | None
    has_vr_marker: bool


def parse_video_stem(stem: str) -> ParsedVideoName:
    """Parse standalone hyphen-delimited CD/VR markers from a video stem."""
    tokens = stem.split("-")
    kept: list[str] = []
    cd_number: int | None = None
    has_vr = False

    for token in tokens:
        cd_match = _CD_TOKEN.fullmatch(token)
        if cd_match:
            if cd_number is None:
                cd_number = int(cd_match.group("number"))
            else:
                kept.append(token)
            continue
        if _VR_TOKEN.fullmatch(token):
            has_vr = True
            continue
        kept.append(token)

    group_key = "-".join(kept) or stem
    return ParsedVideoName(stem, group_key, cd_number, has_vr)


def _casefold_index(paths: list[Path]) -> dict[str, Path]:
    return {path.name.casefold(): path for path in paths}


def associated_files_for_video(
    video_path: Path,
    directory_entries: list[Path],
    subtitle_extensions: frozenset[str] = DEFAULT_SUBTITLE_EXTENSIONS,
) -> tuple[list[Path], list[str]]:
    """Find strict MDC sidecars for one video and report required omissions."""
    stem = video_path.stem
    index = _casefold_index([entry for entry in directory_entries if entry.is_file()])
    associated: list[Path] = []
    missing: list[str] = []

    required = {
        "nfo": f"{stem}.nfo",
        "poster": f"{stem}-poster.jpg",
        "fanart": f"{stem}-fanart.jpg",
        "thumb": f"{stem}-thumb.jpg",
    }
    for kind, filename in required.items():
        found = index.get(filename.casefold())
        if found is None:
            missing.append(kind)
        else:
            associated.append(found)

    for extension in subtitle_extensions:
        for filename in (f"{stem}{extension}", f"{stem}.AI{extension}"):
            found = index.get(filename.casefold())
            if found is not None:
                associated.append(found)

    return sorted(set(associated), key=lambda path: path.name.casefold()), missing


def discover_asset_groups(
    directory: Path,
    video_extensions: frozenset[str] = DEFAULT_VIDEO_EXTENSIONS,
) -> list[AssetGroup]:
    """Build independent or CD asset groups from one asset directory."""
    entries = list(directory.iterdir())
    videos: list[VideoAsset] = []

    for path in entries:
        if not path.is_file() or path.suffix.casefold() not in video_extensions:
            continue
        parsed = parse_video_stem(path.stem)
        associated, missing = associated_files_for_video(path, entries)
        video = VideoAsset(
            path=path,
            stem=path.stem,
            extension=path.suffix.casefold(),
            group_key=parsed.group_key,
            cd_number=parsed.cd_number,
            has_vr_marker=parsed.has_vr_marker,
            associated_files=associated,
            missing_files=missing,
        )
        missing_tags = {
            "nfo": Tag.MISSING_NFO,
            "poster": Tag.MISSING_POSTER,
            "fanart": Tag.MISSING_FANART,
            "thumb": Tag.MISSING_THUMB,
        }
        video.tags.update(missing_tags[item] for item in missing)
        if video.extension == ".rm":
            video.tags.add(Tag.LEGACY_FORMAT_RM)
        elif video.extension == ".rmvb":
            video.tags.add(Tag.LEGACY_FORMAT_RMVB)
        videos.append(video)

    grouped: dict[tuple[str, bool], list[VideoAsset]] = {}
    singles: list[VideoAsset] = []
    for video in videos:
        if video.cd_number is None:
            singles.append(video)
        else:
            grouped.setdefault((video.group_key.casefold(), True), []).append(video)

    result: list[AssetGroup] = []
    for video in singles:
        group = AssetGroup(directory, video.group_key, AssetGroupType.SINGLE, [video])
        _propagate_group_tags(group)
        result.append(group)

    for (_, _), members in grouped.items():
        members.sort(key=lambda item: (item.cd_number or 0, item.path.name.casefold()))
        group = AssetGroup(directory, members[0].group_key, AssetGroupType.CD_SET, members)
        _propagate_group_tags(group)
        if any(member.has_vr_marker for member in members) and not all(
            member.has_vr_marker for member in members
        ):
            group.tags.add(Tag.INCONSISTENT_VR_NAMING)
        result.append(group)

    return sorted(result, key=lambda item: item.group_key.casefold())


def _propagate_group_tags(group: AssetGroup) -> None:
    for video in group.videos:
        group.tags.update(video.tags)
    if group.is_vr:
        group.tags.add(Tag.VR_VIDEO)

