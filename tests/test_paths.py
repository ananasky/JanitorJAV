from pathlib import Path

import pytest

from janitorjav.paths import (
    PathValidationError,
    quarantine_root_for,
    quarantine_target,
    validate_or_create_quarantine,
)


def test_unc_quarantine_is_fixed_sibling() -> None:
    assert quarantine_root_for(r"\\server\media\JAV") == (
        r"\\server\media\JanitorJAV_Quarantine"
    )


def test_drive_quarantine_is_fixed_sibling() -> None:
    assert quarantine_root_for(r"D:\Media\JAV") == r"D:\Media\JanitorJAV_Quarantine"


def test_scan_root_cannot_be_quarantine() -> None:
    with pytest.raises(PathValidationError):
        quarantine_root_for(r"D:\Media\JanitorJAV_Quarantine")


def test_create_empty_quarantine_and_map_target(tmp_path: Path) -> None:
    scan = tmp_path / "JAV"
    scan.mkdir()
    source = scan / "2026" / "ABC-123" / "ABC-123.mp4"
    source.parent.mkdir(parents=True)
    source.touch()

    quarantine = validate_or_create_quarantine(scan)

    assert quarantine.is_dir()
    assert list(quarantine.iterdir()) == []
    assert quarantine_target(scan, quarantine, source) == (
        quarantine / "2026" / "ABC-123" / "ABC-123.mp4"
    )


def test_non_empty_quarantine_is_rejected(tmp_path: Path) -> None:
    scan = tmp_path / "JAV"
    scan.mkdir()
    quarantine = tmp_path / "JanitorJAV_Quarantine"
    quarantine.mkdir()
    (quarantine / "existing.txt").touch()

    with pytest.raises(PathValidationError, match="must be empty"):
        validate_or_create_quarantine(scan)

