import asyncio
from pathlib import Path

import pytest

from arcaea_pull.core.state_manager import StateManager
from arcaea_pull.distribution.base import FlashTransferResult
from arcaea_pull.distribution.service import DistributionService
from arcaea_pull.models import DistributionStatus, DownloadRecord


def record(tmp_path, version="1", digest="a" * 64):
    return DownloadRecord(
        version=version,
        source_url="https://example.test/a.apk",
        path=Path(tmp_path / f"{version}.apk"),
        size=10,
        sha256=digest,
        downloaded_at="now",
    )


class Backend:
    status = "READY"

    def __init__(self, fail_once=()):
        self.calls = []
        self.fail_once = set(fail_once)

    async def send_file(self, target, path, *, name=""):
        self.calls.append(target)
        if target in self.fail_once:
            self.fail_once.remove(target)
            raise RuntimeError(f"temporary failure for {target}")
        return FlashTransferResult(target, f"fs-{target}", "fake")


@pytest.mark.asyncio
async def test_success_is_skipped_and_failure_retries_on_unchanged_version(tmp_path):
    state = StateManager(tmp_path / "state.json")
    backend = Backend(fail_once=["2"])
    service = DistributionService(state, lambda: backend, ["1", "2", "3"])
    apk = record(tmp_path)

    first = await service.distribute(apk)
    second = await service.distribute(apk)

    assert first.succeeded == 2 and first.failed == 1
    assert second.succeeded == 1 and second.skipped == 2 and second.failed == 0
    assert backend.calls == ["1", "2", "3", "2"]
    assert state.distribution_target("1", "1")["status"] == "success"
    assert state.distribution_target("1", "2")["attempts"] == 2


@pytest.mark.asyncio
async def test_allowlist_addition_is_sent_without_resending_existing_target(tmp_path):
    state = StateManager(tmp_path / "state.json")
    backend = Backend()
    apk = record(tmp_path)
    await DistributionService(state, lambda: backend, ["1"]).distribute(apk)
    result = await DistributionService(state, lambda: backend, ["1", "2"]).distribute(apk)
    assert backend.calls == ["1", "2"]
    assert result.skipped == 1 and result.succeeded == 1


@pytest.mark.asyncio
async def test_removed_allowlist_target_is_not_attempted(tmp_path):
    state = StateManager(tmp_path / "state.json")
    first_backend = Backend()
    apk = record(tmp_path)
    await DistributionService(state, lambda: first_backend, ["1", "2"]).distribute(apk)

    second_backend = Backend()
    result = await DistributionService(state, lambda: second_backend, ["1"]).distribute(apk)
    assert second_backend.calls == []
    assert [item.target for item in result.targets] == ["1"]
    assert state.distribution_target("1", "2")["status"] == "success"


@pytest.mark.asyncio
async def test_versions_and_changed_hashes_have_independent_delivery(tmp_path):
    state = StateManager(tmp_path / "state.json")
    backend = Backend()
    service = DistributionService(state, lambda: backend, ["1"])
    await service.distribute(record(tmp_path, version="1", digest="a" * 64))
    await service.distribute(record(tmp_path, version="1", digest="b" * 64))
    await service.distribute(record(tmp_path, version="2", digest="c" * 64))
    assert backend.calls == ["1", "1", "1"]


@pytest.mark.asyncio
async def test_backend_resolution_failure_is_recorded_and_retried(tmp_path):
    state = StateManager(tmp_path / "state.json")
    attempts = 0

    def unavailable():
        nonlocal attempts
        attempts += 1
        raise RuntimeError("adapter offline")

    apk = record(tmp_path)
    state.record_download_success(apk)
    download_before = state.load()["download"].copy()
    service = DistributionService(state, unavailable, ["1"])
    first = await service.distribute(apk)
    second = await service.distribute(apk)
    assert first.targets[0].status == DistributionStatus.FAILED
    assert second.targets[0].status == DistributionStatus.FAILED
    assert attempts == 2
    assert state.distribution_target("1", "1")["attempts"] == 2
    assert state.load()["download"] == download_before


@pytest.mark.asyncio
async def test_concurrent_distribution_rounds_do_not_duplicate_send(tmp_path):
    state = StateManager(tmp_path / "state.json")
    backend = Backend()
    service = DistributionService(state, lambda: backend, ["1"])
    apk = record(tmp_path)
    first, second = await asyncio.gather(service.distribute(apk), service.distribute(apk))
    assert backend.calls == ["1"]
    assert sorted((first.succeeded, second.succeeded)) == [0, 1]
    assert sorted((first.skipped, second.skipped)) == [0, 1]
