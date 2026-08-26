"""Platform-neutral Flash Transfer contract and typed failures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class FlashTransferError(RuntimeError):
    """Base error for QQ Flash Transfer operations."""


class BackendUnavailableError(FlashTransferError):
    """The active platform does not expose the required extension actions."""


class BackendAmbiguousError(BackendUnavailableError):
    """More than one active platform matched without a unique selector."""


class BackendActionError(FlashTransferError):
    """The backend action was available but rejected or failed the request."""


class TargetNotAllowedError(FlashTransferError):
    """The destination is absent from the dedicated Flash Transfer allowlist."""


@dataclass(frozen=True, slots=True)
class FlashTransferResult:
    target: str
    file_set_id: str
    backend: str


class FlashTransferBackend(ABC):
    @property
    @abstractmethod
    def status(self) -> str: ...

    @abstractmethod
    async def send_file(
        self, target: str, path: Path, *, name: str = ""
    ) -> FlashTransferResult: ...
