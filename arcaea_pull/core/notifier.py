"""Whitelist-enforced update notification service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable


class NotificationError(RuntimeError):
    """One or more allowlisted notifications failed."""


class Notifier:
    def __init__(
        self,
        targets: Iterable[str],
        sender: Callable[[str, str], Awaitable[None]],
    ) -> None:
        self.targets = tuple(dict.fromkeys(str(target) for target in targets if str(target)))
        self._allowed = frozenset(self.targets)
        self._sender = sender

    def is_allowed(self, target: str) -> bool:
        return str(target) in self._allowed

    async def send(self, target: str, message: str) -> None:
        normalized = str(target)
        if not self.is_allowed(normalized):
            raise NotificationError(f"notification target is not allowlisted: {normalized}")
        await self._sender(normalized, message)

    async def broadcast(self, message: str) -> bool:
        if not self.targets:
            return False
        errors: list[str] = []
        for target in self.targets:
            try:
                await self.send(target, message)
            except Exception as exc:  # noqa: BLE001 - aggregate per-target delivery failures
                errors.append(f"{target}: {exc}")
        if errors:
            raise NotificationError("; ".join(errors))
        return True
