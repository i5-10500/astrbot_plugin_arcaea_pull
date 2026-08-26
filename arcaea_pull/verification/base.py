"""Shared subprocess boundary for official Android verification tools."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class VerificationBackendError(RuntimeError):
    """An Android verification tool could not produce a trusted result."""


class ToolUnavailableError(VerificationBackendError):
    """A required official Android tool is not installed or configured."""


class ToolTimeoutError(VerificationBackendError):
    """A verification tool exceeded its bounded execution time."""


class SignatureInvalidError(VerificationBackendError):
    """apksigner cryptographically rejected the APK."""


class MalformedToolOutputError(VerificationBackendError):
    """Tool output was incomplete or could not be parsed safely."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    async def run(self, argv: Sequence[str], *, timeout: float) -> CommandResult: ...


class SubprocessRunner:
    async def run(self, argv: Sequence[str], *, timeout: float) -> CommandResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as exc:
            raise ToolUnavailableError(f"could not start {argv[0]!r}: {exc}") from exc
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ToolTimeoutError(f"tool timed out after {timeout:g}s: {argv[0]}") from exc
        return CommandResult(
            returncode=int(process.returncode or 0),
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
