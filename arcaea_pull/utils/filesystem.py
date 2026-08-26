"""Filesystem validation helpers."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path


class ArtifactValidationError(RuntimeError):
    """Downloaded artifact failed a basic APK/ZIP integrity check."""


def safe_version_component(version: str) -> str:
    component = re.sub(r"[^A-Za-z0-9._-]+", "_", version).strip("._")
    if not component:
        raise ArtifactValidationError("version cannot form a safe filename")
    return component


def validate_apk(path: Path, *, expected_size: int | None = None, min_size: int = 1) -> int:
    size = path.stat().st_size
    if size < max(min_size, 1):
        raise ArtifactValidationError(f"APK is too small: {size} byte(s)")
    if expected_size is not None and size != expected_size:
        raise ArtifactValidationError(
            f"incomplete download: expected {expected_size} byte(s), received {size}"
        )
    with path.open("rb") as stream:
        if stream.read(4) not in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}:
            raise ArtifactValidationError("file does not have a ZIP/APK signature")
    try:
        with zipfile.ZipFile(path) as archive:
            if not archive.namelist():
                raise ArtifactValidationError("APK/ZIP archive is empty")
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ArtifactValidationError(f"APK/ZIP member is corrupt: {bad_member}")
    except zipfile.BadZipFile as exc:
        raise ArtifactValidationError("file is not a readable APK/ZIP archive") from exc
    return size

