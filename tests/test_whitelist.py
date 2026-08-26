import pytest

from arcaea_pull.core.notifier import NotificationError, Notifier


@pytest.mark.asyncio
async def test_notify_allow_and_reject_are_explicit():
    calls = []

    async def sender(target, message):
        calls.append((target, message))

    notifier = Notifier(["umo:allowed"], sender)
    await notifier.send("umo:allowed", "ok")
    with pytest.raises(NotificationError):
        await notifier.send("umo:denied", "no")
    assert calls == [("umo:allowed", "ok")]


def test_notify_and_flash_lists_are_not_equivalent():
    notify_targets = {"umo:group:1"}
    flash_targets = {"1"}
    assert "1" not in notify_targets
    assert "umo:group:1" not in flash_targets
