"""Asynchronous client for the official Arcaea China APK metadata feed."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import aiohttp

from ..models import RemoteArtifact

DEFAULT_API_URL = "https://webapi.lowiro.com/webapi/serve/static/bin/arcaea/apk"
USER_AGENT = "astrbot_plugin_arcaea_pull/0.3.1"


class ApiClientError(RuntimeError):
    """Base class for metadata request failures."""


class ApiResponseError(ApiClientError):
    """The server returned an HTTP or application-level error."""


class ApiPayloadError(ApiClientError):
    """The response did not contain the required schema."""


def require_https(url: str, *, field: str = "url") -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ApiPayloadError(f"{field} must be an absolute HTTPS URL")
    return url


class ArcaeaApiClient:
    def __init__(
        self,
        *,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 30,
        retry_count: int = 3,
        session: aiohttp.ClientSession | Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.api_url = require_https(api_url, field="api_url")
        self.timeout = max(float(timeout), 0.1)
        self.retry_count = max(int(retry_count), 1)
        self._session = session
        self._owns_session = session is None
        self._sleep = sleep

    async def _get_session(self) -> aiohttp.ClientSession | Any:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(
                total=self.timeout,
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

    async def fetch(self) -> RemoteArtifact:
        last_error: Exception | None = None
        for attempt in range(self.retry_count):
            try:
                return await self._fetch_once()
            except (asyncio.TimeoutError, aiohttp.ClientError, ApiResponseError) as exc:
                last_error = exc
                if isinstance(exc, ApiResponseError) and not _is_retryable_response(exc):
                    raise
                if attempt + 1 < self.retry_count:
                    await self._sleep(min(2 ** attempt, 4))
            except ApiPayloadError:
                raise
        raise ApiClientError(
            f"metadata request failed after {self.retry_count} attempt(s): {last_error}"
        ) from last_error

    async def _fetch_once(self) -> RemoteArtifact:
        session = await self._get_session()
        async with session.get(self.api_url, headers={"User-Agent": USER_AGENT}) as response:
            if response.status < 200 or response.status >= 300:
                raise ApiResponseError(f"HTTP {response.status}")
            try:
                payload = await response.json(content_type=None)
            except (ValueError, TypeError) as exc:
                raise ApiPayloadError("metadata response is not valid JSON") from exc
        return self.parse_payload(payload)

    @staticmethod
    def parse_payload(payload: object) -> RemoteArtifact:
        if not isinstance(payload, dict):
            raise ApiPayloadError("metadata response must be an object")
        if payload.get("success") is not True:
            raise ApiResponseError("metadata response reported success=false")
        value = payload.get("value")
        if not isinstance(value, dict):
            raise ApiPayloadError("metadata response is missing value")
        version = value.get("version")
        url = value.get("url")
        if not isinstance(version, str) or not version.strip():
            raise ApiPayloadError("metadata response is missing version")
        if not isinstance(url, str) or not url.strip():
            raise ApiPayloadError("metadata response is missing url")
        return RemoteArtifact(version=version.strip(), url=require_https(url, field="value.url"))


def _is_retryable_response(exc: ApiResponseError) -> bool:
    message = str(exc)
    if not message.startswith("HTTP "):
        return False
    try:
        status = int(message.split()[1])
    except (IndexError, ValueError):
        return False
    return status == 429 or status >= 500
