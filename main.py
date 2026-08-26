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
from .arcaea_pull.distribution import BackendProvider, DistributionService
from .arcaea_pull.models import VerificationVerdict
from .arcaea_pull.verification import AuthenticityVerifier

PLUGIN_NAME = "astrbot_plugin_arcaea_pull"


@register(
    PLUGIN_NAME,
    "i5-10500",
    "Arcaea 中国大陆版 APK 可信下载、真实性验证与 QQ 闪传分发",
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
        downloads_root = self.data_dir / "downloads"
        self.downloader = Downloader(
            downloads_root / "pending",
            self.state,
            connect_timeout=float(config.get("download_connect_timeout", 30)),
            read_timeout=float(config.get("download_read_timeout", 120)),
            retry_count=retries,
            keep_old_versions=bool(config.get("keep_old_versions", True)),
        )
        self.notifier = Notifier(
            _string_list(config.get("notify_targets", [])), self._send_notification
        )
        flash_targets = _string_list(config.get("flash_transfer_targets", []))
        self.backend_provider = BackendProvider(
            context,
            flash_targets,
            platform_id=str(config.get("flash_transfer_platform_id", "")),
            self_id=str(config.get("flash_transfer_self_id", "")),
        )
        self.distributor = DistributionService(
            self.state, self.backend_provider.resolve, flash_targets
        )
        self.verifier = AuthenticityVerifier(
            self.state,
            downloads_root,
            trusted_signers=_string_list(config.get("trusted_signer_sha256", [])),
            trusted_package_name=str(config.get("trusted_package_name", "")),
            apksigner_path=str(config.get("apksigner_path", "")),
            apkanalyzer_path=str(config.get("apkanalyzer_path", "")),
            timeout=float(config.get("verification_timeout", 60)),
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
        async with self.pipeline_lock:
            return await self._check_with_download_notice_locked()

    async def _check_with_download_notice_locked(self):
        result = await self.checker.check_unlocked()
        if (
            result.downloaded is not None
            and not result.downloaded.reused
            and bool(self.config.get("notify_on_download_success", True))
        ):
            with suppress(NotificationError):
                await self.notifier.broadcast(
                    f"Arcaea {result.downloaded.version} APK 下载成功，"
                    f"大小 {result.downloaded.size} 字节，SHA-256 "
                    f"{result.downloaded.sha256}"
                )
        verification = None
        if result.downloaded is not None and bool(self.config.get("verification_enabled", True)):
            verification = await self.verifier.verify(
                result.downloaded, expected_version=result.artifact.version
            )
            await self._notify_verification_failure(verification, result.artifact.version)

        distribution = None
        if bool(self.config.get("auto_flash_transfer", False)):
            if not bool(self.config.get("auto_download", False)):
                logger.error("AUTO_FLASH_MISCONFIGURED: auto_flash_transfer requires auto_download")
            elif not bool(self.config.get("verification_enabled", True)):
                logger.error(
                    "CONFIG_SECURITY_ERROR: automatic Flash Transfer requires verification"
                )
            elif verification is not None and verification.artifact is not None:
                distribution = await self.distributor.distribute(verification.artifact)
                await self._notify_distribution(distribution)
        return result, verification, distribution

    async def _notify_verification_failure(self, result, version: str) -> None:
        if result is None or result.verdict == VerificationVerdict.VERIFIED:
            return
        if not bool(self.config.get("notify_on_verification_failure", True)):
            return
        if not self.state.verification_failure_notification_needed(result.event_key):
            return
        try:
            notified = await self.notifier.broadcast(
                f"Arcaea C版 {version} 安装包真实性验证失败，已停止自动分发。"
                f"原因：{result.verdict.value}"
            )
        except NotificationError:
            return
        if notified:
            self.state.record_verification_failure_notification(result.event_key)

    async def _notify_distribution(self, result) -> None:
        if result.succeeded and bool(self.config.get("notify_on_distribution_success", True)):
            with suppress(NotificationError):
                await self.notifier.broadcast(
                    f"Arcaea {result.version} APK 闪传完成："
                    f"成功 {result.succeeded}，失败 {result.failed}，"
                    f"已跳过 {result.skipped}。"
                )
        elif result.failed and bool(self.config.get("notify_on_distribution_failure", True)):
            with suppress(NotificationError):
                await self.notifier.broadcast(
                    f"Arcaea {result.version} APK 闪传失败："
                    f"失败 {result.failed}，已跳过 {result.skipped}。"
                )

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
        auto_download = bool(self.config.get("auto_download", False))
        auto_flash = bool(self.config.get("auto_flash_transfer", False))
        if auto_flash and not auto_download:
            flash_status = "AUTO_FLASH_MISCONFIGURED (需要同时启用 auto_download)"
        elif auto_flash and not bool(self.config.get("verification_enabled", True)):
            flash_status = "CONFIG_SECURITY_ERROR (真实性验证被禁用)"
        else:
            try:
                flash_status = self.backend_provider.resolve().status
            except Exception as exc:  # noqa: BLE001 - status is diagnostic
                flash_status = f"UNAVAILABLE ({exc})"
        distribution = _distribution_summary(state, observed)
        verification_status = await asyncio.to_thread(
            _verification_status, self.config, self.verifier, state, observed
        )
        yield event.plain_result(
            "\n".join(
                [
                    f"Arcaea Pull: v{__version__}",
                    f"last_seen_version: {observed}",
                    f"last_downloaded_version: {downloaded}",
                    f"check_enabled: {bool(self.config.get('check_enabled', True))}",
                    f"schedule: {_schedule_summary(self.config)}",
                    f"auto_download: {auto_download}",
                    f"auto_flash_transfer: {auto_flash}",
                    f"verification: {verification_status}",
                    "trusted signer configured: "
                    + (
                        "yes"
                        if _string_list(self.config.get("trusted_signer_sha256", []))
                        else "no"
                    ),
                    "last_verified_version: "
                    f"{state['verification'].get('last_verified_version') or '未记录'}",
                    f"FlashTransfer: {flash_status}",
                    f"distribution: {distribution}",
                ]
            )
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @apull.command("check")
    async def check(self, event: AstrMessageEvent):
        """立即检查一次远端版本。"""
        try:
            result, verification, distribution = await self._check_with_download_notice()
            summary = "检测到版本变化" if result.changed else "版本未变化"
            details = [f"{summary}: {result.artifact.version}"]
            if result.downloaded:
                details.append(f"APK: {result.downloaded.path}")
            if result.notification_error:
                details.append(f"通知失败: {result.notification_error}")
            if verification is not None:
                details.append(f"真实性验证: {verification.verdict.value}")
            if distribution is not None:
                details.append(
                    f"闪传: success={distribution.succeeded}, "
                    f"failed={distribution.failed}, skipped={distribution.skipped}"
                )
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
                f"APK 就绪{reused}: {record.path}\nsize={record.size}\nsha256={record.sha256}"
            )
        except Exception as exc:  # noqa: BLE001 - return diagnostic to admin
            logger.exception(f"Manual Arcaea APK download failed: {exc}")
            yield event.plain_result(f"下载失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @apull.command("verify")
    async def verify(self, event: AstrMessageEvent):
        """验证当前远端版本已下载 APK 的签名、身份与版本。"""
        if not bool(self.config.get("verification_enabled", True)):
            yield event.plain_result(
                "CONFIG_SECURITY_ERROR：verification_enabled 已关闭，无法建立可信产物。"
            )
            return
        try:
            async with self.pipeline_lock:
                artifact = await self.api_client.fetch()
                record = await asyncio.to_thread(
                    self.downloader.existing_record, artifact
                )
                if record is not None:
                    result = await self.verifier.verify(
                        record, expected_version=artifact.version
                    )
                else:
                    result = None
            if record is None or result is None:
                yield event.plain_result(
                    f"无法验证：当前最新版本 {artifact.version} 尚无可靠本地 APK；"
                    "请先执行 /apull download。"
                )
                return
            await self._notify_verification_failure(result, artifact.version)
            details = [f"verdict={result.verdict.value}", f"reason={result.reason}"]
            if result.artifact is not None:
                verified = result.artifact
                details.extend(
                    [
                        f"package={verified.package_name}",
                        f"versionName={verified.version_name}",
                        f"versionCode={verified.version_code}",
                        "signer_sha256=" + ",".join(verified.signer_certificate_sha256),
                        f"file_sha256={verified.file_sha256}",
                        f"path={verified.path}",
                    ]
                )
            yield event.plain_result("\n".join(details))
        except Exception as exc:  # noqa: BLE001 - return diagnostic to admin
            logger.exception(f"Manual Arcaea APK verification failed: {exc}")
            yield event.plain_result(f"验证失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @apull.command("distribute")
    async def distribute(self, event: AstrMessageEvent):
        """仅分发当前远端版本已可靠下载的 APK，不隐式下载。"""
        if not bool(self.config.get("verification_enabled", True)):
            yield event.plain_result("CONFIG_SECURITY_ERROR：真实性验证被禁用，拒绝分发。")
            return
        try:
            async with self.pipeline_lock:
                artifact = await self.api_client.fetch()
                verified = await asyncio.to_thread(
                    self.verifier.load_verified, artifact.version
                )
                if verified is not None:
                    result = await self.distributor.distribute(verified)
                else:
                    result = None
            if verified is None or result is None:
                yield event.plain_result(
                    f"SECURITY_HOLD：当前最新版本 {artifact.version} 没有可复用的"
                    " VERIFIED 产物；请先执行 /apull verify 并处理验证错误。"
                )
                return
            await self._notify_distribution(result)
            details = [
                f"分发完成: version={result.version}",
                f"success={result.succeeded}, failed={result.failed}, skipped={result.skipped}",
            ]
            details.extend(
                f"{item.target}: {item.status.value}"
                + (" (already sent)" if item.skipped else "")
                + (f" ({item.error})" if item.error else "")
                for item in result.targets
            )
            yield event.plain_result("\n".join(details))
        except Exception as exc:  # noqa: BLE001 - return diagnostic to admin
            logger.exception(f"Manual Arcaea APK distribution failed: {exc}")
            yield event.plain_result(f"分发失败：{exc}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @apull.command("flash_test")
    async def flash_test(self, event: AstrMessageEvent):
        """向当前白名单群发送一个无敏感信息的小型 QQ 闪传探针。"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("闪传诊断只能在 aiocqhttp 群聊中执行。")
            return
        probe_path = Path(self.data_dir) / "flash-transfer-probe.txt"
        probe_path.write_text(
            "astrbot_plugin_arcaea_pull Flash Transfer PoC\n"
            "This file contains no APK or credentials.\n",
            encoding="utf-8",
        )
        try:
            backend = self.backend_provider.resolve()
            result = await backend.send_file(
                group_id, probe_path, name="Arcaea Pull FlashTransfer PoC"
            )
            yield event.plain_result(
                f"QQ 闪传 PoC 成功：group={result.target}, fileset_id={result.file_set_id}。"
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
    if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 1440:
        return "INVALID"
    primary = f"every {interval}m from local 00:00"
    return f"{primary}; extras={extras or 'none'}"


def _distribution_summary(state: dict[str, Any], version: str) -> str:
    versions = state.get("distribution", {}).get("versions", {})
    targets = versions.get(version, {}).get("targets", {})
    counts = {"pending": 0, "success": 0, "failed": 0}
    for value in targets.values():
        status = value.get("status") if isinstance(value, dict) else None
        if status in counts:
            counts[status] += 1
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _verification_status(
    config: AstrBotConfig,
    verifier: AuthenticityVerifier,
    state: dict[str, Any],
    version: str,
) -> str:
    if not bool(config.get("verification_enabled", True)):
        return "SECURITY_HOLD (VERIFICATION_DISABLED)"
    try:
        verifier.preflight()
    except Exception as exc:  # noqa: BLE001 - concise status only
        message = str(exc)
        if "must be configured" in message:
            return "SECURITY_HOLD (TRUST_NOT_CONFIGURED)"
        if "invalid trusted signer" in message:
            return "SECURITY_HOLD (TRUST_CONFIGURATION_INVALID)"
        return "UNAVAILABLE (VERIFIER_UNAVAILABLE)"
    if verifier.load_verified(version) is not None:
        return "VERIFIED"
    attempt = state.get("verification", {}).get("last_attempt", {})
    if attempt.get("version") == version and attempt.get("verdict"):
        return f"SECURITY_HOLD ({attempt['verdict']})"
    return "UNVERIFIED"
