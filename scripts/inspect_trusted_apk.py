"""Inspect a user-supplied known-good APK with official Android SDK tools."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arcaea_pull.verification.apksigner_backend import ApkSignerBackend  # noqa: E402
from arcaea_pull.verification.manifest_inspector import ApkManifestInspector  # noqa: E402
from arcaea_pull.verification.tools import (  # noqa: E402
    resolve_apkanalyzer,
    resolve_apksigner,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description=(
            "Cryptographically verify and inspect an APK already known to the user. "
            "This command never edits plugin trust configuration."
        )
    )
    value.add_argument("apk", type=Path)
    value.add_argument("--apksigner", default="", help="explicit apksigner path")
    value.add_argument("--apkanalyzer", default="", help="explicit apkanalyzer path")
    value.add_argument("--timeout", type=float, default=60)
    return value


async def inspect(args: argparse.Namespace) -> None:
    apk = args.apk.resolve()
    if not apk.is_file():
        raise FileNotFoundError(f"APK does not exist: {apk}")
    signature = await ApkSignerBackend(
        resolve_apksigner(args.apksigner), timeout=args.timeout
    ).verify(apk)
    manifest = await ApkManifestInspector(
        resolve_apkanalyzer(args.apkanalyzer), timeout=args.timeout
    ).inspect(apk)
    print("Cryptographic signature: VALID")
    print(f"Package: {manifest.package_name}")
    print(f"Version name: {manifest.version_name}")
    print(f"Version code: {manifest.version_code}")
    for signer in signature.signer_certificate_sha256:
        print(f"Signer SHA-256: {signer}")


def main() -> int:
    args = parser().parse_args()
    try:
        asyncio.run(inspect(args))
    except Exception as exc:  # noqa: BLE001 - CLI must produce one safe failure
        print(f"Inspection failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
