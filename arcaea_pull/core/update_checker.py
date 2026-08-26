"""Serialized update-check pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from ..models import CheckResult, DownloadRecord, RemoteArtifact
from .api_client import ArcaeaApiClient
from .notifier import NotificationError, Notifier
from .state_manager import StateManager


class ArtifactDownloader(Protocol):
    async def download(self, artifact: RemoteArtifact) -> DownloadRecord: ...


class UpdateChecker:
    def __init__(
        self,
        api_client: ArcaeaApiClient,
        state: StateManager,
        *,
        notifier: Notifier | None = None,
        downloader: ArtifactDownloader | None = None,
        notify_on_update: bool = True,
        auto_download: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        pipeline_lock: asyncio.Lock | None = None,
    ) -> None:
        self.api_client = api_client
        self.state = state
        self.notifier = notifier
        self.downloader = downloader
        self.notify_on_update = notify_on_update
        self.auto_download = auto_download
        self.clock = clock
        self.pipeline_lock = pipeline_lock or asyncio.Lock()

    async def check(self) -> CheckResult:
        async with self.pipeline_lock:
            artifact = await self.api_client.fetch()
            before = self.state.load()
            previous = before["observed"].get("version")
            changed = previous != artifact.version
            observed_at = self.clock().astimezone(timezone.utc).isoformat()
            self.state.record_observed(artifact.version, artifact.url, observed_at)

            notified = False
            notification_error: str | None = None
            last_notified = before["notification"].get("last_notified_version")
            if changed and self.notify_on_update and last_notified != artifact.version:
                if self.notifier is not None:
                    try:
                        notified = await self.notifier.broadcast(
                            f"检测到 Arcaea C 版 APK 版本变化：{previous or '未记录'} → "
                            f"{artifact.version}"
                        )
                        if notified:
                            self.state.record_notification(artifact.version)
                    except NotificationError as exc:
                        notification_error = str(exc)

            downloaded = None
            # Re-enter the downloader for the current remote version on every check.
            # It validates and reuses a completed file, while a missing/failed prior
            # download is retried even when the remote version itself is unchanged.
            if self.auto_download and self.downloader is not None:
                downloaded = await self.downloader.download(artifact)

            return CheckResult(
                artifact=artifact,
                changed=changed,
                notified=notified,
                downloaded=downloaded,
                notification_error=notification_error,
            )
