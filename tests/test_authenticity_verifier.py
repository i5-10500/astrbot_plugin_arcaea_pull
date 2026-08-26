import asyncio

import pytest

from arcaea_pull.core.state_manager import StateManager
from arcaea_pull.models import (
    DownloadRecord,
    ManifestIdentity,
    SignatureVerificationResult,
    VerificationVerdict,
)
from arcaea_pull.utils.hashing import sha256_file
from arcaea_pull.verification.base import (
    MalformedToolOutputError,
    SignatureInvalidError,
    ToolTimeoutError,
)
from arcaea_pull.verification.verifier import AuthenticityVerifier

SIGNER = "AB" * 32
PACKAGE = "com.example.arcaea"


class SignatureBackend:
    def __init__(self, result=None, error=None):
        self.result = result or SignatureVerificationResult((SIGNER,), ("v2",), "fake-sig")
        self.error = error
        self.calls = 0

    async def verify(self, _path):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class ManifestInspector:
    def __init__(self, identity=None, error=None):
        self.identity = identity or ManifestIdentity(PACKAGE, "1c", 100, "fake-manifest")
        self.error = error
        self.calls = 0

    async def inspect(self, _path):
        self.calls += 1
        if self.error:
            raise self.error
        return self.identity


def downloaded(tmp_path, *, version="1c", legacy=False, content=b"synthetic signed apk fixture"):
    root = tmp_path / "downloads"
    folder = root if legacy else root / "pending"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"arcaea_{version}.apk"
    path.write_bytes(content)
    return DownloadRecord(
        version=version,
        source_url="https://example.test/a.apk",
        path=path.resolve(),
        size=path.stat().st_size,
        sha256=sha256_file(path),
        downloaded_at="downloaded",
    )


def verifier(tmp_path, *, sig=None, manifest=None, signers=(SIGNER,), package=PACKAGE):
    return AuthenticityVerifier(
        StateManager(tmp_path / "state.json"),
        tmp_path / "downloads",
        trusted_signers=signers,
        trusted_package_name=package,
        signature_backend=sig or SignatureBackend(),
        manifest_inspector=manifest or ManifestInspector(),
    )


@pytest.mark.asyncio
async def test_verified_artifact_is_published_and_is_the_only_reusable_boundary(tmp_path):
    record = downloaded(tmp_path)
    service = verifier(tmp_path)
    result = await service.verify(record, expected_version="1c")
    assert result.verdict == VerificationVerdict.VERIFIED
    assert result.artifact is not None
    assert result.artifact.path.parent.name == "verified"
    assert result.artifact.path.is_file()
    assert not record.path.exists()
    assert service.load_verified("1c") == result.artifact
    state = service.state.load()
    assert state["verification"]["last_verified_version_code"] == 100
    assert state["download"]["path"] == str(result.artifact.path)


@pytest.mark.asyncio
async def test_concurrent_verification_reuses_one_cryptographic_result(tmp_path):
    record = downloaded(tmp_path)
    sig = SignatureBackend()
    service = verifier(tmp_path, sig=sig)
    first, second = await asyncio.gather(
        service.verify(record, expected_version="1c"),
        service.verify(record, expected_version="1c"),
    )
    assert first.verdict == second.verdict == VerificationVerdict.VERIFIED
    assert sig.calls == 1


@pytest.mark.asyncio
async def test_legacy_apk_is_verified_without_deleting_original(tmp_path):
    record = downloaded(tmp_path, legacy=True)
    result = await verifier(tmp_path).verify(record, expected_version="1c")
    assert result.verdict == VerificationVerdict.VERIFIED
    assert record.path.is_file()
    assert result.artifact is not None and result.artifact.path != record.path


@pytest.mark.asyncio
async def test_empty_trust_or_package_holds_without_running_tools(tmp_path):
    record = downloaded(tmp_path)
    sig = SignatureBackend()
    service = verifier(tmp_path, sig=sig, signers=())
    result = await service.verify(record, expected_version="1c")
    assert result.verdict == VerificationVerdict.TRUST_NOT_CONFIGURED
    assert sig.calls == 0
    assert service.state.load()["verification"].get("last_verified_version") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sig", "manifest", "verdict"),
    [
        (
            SignatureBackend(error=SignatureInvalidError("invalid")),
            None,
            VerificationVerdict.SIGNATURE_INVALID,
        ),
        (
            SignatureBackend(error=MalformedToolOutputError("bad output")),
            None,
            VerificationVerdict.SIGNATURE_OUTPUT_INVALID,
        ),
        (
            SignatureBackend(error=ToolTimeoutError("timeout")),
            None,
            VerificationVerdict.VERIFIER_UNAVAILABLE,
        ),
        (
            None,
            ManifestInspector(error=MalformedToolOutputError("bad manifest")),
            VerificationVerdict.MANIFEST_INVALID,
        ),
    ],
)
async def test_backend_failures_are_fail_closed(tmp_path, sig, manifest, verdict):
    record = downloaded(tmp_path)
    result = await verifier(tmp_path, sig=sig, manifest=manifest).verify(
        record, expected_version="1c"
    )
    assert result.verdict == verdict
    assert result.artifact is None
    assert verifier_state(tmp_path).get("last_verified_version") is None


