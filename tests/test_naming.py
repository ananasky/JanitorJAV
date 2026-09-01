from pathlib import Path

from janitorjav.models import AssetGroupType, Tag
from janitorjav.naming import discover_asset_groups, parse_video_stem


def test_parse_cd_and_vr_markers_in_any_order() -> None:
    first = parse_video_stem("ABC-123-VR-CD02")
    second = parse_video_stem("ABC-123-cd2-vr")

    assert first.group_key == "ABC-123"
    assert first.cd_number == 2
    assert first.has_vr_marker is True
    assert second.group_key == "ABC-123"
    assert second.cd_number == 2
    assert second.has_vr_marker is True


def test_marker_must_be_hyphen_delimited() -> None:
    parsed = parse_video_stem("ABC-VRVIDEO-CDROM")
    assert parsed.group_key == "ABC-VRVIDEO-CDROM"
    assert parsed.cd_number is None
    assert parsed.has_vr_marker is False


def _touch(directory: Path, *names: str) -> None:
    for name in names:
        (directory / name).touch()


def test_discover_complete_single_asset(tmp_path: Path) -> None:
    _touch(
        tmp_path,
        "ABC-123.mp4",
        "ABC-123.nfo",
        "ABC-123-poster.jpg",
        "ABC-123-fanart.jpg",
        "ABC-123-thumb.jpg",
        "ABC-123.AI.srt",
    )

    groups = discover_asset_groups(tmp_path)

    assert len(groups) == 1
    assert groups[0].group_type is AssetGroupType.SINGLE
    assert not groups[0].tags
    assert {path.name for path in groups[0].videos[0].associated_files} == {
        "ABC-123.nfo",
        "ABC-123-poster.jpg",
        "ABC-123-fanart.jpg",
        "ABC-123-thumb.jpg",
        "ABC-123.AI.srt",
    }


def test_cd_members_group_and_vr_propagates(tmp_path: Path) -> None:
    for stem in ("ABC-123-CD1-VR", "ABC-123-CD2"):
        _touch(
            tmp_path,
            f"{stem}.mkv",
            f"{stem}.nfo",
            f"{stem}-poster.jpg",
            f"{stem}-fanart.jpg",
            f"{stem}-thumb.jpg",
        )

    groups = discover_asset_groups(tmp_path)

    assert len(groups) == 1
    assert groups[0].group_type is AssetGroupType.CD_SET
    assert [video.cd_number for video in groups[0].videos] == [1, 2]
    assert Tag.VR_VIDEO in groups[0].tags
    assert Tag.INCONSISTENT_VR_NAMING in groups[0].tags


def test_missing_sidecars_and_legacy_format_are_independent(tmp_path: Path) -> None:
    _touch(tmp_path, "OLD-001.rmvb")

    group = discover_asset_groups(tmp_path)[0]

    assert group.tags == {
        Tag.LEGACY_FORMAT_RMVB,
        Tag.MISSING_NFO,
        Tag.MISSING_POSTER,
        Tag.MISSING_FANART,
        Tag.MISSING_THUMB,
    }

