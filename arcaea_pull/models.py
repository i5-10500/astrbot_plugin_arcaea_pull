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


class VerificationVerdict(str, Enum):
    VERIFIED = "VERIFIED"
    VERIFICATION_DISABLED = "VERIFICATION_DISABLED"
    TRUST_NOT_CONFIGURED = "TRUST_NOT_CONFIGURED"
    TRUST_CONFIGURATION_INVALID = "TRUST_CONFIGURATION_INVALID"
    VERIFIER_UNAVAILABLE = "VERIFIER_UNAVAILABLE"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    SIGNATURE_OUTPUT_INVALID = "SIGNATURE_OUTPUT_INVALID"
    UNTRUSTED_SIGNER = "UNTRUSTED_SIGNER"
    MANIFEST_INVALID = "MANIFEST_INVALID"
    PACKAGE_MISMATCH = "PACKAGE_MISMATCH"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    VERSION_CODE_MISMATCH = "VERSION_CODE_MISMATCH"
    ROLLBACK_DETECTED = "ROLLBACK_DETECTED"
    FILE_CHANGED = "FILE_CHANGED"
    STATE_INVALID = "STATE_INVALID"
    PUBLISH_FAILED = "PUBLISH_FAILED"
    QUARANTINE_FAILED = "QUARANTINE_FAILED"


@dataclass(frozen=True, slots=True)
class SignatureVerificationResult:
    signer_certificate_sha256: tuple[str, ...]
    verified_schemes: tuple[str, ...]
    backend: str


@dataclass(frozen=True, slots=True)
class ManifestIdentity:
    package_name: str
    version_name: str
    version_code: int
    backend: str


@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    version: str
    source_url: str
    path: Path
    size: int
    file_sha256: str
    package_name: str
    version_name: str
    version_code: int
    signer_certificate_sha256: tuple[str, ...]
    verified_at: str
    verification_backend: str


@dataclass(frozen=True, slots=True)
class AuthenticityResult:
    verdict: VerificationVerdict
    reason: str
    artifact: VerifiedArtifact | None = None
    event_key: str = ""
