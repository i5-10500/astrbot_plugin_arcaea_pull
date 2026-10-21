"""Bound APK archives without interpreting opaque remote version strings."""

from __future__ import annotations

import logging
import stat
from collections.abc import Mapping
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_retention_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 20:
        raise ValueError("old_versions_to_keep must be a whole number from 0 to 20")
    return value


def cleanup_old_apks(
    directory: Path,
    current_path: Path,
    *,
    old_versions_to_keep: int,
    timestamps: Mapping[Path, float] | None = None,
) -> tuple[Path, ...]:
    """Keep the current file and N recent archives, deleting only direct managed files."""
    removed: list[Path] = []
    try:
        if _is_link(directory):
            return ()
        root = directory.resolve()
        current = current_path.resolve()
        if current.parent != root or not current.is_file():
            return ()
        candidates: list[tuple[float, Path]] = []
        for candidate in directory.glob("arcaea_*.apk"):
            try:
                if _is_link(candidate):
                    continue
                resolved = candidate.resolve()
                if (
                    resolved.parent != root
                    or resolved == current
                    or not candidate.is_file()
                ):
                    continue
                modified_at = candidate.stat().st_mtime
                timestamp = (timestamps or {}).get(resolved, modified_at)
                candidates.append((timestamp, candidate))
            except OSError as exc:
                logger.warning("Could not inspect old APK %s: %s", candidate, exc)
        candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        for _, candidate in candidates[old_versions_to_keep:]:
            try:
                # Recheck immediately before deletion; never unlink a resolved external target.
                if _is_link(candidate) or candidate.resolve().parent != root:
                    continue
                candidate.unlink(missing_ok=True)
                removed.append(root / candidate.name)
                logger.info("Removed old APK %s", candidate)
            except OSError as exc:
                logger.warning("Could not remove old APK %s: %s", candidate, exc)
    except OSError as exc:
        logger.warning("Could not clean APK directory %s: %s", directory, exc)
    return tuple(removed)


def _is_link(path: Path) -> bool:
    """Include Windows junctions/reparse points on all supported Python versions."""
    return path.is_symlink() or bool(
        getattr(path.lstat(), "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
