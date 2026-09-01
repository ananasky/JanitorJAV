from __future__ import annotations

import ntpath
from pathlib import Path


QUARANTINE_DIRECTORY_NAME = "JanitorJAV_Quarantine"


class PathValidationError(ValueError):
    pass


def quarantine_root_for(scan_root: str) -> str:
    """Return the fixed sibling quarantine path using Windows path semantics."""
    normalized = ntpath.normpath(scan_root)
    parent = ntpath.dirname(normalized)
    name = ntpath.basename(normalized)
    if not parent or not name:
        raise PathValidationError("scan root must not be a drive or share root")
    if name.casefold() == QUARANTINE_DIRECTORY_NAME.casefold():
        raise PathValidationError("scan root cannot be the quarantine directory")
    return ntpath.join(parent, QUARANTINE_DIRECTORY_NAME)


def validate_or_create_quarantine(scan_root: Path) -> Path:
    """Validate a native scan path and create its fixed empty sibling quarantine."""
    scan_root = scan_root.resolve()
    if not scan_root.is_dir():
        raise PathValidationError(f"scan root is not a directory: {scan_root}")
    if scan_root.name.casefold() == QUARANTINE_DIRECTORY_NAME.casefold():
        raise PathValidationError("scan root cannot be the quarantine directory")

    quarantine = scan_root.parent / QUARANTINE_DIRECTORY_NAME
    if quarantine.exists():
        if not quarantine.is_dir():
            raise PathValidationError("quarantine path exists and is not a directory")
        if any(quarantine.iterdir()):
            raise PathValidationError("quarantine directory must be empty")
    else:
        quarantine.mkdir()

    probe = quarantine / ".janitorjav-write-test"
    try:
        probe.touch(exist_ok=False)
        probe.unlink()
    except OSError as error:
        raise PathValidationError(f"quarantine directory is not writable: {error}") from error
    return quarantine


def quarantine_target(scan_root: Path, quarantine_root: Path, source: Path) -> Path:
    try:
        relative = source.resolve().relative_to(scan_root.resolve())
    except ValueError as error:
        raise PathValidationError("source must be inside scan root") from error
    return quarantine_root / relative

