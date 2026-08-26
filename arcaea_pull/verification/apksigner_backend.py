"""Cryptographically verify APK signatures with Android's official apksigner."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import SignatureVerificationResult
from .base import (
    CommandRunner,
    MalformedToolOutputError,
    SignatureInvalidError,
    SubprocessRunner,
)

_CERT_RE = re.compile(
    r"^Signer (?:#\d+|\([^)]+\)) certificate SHA-256 digest:\s*"
    r"([0-9A-Fa-f: ]+)\s*$",
    re.MULTILINE,
)
_SCHEME_RE = re.compile(
    r"^Verified using (v\d+(?:\.\d+)?) scheme .*:\s*true\s*$",
    re.MULTILINE | re.IGNORECASE,
)


class ApkSignerBackend:
    def __init__(
        self,
        executable: str | Path,
        *,
        runner: CommandRunner | None = None,
        timeout: float = 60,
    ) -> None:
        self.executable = Path(executable)
        self.runner = runner or SubprocessRunner()
        self.timeout = max(float(timeout), 1)

    async def verify(self, path: Path) -> SignatureVerificationResult:
        result = await self.runner.run(
            (
                str(self.executable),
                "verify",
                "--verbose",
                "--print-certs",
                str(path),
            ),
            timeout=self.timeout,
        )
        if result.returncode != 0:
            detail = _safe_detail(result.stderr or result.stdout)
            raise SignatureInvalidError(
                f"apksigner rejected APK (exit {result.returncode}): {detail}"
            )
        signers = tuple(
            dict.fromkeys(normalize_fingerprint(item) for item in _CERT_RE.findall(result.stdout))
        )
        schemes = tuple(dict.fromkeys(item.lower() for item in _SCHEME_RE.findall(result.stdout)))
        if not signers or not schemes:
            raise MalformedToolOutputError(
                "apksigner success output lacked signer SHA-256 or a verified signature scheme"
            )
        if not any(int(scheme[1:].split(".", maxsplit=1)[0]) >= 2 for scheme in schemes):
            raise SignatureInvalidError(
                "APK lacks a verified v2-or-newer whole-file signature scheme"
            )
        return SignatureVerificationResult(
            signer_certificate_sha256=signers,
            verified_schemes=schemes,
            backend="android-apksigner",
        )


def normalize_fingerprint(value: str) -> str:
    compact = re.sub(r"[:\s]", "", str(value))
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", compact):
        raise ValueError("signer SHA-256 must contain exactly 64 hexadecimal digits")
    return compact.upper()


def _safe_detail(value: str) -> str:
    return " ".join(value.strip().split())[:500] or "no diagnostic output"
