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
    assert runner.calls[0][0][1:4] == (
        "verify",
        "--verbose",
        "--print-certs",
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


@pytest.mark.asyncio
async def test_apksigner_rejects_v1_only_signature(tmp_path):
    backend = ApkSignerBackend(
        "apksigner",
        runner=Runner(
            [
                command(
                    "Verified using v1 scheme (JAR signing): true\n"
                    f"Signer #1 certificate SHA-256 digest: {'AA' * 32}\n"
                )
            ]
        ),
    )
    with pytest.raises(SignatureInvalidError, match="v2-or-newer"):
        await backend.verify(tmp_path / "a.apk")


def test_fingerprint_canonicalization_and_validation():
    assert normalize_fingerprint("aa:" * 31 + "aa") == "AA" * 32
    assert normalize_fingerprint(" aa aa " * 16) == "AA" * 32
    with pytest.raises(ValueError):
        normalize_fingerprint("not-a-fingerprint")


def badging(package="com.example.app", version_name="6.0.0c", version_code="12345"):
    return (
        f"package: name='{package}' versionCode='{version_code}' "
        f"versionName='{version_name}' compileSdkVersion='35'\n"
        "sdkVersion:'23'\n"
    )


def xmltree(
    package="com.example.app",
    version_name="6.0.0c",
    version_code="12345",
    version_code_major=None,
):
    major = (
        "    A: http://schemas.android.com/apk/res/android:"
        f"versionCodeMajor(0x01010576)={version_code_major}\n"
        if version_code_major is not None
        else ""
    )
    return (
        "N: android=http://schemas.android.com/apk/res/android (line=2)\n"
        "  E: manifest (line=2)\n"
        "    A: http://schemas.android.com/apk/res/android:"
        f"versionCode(0x0101021b)={version_code}\n"
        "    A: http://schemas.android.com/apk/res/android:"
        f'versionName(0x0101021c)="{version_name}" (Raw: "{version_name}")\n'
        f"{major}"
        f'    A: package="{package}" (Raw: "{package}")\n'
        "    E: uses-sdk (line=7)\n"
    )


@pytest.mark.asyncio
async def test_aapt2_reads_and_cross_checks_exact_manifest_fields(tmp_path):
    runner = Runner([command(stdout=badging()), command(stdout=xmltree())])
    identity = await ApkManifestInspector("aapt2", runner=runner).inspect(tmp_path / "a.apk")
    assert identity.package_name == "com.example.app"
    assert identity.version_name == "6.0.0c"
    assert identity.version_code == 12345
    assert identity.backend == "android-aapt2"
    assert runner.calls[0][0][1:3] == ("dump", "badging")
    assert runner.calls[1][0][1:3] == ("dump", "xmltree")
    assert runner.calls[1][0][-2:] == ("--file", "AndroidManifest.xml")


@pytest.mark.asyncio
async def test_aapt2_combines_version_code_major_for_rollback_protection(tmp_path):
    runner = Runner(
        [
            command(stdout=badging(version_code="7")),
            command(stdout=xmltree(version_code="7", version_code_major="2")),
        ]
    )
    identity = await ApkManifestInspector("aapt2", runner=runner).inspect(tmp_path / "a.apk")
    assert identity.version_code == (2 << 32) | 7


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results",
    [
        [command(stderr="bad manifest", returncode=1)],
        [command(stdout="package: broken\n"), command(stdout=xmltree())],
        [command(stdout=badging()), command(stdout=xmltree(package="com.other"))],
        [command(stdout=badging()), command(stdout=xmltree() + xmltree())],
        [command(stdout=badging()), command(stdout=xmltree(version_code="4294967296"))],
    ],
)
async def test_aapt2_malformed_failed_or_inconsistent_output_is_rejected(tmp_path, results):
    inspector = ApkManifestInspector("aapt2", runner=Runner(results))
    with pytest.raises(MalformedToolOutputError):
        await inspector.inspect(tmp_path / "a.apk")
