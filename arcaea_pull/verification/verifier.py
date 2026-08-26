"""Orchestrate signature, trust, identity, rollback, and file lifecycle checks."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.state_manager import StateManager
from ..models import (
    AuthenticityResult,
    DownloadRecord,
    VerificationVerdict,
    VerifiedArtifact,
)
from ..utils.filesystem import safe_version_component
from ..utils.hashing import sha256_file
from .apksigner_backend import ApkSignerBackend, normalize_fingerprint
from .base import (
    MalformedToolOutputError,
    SignatureInvalidError,
    ToolUnavailableError,
    VerificationBackendError,
)
from .manifest_inspector import ApkManifestInspector
from .tools import resolve_aapt2, resolve_apksigner


class AuthenticityVerifier:
    def __init__(
        self,
        state: StateManager,
        downloads_root: str | Path,
        *,
        trusted_signers: Iterable[str],
        trusted_package_name: str,
        apksigner_path: str = "",
        aapt2_path: str = "",
        timeout: float = 60,
        signature_backend: Any | None = None,
        manifest_inspector: Any | None = None,
    ) -> None:
        self.state = state
        self.downloads_root = Path(downloads_root)
        self.pending_dir = self.downloads_root / "pending"
        self.verified_dir = self.downloads_root / "verified"
        self.quarantine_dir = self.downloads_root / "quarantine"
        self._raw_trusted_signers = tuple(str(item) for item in trusted_signers)
        self.trusted_package_name = str(trusted_package_name).strip()
        self.apksigner_path = str(apksigner_path).strip()
        self.aapt2_path = str(aapt2_path).strip()
        self.timeout = max(float(timeout), 1)
        self._signature_backend = signature_backend
        self._manifest_inspector = manifest_inspector
        self._lock = asyncio.Lock()

    def preflight(self) -> tuple[Any, Any, frozenset[str]]:
        if not self._raw_trusted_signers or not self.trusted_package_name:
            raise ToolUnavailableError(
                "trusted signer SHA-256 and trusted package name must be configured"
            )
        try:
            trusted = frozenset(normalize_fingerprint(item) for item in self._raw_trusted_signers)
        except ValueError as exc:
            raise ToolUnavailableError(f"invalid trusted signer configuration: {exc}") from exc
        signature_backend = self._signature_backend
        if signature_backend is None:
            signature_backend = ApkSignerBackend(
                resolve_apksigner(self.apksigner_path), timeout=self.timeout
            )
        manifest_inspector = self._manifest_inspector
        if manifest_inspector is None:
            manifest_inspector = ApkManifestInspector(
                resolve_aapt2(self.aapt2_path), timeout=self.timeout
            )
        return signature_backend, manifest_inspector, trusted

    async def verify(self, record: DownloadRecord, *, expected_version: str) -> AuthenticityResult:
        async with self._lock:
            try:
                signature_backend, manifest_inspector, trusted = await asyncio.to_thread(
                    self.preflight
                )
            except ToolUnavailableError as exc:
                verdict = (
                    VerificationVerdict.TRUST_NOT_CONFIGURED
                    if not self._raw_trusted_signers or not self.trusted_package_name
                    else VerificationVerdict.VERIFIER_UNAVAILABLE
                )
                if "invalid trusted signer" in str(exc):
                    verdict = VerificationVerdict.TRUST_CONFIGURATION_INVALID
                return await self._failure(record, verdict, str(exc), quarantine=False)

            cached = await asyncio.to_thread(
                self._load_verified, expected_version, record.sha256, trusted
            )
            if cached is not None:
                return AuthenticityResult(
                    verdict=VerificationVerdict.VERIFIED,
                    reason="verified artifact reused after path and SHA-256 validation",
                    artifact=cached,
                )

            if not await asyncio.to_thread(_matches_record, record):
                return await self._failure(
                    record,
                    VerificationVerdict.FILE_CHANGED,
                    "downloaded APK path, size, or SHA-256 no longer matches its record",
                )

            try:
                signature = await signature_backend.verify(record.path)
            except SignatureInvalidError as exc:
                return await self._failure(record, VerificationVerdict.SIGNATURE_INVALID, str(exc))
            except MalformedToolOutputError as exc:
                return await self._failure(
                    record, VerificationVerdict.SIGNATURE_OUTPUT_INVALID, str(exc)
                )
            except VerificationBackendError as exc:
                return await self._failure(
                    record, VerificationVerdict.VERIFIER_UNAVAILABLE, str(exc), quarantine=False
                )
            except Exception as exc:
                return await self._failure(
                    record,
                    VerificationVerdict.VERIFIER_UNAVAILABLE,
                    f"unexpected apksigner failure: {exc}",
                    quarantine=False,
                )

            signer_set = frozenset(signature.signer_certificate_sha256)
            if not signer_set or not signer_set.issubset(trusted):
                return await self._failure(
                    record,
                    VerificationVerdict.UNTRUSTED_SIGNER,
                    "one or more APK signer certificates are not explicitly trusted",
                )

            try:
                manifest = await manifest_inspector.inspect(record.path)
            except MalformedToolOutputError as exc:
                return await self._failure(
                    record,
                    VerificationVerdict.MANIFEST_INVALID,
                    f"manifest identity could not be read reliably: {exc}",
                )
            except VerificationBackendError as exc:
                return await self._failure(
                    record,
                    VerificationVerdict.VERIFIER_UNAVAILABLE,
                    f"manifest inspector unavailable: {exc}",
                    quarantine=False,
                )
            except Exception as exc:
                return await self._failure(
                    record,
                    VerificationVerdict.MANIFEST_INVALID,
                    f"unexpected manifest inspector failure: {exc}",
                )
            if manifest.package_name != self.trusted_package_name:
                return await self._failure(
                    record,
                    VerificationVerdict.PACKAGE_MISMATCH,
                    f"manifest package {manifest.package_name!r} does not match configured package",
                )
            if manifest.version_name != expected_version:
                return await self._failure(
                    record,
                    VerificationVerdict.VERSION_MISMATCH,
                    "manifest versionName "
                    f"{manifest.version_name!r} does not exactly match API version",
                )

            verification_state = self.state.load()["verification"]
            last_version = verification_state.get("last_verified_version")
            last_code = verification_state.get("last_verified_version_code")
            if last_code is not None and (
                isinstance(last_code, bool)
                or not isinstance(last_code, int)
                or not isinstance(last_version, str)
                or not last_version
            ):
                return await self._failure(
                    record,
                    VerificationVerdict.STATE_INVALID,
                    "stored rollback-protection state is malformed",
                    quarantine=False,
                )
            if isinstance(last_code, int):
                if last_version == expected_version and manifest.version_code != last_code:
                    return await self._failure(
                        record,
                        VerificationVerdict.VERSION_CODE_MISMATCH,
                        "same versionName has a different versionCode than the trusted record",
                    )
                if last_version != expected_version and manifest.version_code < last_code:
                    return await self._failure(
                        record,
                        VerificationVerdict.ROLLBACK_DETECTED,
                        f"versionCode {manifest.version_code} is lower than trusted {last_code}",
                    )

            if not await asyncio.to_thread(_matches_record, record):
                return await self._failure(
                    record,
                    VerificationVerdict.FILE_CHANGED,
                    "APK changed while Android verification tools were running",
                )

            try:
                verified_path = await asyncio.to_thread(
                    self._publish_verified, record, expected_version
                )
            except OSError as exc:
                return await self._failure(
                    record,
                    VerificationVerdict.PUBLISH_FAILED,
                    f"could not publish verified APK: {exc}",
                    quarantine=False,
                )
            verified_at = datetime.now(timezone.utc).isoformat()
            artifact = VerifiedArtifact(
                version=expected_version,
                source_url=record.source_url,
                path=verified_path,
                size=record.size,
                file_sha256=record.sha256,
                package_name=manifest.package_name,
                version_name=manifest.version_name,
                version_code=manifest.version_code,
                signer_certificate_sha256=tuple(sorted(signer_set)),
                verified_at=verified_at,
                verification_backend=f"{signature.backend}+{manifest.backend}",
            )
            self.state.record_verification_success(artifact)
            self.state.record_download_success(
                DownloadRecord(
                    version=record.version,
                    source_url=record.source_url,
                    path=verified_path,
                    size=record.size,
                    sha256=record.sha256,
                    downloaded_at=record.downloaded_at,
                    reused=record.reused,
                )
            )
            return AuthenticityResult(
                verdict=VerificationVerdict.VERIFIED,
                reason="APK signature, signer, package, version, and rollback checks passed",
                artifact=artifact,
            )

    def load_verified(self, version: str) -> VerifiedArtifact | None:
        try:
            _, _, trusted = self.preflight()
        except ToolUnavailableError:
            return None
        return self._load_verified(version, None, trusted)

    def _load_verified(
        self,
        version: str,
        expected_sha256: str | None,
        trusted: frozenset[str],
    ) -> VerifiedArtifact | None:
        values = self.state.verified_artifact(version)
        if not values:
            return None
        try:
            artifact = _artifact_from_state(values)
            if artifact.version != version or artifact.version_name != version:
                return None
            resolved = artifact.path.resolve()
            if resolved.parent != self.verified_dir.resolve() or not resolved.is_file():
                return None
            if expected_sha256 and artifact.file_sha256 != expected_sha256:
                return None
            if resolved.stat().st_size != artifact.size:
                return None
            if sha256_file(resolved) != artifact.file_sha256:
                return None
            if artifact.package_name != self.trusted_package_name:
                return None
            if not set(artifact.signer_certificate_sha256).issubset(trusted):
                return None
            verification = self.state.load()["verification"]
            last_version = verification.get("last_verified_version")
            last_code = verification.get("last_verified_version_code")
            if last_code is not None and (
                isinstance(last_code, bool)
                or not isinstance(last_code, int)
                or not isinstance(last_version, str)
                or not last_version
            ):
                return None
            if isinstance(last_code, int):
                if last_version == version and artifact.version_code != last_code:
                    return None
                if last_version != version and artifact.version_code < last_code:
                    return None
            return artifact
        except (KeyError, OSError, TypeError, ValueError):
            return None

    async def _failure(
        self,
        record: DownloadRecord,
        verdict: VerificationVerdict,
        reason: str,
        *,
        quarantine: bool = True,
    ) -> AuthenticityResult:
        final_verdict = verdict
        quarantine_path: Path | None = None
        failure_sha256 = record.sha256
        failure_size = record.size
        if quarantine and record.path.is_file():
            try:
                quarantine_path, failure_size, failure_sha256 = await asyncio.to_thread(
                    self._publish_quarantine, record, verdict
                )
                self.state.record_download_success(
                    DownloadRecord(
                        version=record.version,
                        source_url=record.source_url,
                        path=quarantine_path,
                        size=failure_size,
                        sha256=failure_sha256,
                        downloaded_at=record.downloaded_at,
                        reused=record.reused,
                    )
                )
            except OSError as exc:
                final_verdict = VerificationVerdict.QUARANTINE_FAILED
                reason = f"{verdict.value}; quarantine failed: {exc}"
        event_key = f"{record.version}:{failure_sha256}:{final_verdict.value}"
        self.state.record_verification_failure(
            version=record.version,
            file_sha256=failure_sha256,
            path=record.path,
            verdict=final_verdict.value,
            reason=reason,
            attempted_at=datetime.now(timezone.utc).isoformat(),
            quarantine_path=quarantine_path,
            event_key=event_key,
        )
        return AuthenticityResult(
            verdict=final_verdict,
            reason=reason,
            event_key=event_key,
        )

    def _publish_verified(self, record: DownloadRecord, version: str) -> Path:
        self.verified_dir.mkdir(parents=True, exist_ok=True)
        target = self.verified_dir / f"arcaea_{safe_version_component(version)}.apk"
        return _publish(record.path, target, record.sha256, self.downloads_root)

    def _publish_quarantine(
        self, record: DownloadRecord, verdict: VerificationVerdict
    ) -> tuple[Path, int, str]:
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        actual_size = record.path.stat().st_size
        actual_digest = sha256_file(record.path)
        target = self.quarantine_dir / (
            f"arcaea_{safe_version_component(record.version)}_{actual_digest[:12]}_"
            f"{verdict.value.lower()}.apk"
        )
        path = _publish(record.path, target, actual_digest, self.downloads_root)
        return path, actual_size, actual_digest


def _matches_record(record: DownloadRecord) -> bool:
    try:
        return (
            record.path.is_file()
            and record.path.stat().st_size == record.size
            and sha256_file(record.path) == record.sha256
        )
    except OSError:
        return False


def _publish(source: Path, target: Path, digest: str, downloads_root: Path) -> Path:
    resolved_source = source.resolve()
    resolved_target = target.resolve()
    if resolved_source == resolved_target:
        if sha256_file(resolved_target) != digest:
            raise OSError("existing destination SHA-256 mismatch")
        return resolved_target
    if resolved_target.is_file() and sha256_file(resolved_target) == digest:
        _remove_if_managed_source(resolved_source, downloads_root, resolved_target)
        return resolved_target
    temp = resolved_target.with_name(f".{resolved_target.name}.tmp")
    temp.unlink(missing_ok=True)
    try:
        shutil.copy2(resolved_source, temp)
        if sha256_file(temp) != digest:
            raise OSError("copied artifact SHA-256 mismatch")
        os.replace(temp, resolved_target)
    finally:
        temp.unlink(missing_ok=True)
    _remove_if_managed_source(resolved_source, downloads_root, resolved_target)
    return resolved_target


def _remove_if_managed_source(source: Path, downloads_root: Path, target: Path) -> None:
    managed = {downloads_root.resolve() / "pending", downloads_root.resolve() / "verified"}
    if source.parent in managed and source != target:
        source.unlink(missing_ok=True)


def _artifact_from_state(values: dict[str, Any]) -> VerifiedArtifact:
    raw_size = values["size"]
    raw_version_code = values["version_code"]
    if isinstance(raw_size, bool) or not isinstance(raw_size, int):
        raise TypeError("verified artifact size must be an integer")
    if isinstance(raw_version_code, bool) or not isinstance(raw_version_code, int):
        raise TypeError("verified artifact version_code must be an integer")
    raw_signers = values["signer_certificate_sha256"]
    if not isinstance(raw_signers, list) or not all(
        isinstance(item, str) for item in raw_signers
    ):
        raise TypeError("verified artifact signers must be a string list")
    return VerifiedArtifact(
        version=str(values["version"]),
        source_url=str(values["source_url"]),
        path=Path(values["path"]),
        size=raw_size,
        file_sha256=str(values["file_sha256"]),
        package_name=str(values["package_name"]),
        version_name=str(values["version_name"]),
        version_code=raw_version_code,
        signer_certificate_sha256=tuple(raw_signers),
        verified_at=str(values["verified_at"]),
        verification_backend=str(values["verification_backend"]),
    )
