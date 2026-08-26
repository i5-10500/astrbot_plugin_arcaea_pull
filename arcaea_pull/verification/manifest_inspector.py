"""Read binary Android manifest identity through the official AAPT2 tool."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import ManifestIdentity
from .base import CommandRunner, MalformedToolOutputError, SubprocessRunner

_BADGING_PACKAGE = re.compile(
    r"^package: name='([^'\r\n]+)' versionCode='([0-9]+)' "
    r"versionName='([^'\r\n]+)'(?: [A-Za-z][A-Za-z0-9-]*='[^'\r\n]*')*$"
)
_MANIFEST = re.compile(r"^  E: manifest \(line=[0-9]+\)$")
_ROOT_PACKAGE = re.compile(r'^    A: package="([^"\r\n]+)"(?: \(Raw: "[^"\r\n]*"\))?$')
_ROOT_VERSION_CODE = re.compile(
    r"^    A: http://schemas\.android\.com/apk/res/android:"
    r"versionCode\(0x0101021b\)=([0-9]+|0x[0-9A-Fa-f]+)$"
)
_ROOT_VERSION_NAME = re.compile(
    r'^    A: http://schemas\.android\.com/apk/res/android:'
    r'versionName\(0x0101021c\)="([^"\r\n]+)"(?: \(Raw: "[^"\r\n]*"\))?$'
)
_ROOT_VERSION_CODE_MAJOR = re.compile(
    r"^    A: http://schemas\.android\.com/apk/res/android:"
    r"versionCodeMajor\(0x01010576\)=([0-9]+|0x[0-9A-Fa-f]+)$"
)
_UINT32_MAX = (1 << 32) - 1


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
        badging = await self._run("badging", path)
        xmltree = await self._run("xmltree", path, "--file", "AndroidManifest.xml")
        badging_identity = _parse_badging(badging)
        package_name, version_name, base_code, major_code = _parse_xmltree(xmltree)
        if badging_identity != (package_name, version_name, base_code):
            raise MalformedToolOutputError(
                "aapt2 badging and xmltree manifest identities do not match"
            )
        if not package_name or any(char.isspace() for char in package_name):
            raise MalformedToolOutputError("aapt2 returned an invalid package name")
        return ManifestIdentity(
            package_name=package_name,
            version_name=version_name,
            version_code=(major_code << 32) | base_code,
            backend="android-aapt2",
        )

    async def _run(self, verb: str, path: Path, *arguments: str) -> str:
        result = await self.runner.run(
            (str(self.executable), "dump", verb, str(path), *arguments),
            timeout=self.timeout,
        )
        if result.returncode != 0:
            detail = " ".join((result.stderr or result.stdout).strip().split())[:500]
            raise MalformedToolOutputError(
                f"aapt2 dump {verb} failed (exit {result.returncode}): "
                f"{detail or 'no diagnostic output'}"
            )
        return result.stdout


def _parse_badging(output: str) -> tuple[str, str, int]:
    lines = [line for line in output.splitlines() if line.startswith("package:")]
    if len(lines) != 1:
        raise MalformedToolOutputError(
            f"aapt2 dump badging returned {len(lines)} package records"
        )
    match = _BADGING_PACKAGE.fullmatch(lines[0])
    if match is None:
        raise MalformedToolOutputError("aapt2 dump badging returned a malformed package record")
    package_name, raw_code, version_name = match.groups()
    base_code = _uint32(raw_code, "versionCode")
    if not version_name:
        raise MalformedToolOutputError("aapt2 returned an empty versionName")
    return package_name, version_name, base_code


def _parse_xmltree(output: str) -> tuple[str, str, int, int]:
    lines = output.splitlines()
    if sum(_MANIFEST.fullmatch(line) is not None for line in lines) != 1:
        raise MalformedToolOutputError("aapt2 xmltree did not contain one manifest root")
    package_name = _single_match(lines, _ROOT_PACKAGE, "package")
    version_name = _single_match(lines, _ROOT_VERSION_NAME, "versionName")
    base_code = _uint32(_single_match(lines, _ROOT_VERSION_CODE, "versionCode"), "versionCode")
    major_matches = _matches(lines, _ROOT_VERSION_CODE_MAJOR)
    if len(major_matches) > 1:
        raise MalformedToolOutputError("aapt2 xmltree returned duplicate versionCodeMajor")
    major_code = _uint32(major_matches[0], "versionCodeMajor") if major_matches else 0
    return package_name, version_name, base_code, major_code


def _single_match(lines: list[str], pattern: re.Pattern[str], field: str) -> str:
    matches = _matches(lines, pattern)
    if len(matches) != 1:
        raise MalformedToolOutputError(
            f"aapt2 xmltree returned {len(matches)} root {field} values"
        )
    return matches[0]


def _matches(lines: list[str], pattern: re.Pattern[str]) -> list[str]:
    return [match.group(1) for line in lines if (match := pattern.fullmatch(line))]


def _uint32(raw_value: str, field: str) -> int:
    try:
        value = int(raw_value, 0)
    except ValueError as exc:
        raise MalformedToolOutputError(f"aapt2 returned an invalid {field}") from exc
    if not 0 <= value <= _UINT32_MAX:
        raise MalformedToolOutputError(f"aapt2 returned an out-of-range {field}")
    return value
