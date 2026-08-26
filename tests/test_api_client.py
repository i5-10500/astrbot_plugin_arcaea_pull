import asyncio

import pytest

from arcaea_pull.core.api_client import (
    ApiClientError,
    ApiPayloadError,
    ApiResponseError,
    ArcaeaApiClient,
)
from tests.fakes import FakeResponse, FakeSession


def payload(**value):
    return {"success": True, "value": value}


@pytest.mark.asyncio
async def test_normal_response():
    client = ArcaeaApiClient(
        session=FakeSession([FakeResponse(payload=payload(version="6.0.0c", url="https://x/a"))])
    )
    result = await client.fetch()
    assert result.version == "6.0.0c"
    assert result.url == "https://x/a"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"success": False}, ApiResponseError),
        ({"success": True}, ApiPayloadError),
        ({"success": True, "value": {"url": "https://x/a"}}, ApiPayloadError),
        ({"success": True, "value": {"version": "1"}}, ApiPayloadError),
        (payload(version="1", url="http://unsafe/a"), ApiPayloadError),
    ],
)
@pytest.mark.asyncio
async def test_invalid_payloads(body, error):
    client = ArcaeaApiClient(session=FakeSession([FakeResponse(payload=body)]))
    with pytest.raises(error):
        await client.fetch()


@pytest.mark.asyncio
async def test_non_json():
    client = ArcaeaApiClient(session=FakeSession([FakeResponse(json_error=ValueError("bad"))]))
    with pytest.raises(ApiPayloadError, match="valid JSON"):
        await client.fetch()


@pytest.mark.parametrize("status", [400, 404])
@pytest.mark.asyncio
async def test_4xx_is_not_retried(status):
    session = FakeSession([FakeResponse(status=status)])
    client = ArcaeaApiClient(session=session, retry_count=3)
    with pytest.raises(ApiClientError, match=f"HTTP {status}"):
        await client.fetch()
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_5xx_retry_succeeds():
    session = FakeSession(
        [
            FakeResponse(status=503),
            FakeResponse(payload=payload(version="2", url="https://x/a")),
        ]
    )
    client = ArcaeaApiClient(session=session, retry_count=2, sleep=lambda _: asyncio.sleep(0))
    assert (await client.fetch()).version == "2"
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_timeout_retries_then_fails():
    session = FakeSession([asyncio.TimeoutError(), asyncio.TimeoutError()])
    client = ArcaeaApiClient(session=session, retry_count=2, sleep=lambda _: asyncio.sleep(0))
    with pytest.raises(ApiClientError, match="2 attempt"):
        await client.fetch()

