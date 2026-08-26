"""Typed domain models shared by the core services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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


class DistributionStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DistributionTargetResult:
    target: str
    status: DistributionStatus
    skipped: bool = False
    file_set_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DistributionResult:
    version: str
    targets: tuple[DistributionTargetResult, ...]

    @property
    def succeeded(self) -> int:
        return sum(
            item.status == DistributionStatus.SUCCESS and not item.skipped for item in self.targets
        )

    @property
    def failed(self) -> int:
        return sum(item.status == DistributionStatus.FAILED for item in self.targets)

    @property
    def skipped(self) -> int:
        return sum(item.skipped for item in self.targets)
