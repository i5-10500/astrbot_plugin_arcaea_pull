"""Read binary Android manifest identity through official apkanalyzer commands."""

from __future__ import annotations

from pathlib import Path

from ..models import ManifestIdentity
from .base import CommandRunner, MalformedToolOutputError, SubprocessRunner


class ApkManifestInspector:
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

    async def inspect(self, path: Path) -> ManifestIdentity:
        package_name = await self._field("application-id", path)
        version_name = await self._field("version-name", path)
        raw_version_code = await self._field("version-code", path)
        if not package_name or any(char.isspace() for char in package_name):
            raise MalformedToolOutputError("apkanalyzer returned an invalid application ID")
        if not version_name:
            raise MalformedToolOutputError("apkanalyzer returned an empty version name")
        try:
            version_code = int(raw_version_code)
        except ValueError as exc:
            raise MalformedToolOutputError(
                f"apkanalyzer returned a non-integer version code: {raw_version_code!r}"
            ) from exc
        if version_code < 0:
            raise MalformedToolOutputError("apkanalyzer returned a negative version code")
        return ManifestIdentity(
            package_name=package_name,
            version_name=version_name,
            version_code=version_code,
            backend="android-apkanalyzer",
        )

    async def _field(self, verb: str, path: Path) -> str:
        result = await self.runner.run(
            (str(self.executable), "manifest", verb, str(path)),
            timeout=self.timeout,
        )
        if result.returncode != 0:
            detail = " ".join((result.stderr or result.stdout).strip().split())[:500]
            raise MalformedToolOutputError(
                f"apkanalyzer manifest {verb} failed (exit {result.returncode}): "
                f"{detail or 'no diagnostic output'}"
            )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(lines) != 1:
            raise MalformedToolOutputError(
                f"apkanalyzer manifest {verb} returned {len(lines)} values"
            )
        return lines[0]
