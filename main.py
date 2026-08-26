"""AstrBot adapter for the Arcaea Pull core services."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools, register

from .arcaea_pull import __version__
from .arcaea_pull.core.api_client import ArcaeaApiClient
from .arcaea_pull.core.downloader import Downloader
from .arcaea_pull.core.notifier import NotificationError, Notifier
from .arcaea_pull.core.scheduler import ScheduleConfigError, seconds_until_next
from .arcaea_pull.core.state_manager import StateManager
from .arcaea_pull.core.update_checker import UpdateChecker
from .arcaea_pull.distribution import NapCatFlashTransferBackend

PLUGIN_NAME = "astrbot_plugin_arcaea_pull"


@register(
    PLUGIN_NAME,
    "i5-10500",
    "Arcaea 中国大陆版 APK 更新检测、可靠下载与 QQ 闪传 PoC",
    __version__,
    "https://github.com/i5-10500/astrbot_plugin_arcaea_pull",
)
class ArcaeaPullPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        self.state = StateManager(self.data_dir / "state.json")
        self.pipeline_lock = asyncio.Lock()
        request_timeout = float(config.get("request_timeout", 30))
        retries = int(config.get("retry_count", 3))
        self.api_client = ArcaeaApiClient(timeout=request_timeout, retry_count=retries)
        self.downloader = Downloader(
            self.data_dir / "downloads",
            self.state,
            connect_timeout=float(config.get("download_connect_timeout", 30)),
            read_timeout=float(config.get("download_read_timeout", 120)),
            retry_count=retries,
            keep_old_versions=bool(config.get("keep_old_versions", True)),
        )
        self.notifier = Notifier(
            _string_list(config.get("notify_targets", [])), self._send_notification
        )
        self.checker = UpdateChecker(
            self.api_client,
            self.state,
            notifier=self.notifier,
            downloader=self.downloader,
            notify_on_update=bool(config.get("notify_on_update", True)),
            auto_download=bool(config.get("auto_download", False)),
            pipeline_lock=self.pipeline_lock,
        )
        self._scheduler_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        """Start exactly one timezone-aware scheduler task."""
        self.state.load()
        if bool(self.config.get("check_enabled", True)):
            try:
                self._seconds_until_next_check()
            except ScheduleConfigError as exc:
                logger.error(f"Arcaea Pull scheduler disabled: {exc}")
                return
            self._scheduler_task = asyncio.create_task(
                self._scheduler_loop(), name="arcaea-pull-scheduled-check"
            )

    async def terminate(self) -> None:
        """Cancel background work and close owned HTTP sessions."""
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scheduler_task
            self._scheduler_task = None
        await self.api_client.close()
        await self.downloader.close()

    async def _send_notification(self, target: str, message: str) -> None:
        chain = MessageChain().message(message)
        sent = await self.context.send_message(target, chain)
        if sent is False:
            raise NotificationError(f"AstrBot could not resolve notification UMO: {target}")

    async def _scheduler_loop(self) -> None:
        while True:
            delay = self._seconds_until_next_check()
            await asyncio.sleep(delay)
            try:
                await self._check_with_download_notice()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - scheduler must survive one failed day
                logger.exception(f"Scheduled Arcaea update check failed: {exc}")
                if bool(self.config.get("notify_on_error", False)):
                    with suppress(NotificationError):
                        await self.notifier.broadcast(f"Arcaea 更新检查失败：{exc}")

    def _seconds_until_next_check(self) -> float:
        return seconds_until_next(
            datetime.now(timezone.utc),
            str(self.config.get("timezone", "Asia/Shanghai")),
            interval_minutes=self.config.get("check_interval_minutes", 30),
            extra_check_times=_string_list(self.config.get("extra_check_times", [])),
        )

    async def _check_with_download_notice(self):
        result = await self.checker.check()
        if (
            result.downloaded is not None
            and bool(self.config.get("notify_on_download_success", True))
        ):
            with suppress(NotificationError):
                await self.notifier.broadcast(
                    f"Arcaea {result.downloaded.version} APK 下载成功，"
                    f"大小 {result.downloaded.size} 字节，SHA-256 "
                    f"{result.downloaded.sha256}"
                )
        return result

    @filter.command_group("apull")
    def apull(self):
        """Arcaea Pull 管理命令。"""

    @filter.permission_type(filter.PermissionType.ADMIN)
    @apull.command("status")
    async def status(self, event: AstrMessageEvent):
        """显示安全的插件运行状态。"""
        state = self.state.load()
        observed = state["observed"].get("version") or "未记录"
        downloaded = state["download"].get("last_downloaded_version") or "未记录"
        yield event.plain_result(
            "\n".join(
                [
                    f"Arcaea Pull: v{__version__}",
                    f"last_seen_version: {observed}",
                    f"last_downloaded_version: {downloaded}",
                    f"check_enabled: {bool(self.config.get('check_enabled', True))}",
                    f"schedule: {_schedule_summary(self.config)}",
                    f"auto_download: {bool(self.config.get('auto_download', False))}",
                    "FlashTransfer: READY_UNVERIFIED "
                    "(NapCat >= v4.10.47; 需执行白名单小文件实测)",
                ]
            )
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @apull.command("check")
    async def check(self, event: AstrMessageEvent):
        """立即检查一次远端版本。"""
        try:
            result = await self._check_with_download_notice()
            summary = "检测到版本变化" if result.changed else "版本未变化"
            details = [f"{summary}: {result.artifact.version}"]
            if result.downloaded:
                details.append(f"APK: {result.downloaded.path}")
            if result.notification_error:
                details.append(f"通知失败: {result.notification_error}")
            yield event.plain_result("\n".join(details))
        except Exception as exc:  # noqa: BLE001 - return diagnostic to admin
            logger.exception(f"Manual Arcaea update check failed: {exc}")
            yield event.plain_result(f"检查失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @apull.command("download")
    async def download(self, event: AstrMessageEvent):
        """下载当前 API 返回的 APK；已可靠存在时不会重复下载。"""
        try:
            async with self.pipeline_lock:
                artifact = await self.api_client.fetch()
                record = await self.downloader.download(artifact)
            if bool(self.config.get("notify_on_download_success", True)) and not record.reused:
                with suppress(NotificationError):
                    await self.notifier.broadcast(
                        f"Arcaea {record.version} APK 下载成功，大小 {record.size} 字节，"
                        f"SHA-256 {record.sha256}"
                    )
            reused = "（已存在，未重复下载）" if record.reused else ""
            yield event.plain_result(
                f"APK 就绪{reused}: {record.path}\n"
                f"size={record.size}\nsha256={record.sha256}"
            )
        except Exception as exc:  # noqa: BLE001 - return diagnostic to admin
            logger.exception(f"Manual Arcaea APK download failed: {exc}")
            yield event.plain_result(f"下载失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @apull.command("flash_test")
    async def flash_test(self, event: AstrMessageEvent):
        """向当前白名单群发送一个无敏感信息的小型 QQ 闪传探针。"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("闪传诊断只能在 aiocqhttp 群聊中执行。")
            return
        bot = getattr(event, "bot", None)
        call_action = getattr(bot, "call_action", None)
        if not callable(call_action):
            yield event.plain_result(
                "当前事件未提供 aiocqhttp call_action，FlashTransfer backend 不可用。"
            )
            return
        backend = NapCatFlashTransferBackend(
            call_action,
            _string_list(self.config.get("flash_transfer_targets", [])),
            self_id=str(event.get_self_id() or "") or None,
        )
        probe_path = Path(self.data_dir) / "flash-transfer-probe.txt"
        probe_path.write_text(
            "astrbot_plugin_arcaea_pull Flash Transfer PoC\n"
            "This file contains no APK or credentials.\n",
            encoding="utf-8",
        )
        try:
            result = await backend.send_file(
                group_id, probe_path, name="Arcaea Pull FlashTransfer PoC"
            )
            yield event.plain_result(
                f"QQ 闪传 PoC 成功：group={result.target}, "
                f"fileset_id={result.file_set_id}。这不代表 APK 自动分发已启用。"
            )
        except Exception as exc:  # noqa: BLE001 - typed backend detail goes to admin
            logger.exception(f"Flash Transfer PoC failed: {exc}")
            yield event.plain_result(f"QQ 闪传 PoC 失败：{exc}")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if str(item)]


def _schedule_summary(config: AstrBotConfig) -> str:
    extras = _string_list(config.get("extra_check_times", []))
    interval = config.get("check_interval_minutes", 30)
    if (
        isinstance(interval, bool)
        or not isinstance(interval, int)
        or not 1 <= interval <= 1440
    ):
        return "INVALID"
    primary = f"every {interval}m from local 00:00"
    return f"{primary}; extras={extras or 'none'}"
