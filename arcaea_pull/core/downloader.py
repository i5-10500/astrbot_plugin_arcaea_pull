"""Reliable streaming APK downloader."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from arcaea_pull.models import DownloadRecord, RemoteArtifact
from arcaea_pull.utils.filesystem import (
    ArtifactValidationError,
    safe_version_component,
    validate_apk,
)
from arcaea_pull.utils.hashing import sha256_file

from .api_client import USER_AGENT, require_https
from .state_manager import StateManager


class DownloadError(RuntimeError):
    """Base class for download failures."""


class DownloadHttpError(DownloadError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"download HTTP {status}")


class Downloader:
    def __init__(
        self,
        output_dir: str | Path,
        state: StateManager,
        *,
        timeout: float = 30,
        retry_count: int = 3,
        min_size: int = 1024,
        chunk_size: int = 1024 * 1024,
        session: aiohttp.ClientSession | Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.output_dir = Path(output_dir)
        self.state = state
        self.timeout = max(float(timeout), 0.1)
        self.retry_count = max(int(retry_count), 1)
        self.min_size = max(int(min_size), 1)
        self.chunk_size = max(int(chunk_size), 1)
        self._session = session
        self._owns_session = session is None
        self._sleep = sleep
        self.clock = clock

    async def _get_session(self) -> aiohttp.ClientSession | Any:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(
                total=None,
                connect=min(self.timeout, 10),
                sock_read=self.timeout,
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
            )
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def download(self, artifact: RemoteArtifact) -> DownloadRecord:
        require_https(artifact.url, field="artifact.url")
        filename = f"arcaea_{safe_version_component(artifact.version)}.apk"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        final_path = self.output_dir / filename
        part_path = final_path.with_suffix(".apk.part")

        reused = self._existing_record(artifact, final_path)
        if reused is not None:
            return reused

        last_error: Exception | None = None
        for attempt in range(self.retry_count):
            part_path.unlink(missing_ok=True)
            try:
                await self._download_once(artifact.url, part_path)
                size = validate_apk(part_path, min_size=self.min_size)
                digest = sha256_file(part_path)
                os.replace(part_path, final_path)
                record = DownloadRecord(
                    version=artifact.version,
                    source_url=artifact.url,
                    path=final_path.resolve(),
                    size=size,
                    sha256=digest,
                    downloaded_at=self.clock().astimezone(timezone.utc).isoformat(),
                )
                self.state.record_download_success(record)
                return record
            except (asyncio.TimeoutError, aiohttp.ClientError, ArtifactValidationError) as exc:
                last_error = exc
            except DownloadHttpError as exc:
                last_error = exc
                if exc.status != 429 and exc.status < 500:
                    break
            except OSError as exc:
                last_error = exc
                break
            finally:
                part_path.unlink(missing_ok=True)
            if attempt + 1 < self.retry_count:
                await self._sleep(min(2 ** attempt, 4))

        message = f"download failed after {self.retry_count} attempt(s): {last_error}"
        self.state.record_download_failure(
            version=artifact.version,
            source_url=artifact.url,
            attempted_at=self.clock().astimezone(timezone.utc).isoformat(),
            error=message,
        )
        raise DownloadError(message) from last_error

    async def _download_once(self, url: str, part_path: Path) -> None:
        session = await self._get_session()
        async with session.get(url, headers={"User-Agent": USER_AGENT}) as response:
            if response.status < 200 or response.status >= 300:
                raise DownloadHttpError(response.status)
            expected_size = _content_length(response)
            received = 0
            with part_path.open("wb") as stream:
                async for chunk in response.content.iter_chunked(self.chunk_size):
                    if chunk:
                        stream.write(chunk)
                        received += len(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if expected_size is not None and received != expected_size:
                raise ArtifactValidationError(
                    f"incomplete download: expected {expected_size} byte(s), received {received}"
                )

    def _existing_record(
        self, artifact: RemoteArtifact, final_path: Path
    ) -> DownloadRecord | None:
        download_state = self.state.load()["download"]
        if download_state.get("last_downloaded_version") != artifact.version:
            return None
        recorded_path = Path(download_state.get("path", final_path))
        if not recorded_path.is_file():
            return None
        try:
            size = validate_apk(recorded_path, min_size=self.min_size)
            digest = sha256_file(recorded_path)
        except (OSError, ArtifactValidationError):
            return None
        if size != download_state.get("size") or digest != download_state.get("sha256"):
            return None
        return DownloadRecord(
            version=artifact.version,
            source_url=str(download_state.get("source_url", artifact.url)),
            path=recorded_path.resolve(),
            size=size,
            sha256=digest,
            downloaded_at=str(download_state.get("downloaded_at", "")),
            reused=True,
        )


def _content_length(response: Any) -> int | None:
    value = getattr(response, "content_length", None)
    if value is None:
        headers = getattr(response, "headers", {})
        value = headers.get("Content-Length") if headers else None
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

