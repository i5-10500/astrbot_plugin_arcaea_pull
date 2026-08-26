from collections import deque

import pytest

from arcaea_pull.verification.apksigner_backend import (
    ApkSignerBackend,
    normalize_fingerprint,
)
from arcaea_pull.verification.base import (
    CommandResult,
    MalformedToolOutputError,
    SignatureInvalidError,
)
from arcaea_pull.verification.manifest_inspector import ApkManifestInspector


class Runner:
    def __init__(self, results):
        self.results = deque(results)
        self.calls = []

    async def run(self, argv, *, timeout):
        self.calls.append((tuple(argv), timeout))
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        return result


def command(stdout="", stderr="", returncode=0):
    return CommandResult(returncode, stdout, stderr)


@pytest.mark.asyncio
async def test_apksigner_cryptographic_success_parses_all_signers_and_scheme(tmp_path):
    fingerprint_a = "AA" * 32
    fingerprint_b = "bb:" * 31 + "bb"
    runner = Runner(
        [
            command(
                "Verified using v1 scheme (JAR signing): false\n"
                "Verified using v2 scheme (APK Signature Scheme v2): true\n"
                "Verified using v3.1 scheme (APK Signature Scheme v3.1): true\n"
                f"Signer #1 certificate SHA-256 digest: {fingerprint_a}\n"
                "Signer (minSdkVersion=33, maxSdkVersion=34) certificate "
                f"SHA-256 digest: {fingerprint_b}\n"
            )
        ]
    )
    result = await ApkSignerBackend("apksigner", runner=runner).verify(tmp_path / "a.apk")
    assert result.verified_schemes == ("v2", "v3.1")
    assert result.signer_certificate_sha256 == ("AA" * 32, "BB" * 32)
    assert runner.calls[0][0][1:5] == (
        "verify",
        "--verbose",
        "--print-certs",
        "-Werr",
    )


@pytest.mark.asyncio
async def test_apksigner_nonzero_exit_is_invalid_signature(tmp_path):
    backend = ApkSignerBackend(
        "apksigner", runner=Runner([command(stderr="DOES NOT VERIFY", returncode=1)])
    )
    with pytest.raises(SignatureInvalidError, match="rejected"):
        await backend.verify(tmp_path / "a.apk")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stdout",
    [
        "Verified using v2 scheme (APK Signature Scheme v2): true\n",
        f"Signer #1 certificate SHA-256 digest: {'AA' * 32}\n",
        "unrecognized success output\n",
    ],
)
async def test_apksigner_malformed_success_output_fails_closed(tmp_path, stdout):
    backend = ApkSignerBackend("apksigner", runner=Runner([command(stdout=stdout)]))
    with pytest.raises(MalformedToolOutputError):
        await backend.verify(tmp_path / "a.apk")


def test_fingerprint_canonicalization_and_validation():
    assert normalize_fingerprint("aa:" * 31 + "aa") == "AA" * 32
    assert normalize_fingerprint(" aa aa " * 16) == "AA" * 32
    with pytest.raises(ValueError):
        normalize_fingerprint("not-a-fingerprint")


@pytest.mark.asyncio
async def test_apkanalyzer_reads_exact_manifest_fields(tmp_path):
    runner = Runner(
        [
            command(stdout="com.example.app\n"),
            command(stdout="6.0.0c\n"),
            command(stdout="12345\n"),
        ]
    )
    identity = await ApkManifestInspector("apkanalyzer", runner=runner).inspect(tmp_path / "a.apk")
    assert identity.package_name == "com.example.app"
    assert identity.version_name == "6.0.0c"
    assert identity.version_code == 12345
    assert [call[0][2] for call in runner.calls] == [
        "application-id",
        "version-name",
        "version-code",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results",
    [
        [command(stdout="two\nvalues\n")],
        [command(stderr="bad manifest", returncode=1)],
        [command(stdout="com.example\n"), command(stdout="1\n"), command(stdout="NaN\n")],
    ],
)
async def test_apkanalyzer_malformed_or_failed_output_is_rejected(tmp_path, results):
    inspector = ApkManifestInspector("apkanalyzer", runner=Runner(results))
    with pytest.raises(MalformedToolOutputError):
        await inspector.inspect(tmp_path / "a.apk")