@pytest.mark.asyncio
async def test_unknown_or_additional_signer_is_rejected(tmp_path):
    record = downloaded(tmp_path)
    signature = SignatureVerificationResult((SIGNER, "CD" * 32), ("v3",), "fake")
    result = await verifier(tmp_path, sig=SignatureBackend(result=signature)).verify(
        record, expected_version="1c"
    )
    assert result.verdict == VerificationVerdict.UNTRUSTED_SIGNER


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity", "verdict"),
    [
        (
            ManifestIdentity("wrong.package", "1c", 100, "fake"),
            VerificationVerdict.PACKAGE_MISMATCH,
        ),
        (ManifestIdentity(PACKAGE, "1", 100, "fake"), VerificationVerdict.VERSION_MISMATCH),
    ],
)
async def test_package_and_version_name_must_match_exactly(tmp_path, identity, verdict):
    record = downloaded(tmp_path)
    result = await verifier(tmp_path, manifest=ManifestInspector(identity=identity)).verify(
        record, expected_version="1c"
    )
    assert result.verdict == verdict


@pytest.mark.asyncio
async def test_version_code_rollback_and_same_name_mismatch_are_blocked(tmp_path):
    first = downloaded(tmp_path, version="1c")
    service = verifier(tmp_path)
    assert (await service.verify(first, expected_version="1c")).artifact is not None

    older = downloaded(tmp_path, version="2c")
    service._manifest_inspector = ManifestInspector(ManifestIdentity(PACKAGE, "2c", 99, "fake"))
    rollback = await service.verify(older, expected_version="2c")
    assert rollback.verdict == VerificationVerdict.ROLLBACK_DETECTED
    assert service.state.load()["verification"]["last_verified_version"] == "1c"

    same = downloaded(tmp_path, version="1c", content=b"different same-version APK")
    service._manifest_inspector = ManifestInspector(ManifestIdentity(PACKAGE, "1c", 101, "fake"))
    mismatch = await service.verify(same, expected_version="1c")
    assert mismatch.verdict == VerificationVerdict.VERSION_CODE_MISMATCH


@pytest.mark.asyncio
async def test_equal_version_code_for_new_version_and_multiple_trusted_signers_pass(tmp_path):
    first = downloaded(tmp_path, version="1c")
    service = verifier(tmp_path)
    assert (await service.verify(first, expected_version="1c")).artifact is not None

    second = downloaded(tmp_path, version="2c", content=b"new version")
    other = "CD" * 32
    service._raw_trusted_signers = (SIGNER, other)
    service._signature_backend = SignatureBackend(
        SignatureVerificationResult((SIGNER, other), ("v3",), "fake")
    )
    service._manifest_inspector = ManifestInspector(ManifestIdentity(PACKAGE, "2c", 100, "fake"))
    result = await service.verify(second, expected_version="2c")
    assert result.verdict == VerificationVerdict.VERIFIED


@pytest.mark.asyncio
async def test_old_verified_artifact_cannot_bypass_later_rollback_state(tmp_path):
    first = downloaded(tmp_path, version="1c")
    service = verifier(tmp_path)
    assert (await service.verify(first, expected_version="1c")).artifact is not None

    second = downloaded(tmp_path, version="2c", content=b"newer trusted APK")
    service._manifest_inspector = ManifestInspector(
        ManifestIdentity(PACKAGE, "2c", 101, "fake")
    )
    assert (await service.verify(second, expected_version="2c")).artifact is not None
    assert service.load_verified("1c") is None


@pytest.mark.asyncio
async def test_verified_cache_checks_hash_and_tampering_is_blocked(tmp_path):
    sig = SignatureBackend()
    record = downloaded(tmp_path)
    service = verifier(tmp_path, sig=sig)
    first = await service.verify(record, expected_version="1c")
    assert first.artifact is not None and sig.calls == 1

    verified_record = DownloadRecord(
        version="1c",
        source_url=record.source_url,
        path=first.artifact.path,
        size=first.artifact.size,
        sha256=first.artifact.file_sha256,
        downloaded_at="downloaded",
    )
    reused = await service.verify(verified_record, expected_version="1c")
    assert reused.verdict == VerificationVerdict.VERIFIED and sig.calls == 1

    first.artifact.path.write_bytes(b"tampered")
    tampered = await service.verify(verified_record, expected_version="1c")
    assert tampered.verdict == VerificationVerdict.FILE_CHANGED
    assert service.load_verified("1c") is None


@pytest.mark.asyncio
async def test_quarantine_failure_still_blocks_and_does_not_advance_trust(tmp_path, monkeypatch):
    record = downloaded(tmp_path)
    service = verifier(tmp_path, sig=SignatureBackend(error=SignatureInvalidError("invalid")))

    def fail_quarantine(*_args):
        raise OSError("disk read-only")

    monkeypatch.setattr(service, "_publish_quarantine", fail_quarantine)
    result = await service.verify(record, expected_version="1c")
    assert result.verdict == VerificationVerdict.QUARANTINE_FAILED
    assert service.state.load()["verification"].get("last_verified_version") is None


@pytest.mark.asyncio
async def test_malformed_rollback_state_fails_closed(tmp_path):
    record = downloaded(tmp_path)
    service = verifier(tmp_path)
    state = service.state.load()
    state["verification"]["last_verified_version"] = "old"
    state["verification"]["last_verified_version_code"] = "not-an-int"
    service.state.save(state)
    result = await service.verify(record, expected_version="1c")
    assert result.verdict == VerificationVerdict.STATE_INVALID
    assert result.artifact is None


def test_verification_failure_notification_key_is_deduplicated(tmp_path):
    state = StateManager(tmp_path / "state.json")
    state.load()
    assert state.verification_failure_notification_needed("1:sha:BAD")
    state.record_verification_failure_notification("1:sha:BAD")
    assert not state.verification_failure_notification_needed("1:sha:BAD")
    assert state.verification_failure_notification_needed("1:other:BAD")


def verifier_state(tmp_path) -> dict:
    return StateManager(tmp_path / "state.json").load()["verification"]
