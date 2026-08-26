import asyncio
import hashlib
import io
import zipfile
from collections import deque

import aiohttp
import pytest

from arcaea_pull.core.downloader import Downloader, DownloadError
from arcaea_pull.core.state_manager import StateManager
from arcaea_pull.models import RemoteArtifact


def apk_bytes():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"manifest")
    return stream.getvalue()


class FakeContent:
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error

    async def iter_chunked(self, _size):
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error


class FakeResponse:
    def __init__(self, data=b"", status=200, content_length=None, error=None):
        self.status = status
        self.content_length = len(data) if content_length is None else content_length
        self.headers = {}
        self.content = FakeContent([data], error=error)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return self.responses.popleft()


def make_downloader(tmp_path, responses, retry_count=1):
    state = StateManager(tmp_path / "state.json")
    downloader = Downloader(
        tmp_path / "downloads",
        state,
        session=FakeSession(responses),
        min_size=1,
        retry_count=retry_count,
        sleep=lambda _: asyncio.sleep(0),
    )
    return downloader, state


@pytest.mark.asyncio
async def test_success_renames_part_and_records_sha256(tmp_path):
    data = apk_bytes()
    downloader, state = make_downloader(tmp_path, [FakeResponse(data)])
    record = await downloader.download(RemoteArtifact("6/unsafe", "https://x/a.apk"))
    assert record.path.name == "arcaea_6_unsafe.apk"
    assert record.path.read_bytes() == data
    assert record.sha256 == hashlib.sha256(data).hexdigest()
    assert not list(record.path.parent.glob("*.part"))
    assert state.load()["download"]["last_downloaded_version"] == "6/unsafe"


@pytest.mark.asyncio
async def test_network_interruption_cleans_part_and_does_not_advance_state(tmp_path):
    response = FakeResponse(
        apk_bytes(), error=aiohttp.ClientPayloadError("interrupted")
    )
    downloader, state = make_downloader(tmp_path, [response])
    with pytest.raises(DownloadError, match="interrupted"):
        await downloader.download(RemoteArtifact("1", "https://x/a.apk"))
    assert not list((tmp_path / "downloads").glob("*.part"))
    assert "last_downloaded_version" not in state.load()["download"]
    assert state.load()["download"]["last_attempt"]["success"] is False


@pytest.mark.asyncio
async def test_http_failure_is_diagnostic(tmp_path):
    downloader, _state = make_downloader(tmp_path, [FakeResponse(status=404)])
    with pytest.raises(DownloadError, match="HTTP 404"):
        await downloader.download(RemoteArtifact("1", "https://x/a.apk"))


@pytest.mark.asyncio
async def test_incomplete_content_length_fails(tmp_path):
    data = apk_bytes()
    downloader, state = make_downloader(
        tmp_path, [FakeResponse(data, content_length=len(data) + 1)]
    )
    with pytest.raises(DownloadError, match="incomplete"):
        await downloader.download(RemoteArtifact("1", "https://x/a.apk"))
    assert "last_downloaded_version" not in state.load()["download"]


@pytest.mark.asyncio
async def test_non_apk_zip_fails(tmp_path):
    downloader, _state = make_downloader(tmp_path, [FakeResponse(b"not an apk")])
    with pytest.raises(DownloadError, match="ZIP/APK signature"):
        await downloader.download(RemoteArtifact("1", "https://x/a.apk"))


@pytest.mark.asyncio
async def test_retry_then_success(tmp_path):
    data = apk_bytes()
    downloader, _state = make_downloader(
        tmp_path, [FakeResponse(status=503), FakeResponse(data)], retry_count=2
    )
    record = await downloader.download(RemoteArtifact("1", "https://x/a.apk"))
    assert record.path.exists()
    assert downloader._session.calls == 2


@pytest.mark.asyncio
async def test_successful_version_is_not_downloaded_twice(tmp_path):
    data = apk_bytes()
    downloader, _state = make_downloader(tmp_path, [FakeResponse(data)])
    artifact = RemoteArtifact("1", "https://x/a.apk")
    first = await downloader.download(artifact)
    second = await downloader.download(artifact)
    assert first.path == second.path
    assert second.reused
    assert downloader._session.calls == 1
