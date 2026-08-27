"""Resolve a live aiocqhttp client from AstrBot's platform manager."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .base import BackendAmbiguousError, BackendUnavailableError
from .napcat_flash_transfer import NapCatFlashTransferBackend


@dataclass(frozen=True, slots=True)
class PlatformCandidate:
    platform_id: str
    self_id: str
    client: Any


class BackendProvider:
    """Resolve on every call so adapter reloads cannot leave a stale client."""

    def __init__(
        self,
        context: Any,
        allowed_targets: Iterable[str],
        *,
        platform_id: str = "",
        self_id: str = "",
    ) -> None:
        self._context = context
        self._allowed_targets = tuple(str(item) for item in allowed_targets if str(item))
        self._platform_id = str(platform_id).strip()
        self._self_id = str(self_id).strip()

    def resolve(self) -> NapCatFlashTransferBackend:
        candidates = self._candidates()
        if self._platform_id:
            candidates = [item for item in candidates if item.platform_id == self._platform_id]
        if self._self_id:
            candidates = [item for item in candidates if item.self_id == self._self_id]
        if not candidates:
            selectors = []
            if self._platform_id:
                selectors.append(f"platform_id={self._platform_id}")
            if self._self_id:
                selectors.append(f"self_id={self._self_id}")
            detail = f" ({', '.join(selectors)})" if selectors else ""
            raise BackendUnavailableError(f"no active aiocqhttp platform matched{detail}")
        if len(candidates) > 1:
            identities = ", ".join(
                f"{item.platform_id or '?'}:{item.self_id or '?'}" for item in candidates
            )
            raise BackendAmbiguousError(
                "multiple active aiocqhttp platforms matched; configure "
                f"flash_transfer_platform_id or flash_transfer_self_id: {identities}"
            )
        selected = candidates[0]
        call_action = getattr(selected.client, "call_action", None)
        if not callable(call_action):
            raise BackendUnavailableError(
                f"aiocqhttp platform {selected.platform_id or '?'} has no callable call_action"
            )
        return NapCatFlashTransferBackend(
            call_action,
            self._allowed_targets,
            self_id=selected.self_id or None,
        )

    def _candidates(self) -> list[PlatformCandidate]:
        manager = getattr(self._context, "platform_manager", None)
        if manager is None:
            raise BackendUnavailableError("AstrBot context has no platform_manager")
        get_insts = getattr(manager, "get_insts", None)
        instances = get_insts() if callable(get_insts) else getattr(manager, "platform_insts", None)
        if not isinstance(instances, (list, tuple)):
            raise BackendUnavailableError("AstrBot platform_manager exposed no platform instances")

        candidates: list[PlatformCandidate] = []
        for adapter in instances:
            metadata = _metadata(adapter)
            if str(getattr(metadata, "name", "")).lower() != "aiocqhttp":
                continue
            client = getattr(adapter, "bot", None)
            if client is None:
                continue
            for self_id in _connected_self_ids(client):
                candidates.append(
                    PlatformCandidate(
                        platform_id=str(getattr(metadata, "id", "") or ""),
                        self_id=self_id,
                        client=client,
                    )
                )
        return candidates


def _metadata(adapter: Any) -> Any:
    meta = getattr(adapter, "meta", None)
    if callable(meta):
        try:
            return meta()
        except Exception as exc:
            raise BackendUnavailableError(
                f"failed to inspect AstrBot platform metadata: {exc}"
            ) from exc
    return getattr(adapter, "metadata", None)


def _connected_self_ids(client: Any) -> tuple[str, ...]:
    """Read actual OneBot connection IDs, never AstrBot's internal client UUID."""
    connections = getattr(client, "_wsr_api_clients", None)
    if not isinstance(connections, dict):
        api = getattr(client, "api", None)
        websocket_api = getattr(api, "_wsr_api", None)
        connections = getattr(websocket_api, "_api_clients", None)
    if not isinstance(connections, dict):
        return ()
    return tuple(
        dict.fromkeys(
            str(self_id).strip()
            for self_id, connection in connections.items()
            if connection is not None and str(self_id).strip()
        )
    )
