import asyncio

import pytest

from arcaea_pull.core.notifier import Notifier
from arcaea_pull.core.state_manager import StateManager
from arcaea_pull.core.update_checker import UpdateChecker
from arcaea_pull.models import RemoteArtifact


class FakeApi:
    def __init__(self, artifact):
        self.artifact = artifact
        self.calls = 0

    async def fetch(self):
        self.calls += 1
        await asyncio.sleep(0)
        return self.artifact


@pytest.mark.asyncio
async def test_first_discovery_notifies_then_same_version_does_not(tmp_path):
    sent = []

    async def sender(target, message):
        sent.append((target, message))

    checker = UpdateChecker(
        FakeApi(RemoteArtifact("6.0.0c", "https://x/a")),
        StateManager(tmp_path / "state.json"),
        notifier=Notifier(["target"], sender),
    )
    first = await checker.check()
    second = await checker.check()
    assert first.changed and first.notified
    assert not second.changed and not second.notified
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_opaque_version_change_triggers_without_semver_ordering(tmp_path):
    state = StateManager(tmp_path / "state.json")
    state.record_observed("z-newer-looking", "https://x/a", "before")
    sent = []

    async def sender(_target, message):
        sent.append(message)

    checker = UpdateChecker(
        FakeApi(RemoteArtifact("a-opaque", "https://x/b")),
        state,
        notifier=Notifier(["target"], sender),
    )
    result = await checker.check()
    assert result.changed
    assert sent


@pytest.mark.asyncio
async def test_notification_failure_does_not_mark_success(tmp_path):
    async def failing_sender(_target, _message):
        raise RuntimeError("offline")

    state = StateManager(tmp_path / "state.json")
    checker = UpdateChecker(
        FakeApi(RemoteArtifact("1", "https://x/a")),
        state,
        notifier=Notifier(["target"], failing_sender),
    )
    result = await checker.check()
    assert result.notification_error
    assert "last_notified_version" not in state.load()["notification"]


@pytest.mark.asyncio
async def test_concurrent_checks_are_serialized_and_do_not_duplicate_notification(tmp_path):
    sent = []

    async def sender(_target, _message):
        sent.append("sent")

    api = FakeApi(RemoteArtifact("1", "https://x/a"))
    checker = UpdateChecker(
        api,
        StateManager(tmp_path / "state.json"),
        notifier=Notifier(["target"], sender),
    )
    results = await asyncio.gather(checker.check(), checker.check())
    assert sum(result.changed for result in results) == 1
    assert sent == ["sent"]


@pytest.mark.asyncio
async def test_auto_download_reenters_downloader_when_version_is_unchanged(tmp_path):
    calls = []

    class Downloader:
        async def download(self, artifact):
            calls.append(artifact.version)
            return None

    checker = UpdateChecker(
        FakeApi(RemoteArtifact("1", "https://x/a")),
        StateManager(tmp_path / "state.json"),
        downloader=Downloader(),
        auto_download=True,
    )
    await checker.check()
    await checker.check()
    assert calls == ["1", "1"]
