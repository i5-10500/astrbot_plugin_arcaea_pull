"""Typed domain models shared by the core services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RemoteArtifact:
    version: str
    url: str


@dataclass(frozen=True, slots=True)
class DownloadRecord:
    version: str
    source_url: str
    path: Path
    size: int
    sha256: str
    downloaded_at: str
    reused: bool = False


@dataclass(frozen=True, slots=True)
class CheckResult:
    artifact: RemoteArtifact
    changed: bool
    notified: bool = False
    downloaded: DownloadRecord | None = None
    notification_error: str | None = None

