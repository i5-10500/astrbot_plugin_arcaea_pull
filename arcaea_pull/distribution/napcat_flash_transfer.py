"""NapCat OneBot extension adapter for QQ Flash Transfer."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import Any

from .base import (
    BackendActionError,
    BackendUnavailableError,
    FlashTransferBackend,
    FlashTransferResult,
    TargetNotAllowedError,
)

MINIMUM_NAPCAT_VERSION = "v4.10.47"
CREATE_ACTION = "create_flash_task"
SEND_ACTION = "send_flash_msg"

ActionCaller = Callable[..., Awaitable[dict[str, Any]]]


class NapCatFlashTransferBackend(FlashTransferBackend):
    def __init__(
        self,
        action_caller: ActionCaller,
        allowed_targets: Iterable[str],
        *,
        self_id: str | None = None,
    ) -> None:
        self._call_action = action_caller
        self._allowed_targets = frozenset(
            str(target) for target in allowed_targets if str(target)
        )
        self._self_id = str(self_id) if self_id else None

    @property
    def status(self) -> str:
        return (
            f"READY_UNVERIFIED (NapCat >= {MINIMUM_NAPCAT_VERSION}; "
            "run /apull flash_test in an allowlisted group)"
        )

    def is_allowed(self, target: str) -> bool:
        return str(target) in self._allowed_targets

    async def send_file(
        self, target: str, path: Path, *, name: str = ""
    ) -> FlashTransferResult:
        normalized_target = str(target)
        if not self.is_allowed(normalized_target):
            raise TargetNotAllowedError(
                f"QQ group is not in flash_transfer_targets: {normalized_target}"
            )
        resolved_path, is_file = await asyncio.to_thread(_resolve_file, path)
        if not is_file:
            raise BackendActionError(f"Flash Transfer source file does not exist: {path}")

        created = await self._invoke(
            CREATE_ACTION,
            files=str(resolved_path),
            name=name or resolved_path.name,
        )
        create_result = created.get("result")
        if create_result not in (None, 0):
            raise BackendActionError(
                f"{CREATE_ACTION} failed: result={create_result!r} "
                f"message={_error_message(created)!r}"
            )
        nested = created.get("createFlashTransferResult")
        if not isinstance(nested, dict):
            nested = {}
        file_set_id = nested.get("fileSetId") or created.get("fileSetId")
        if not isinstance(file_set_id, str) or not file_set_id:
            raise BackendActionError(
                f"{CREATE_ACTION} returned no createFlashTransferResult.fileSetId"
            )

        sent = await self._invoke(
            SEND_ACTION,
            fileset_id=file_set_id,
            group_id=normalized_target,
        )
        if sent.get("errCode") != 0:
            raise BackendActionError(
                f"{SEND_ACTION} failed: errCode={sent.get('errCode')!r} "
                f"message={_error_message(sent)!r}"
            )
        return FlashTransferResult(
            target=normalized_target,
            file_set_id=file_set_id,
            backend="napcat-onebot-extension",
        )

    async def _invoke(self, action: str, **payload: Any) -> dict[str, Any]:
        if self._self_id:
            payload["self_id"] = self._self_id
        try:
            result = await self._call_action(action, **payload)
        except Exception as exc:
            if _looks_unsupported(exc):
                raise BackendUnavailableError(
                    f"NapCat action {action!r} is unavailable; require NapCat "
                    f">= {MINIMUM_NAPCAT_VERSION}: {exc}"
                ) from exc
            raise BackendActionError(f"NapCat action {action!r} raised: {exc}") from exc
        if not isinstance(result, dict):
            raise BackendActionError(
                f"NapCat action {action!r} returned {type(result).__name__}, expected object"
            )
        return result


def _error_message(result: dict[str, Any]) -> str:
    return str(result.get("errMsg") or result.get("message") or result.get("wording") or "")


def _looks_unsupported(exc: Exception) -> bool:
    message = str(exc).lower()
    markers = ("not found", "unsupported", "unknown action", "404", "不支持", "未找到")
    return any(marker in message for marker in markers)


def _resolve_file(path: Path) -> tuple[Path, bool]:
    resolved = path.resolve()
    return resolved, resolved.is_file()
