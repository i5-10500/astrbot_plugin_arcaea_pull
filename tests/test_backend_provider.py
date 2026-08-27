from dataclasses import dataclass

import pytest

from arcaea_pull.distribution.backend_provider import BackendProvider
from arcaea_pull.distribution.base import BackendAmbiguousError, BackendUnavailableError


@dataclass
class Meta:
    name: str
    id: str


class Bot:
    def __init__(self, *self_ids):
        self.calls = []
        self._wsr_api_clients = {str(self_id): object() for self_id in self_ids}

    async def call_action(self, action, **payload):
        self.calls.append((action, payload))
        if action == "create_flash_task":
            return {"result": 0, "createFlashTransferResult": {"fileSetId": "fs"}}
        return {"errCode": 0}


class NoActionBot:
    def __init__(self, *self_ids):
        self._wsr_api_clients = {str(self_id): object() for self_id in self_ids}


class Adapter:
    def __init__(self, platform_id, self_id, bot=None, name="aiocqhttp"):
        self._meta = Meta(name, platform_id)
        self.client_self_id = self_id
        self.bot = bot

    def meta(self):
        return self._meta


class Manager:
    def __init__(self, instances):
        self.platform_insts = instances

    def get_insts(self):
        return self.platform_insts


class Context:
    def __init__(self, instances):
        self.platform_manager = Manager(instances)


@pytest.mark.asyncio
async def test_provider_resolves_live_adapter_without_message_event(tmp_path):
    first = Bot("10001")
    adapter = Adapter("qq-main", "astrbot-internal-uuid", first)
    provider = BackendProvider(Context([adapter]), ["20001"])
    source = tmp_path / "probe.txt"
    source.write_text("probe", encoding="utf-8")

    await provider.resolve().send_file("20001", source)
    assert first.calls[0][1]["self_id"] == "10001"

    replacement = Bot("10001")
    adapter.bot = replacement
    await provider.resolve().send_file("20001", source)
    assert replacement.calls


def test_provider_fails_closed_on_ambiguous_adapters():
    provider = BackendProvider(
        Context(
            [
                Adapter("a", "internal-a", Bot("1")),
                Adapter("b", "internal-b", Bot("2")),
            ]
        ),
        ["group"],
    )
    with pytest.raises(BackendAmbiguousError):
        provider.resolve()


def test_provider_selectors_are_deterministic():
    chosen = Bot("2")
    provider = BackendProvider(
        Context(
            [
                Adapter("a", "internal-a", Bot("1")),
                Adapter("b", "internal-b", chosen),
            ]
        ),
        ["group"],
        platform_id="b",
        self_id="2",
    )
    assert provider.resolve() is not None


def test_provider_rejects_missing_or_non_aiocqhttp_platform():
    with pytest.raises(BackendUnavailableError):
        BackendProvider(Context([Adapter("x", "internal", Bot("1"), name="other")]), []).resolve()


def test_provider_rejects_adapter_without_action_api():
    with pytest.raises(BackendUnavailableError, match="call_action"):
        BackendProvider(
            Context([Adapter("x", "internal", NoActionBot("1"))]), []
        ).resolve()


def test_provider_ignores_astrbot_internal_uuid_and_requires_live_onebot_connection():
    adapter = Adapter("x", "astrbot-internal-uuid", Bot())
    with pytest.raises(BackendUnavailableError, match="no active aiocqhttp"):
        BackendProvider(Context([adapter]), []).resolve()


def test_provider_requires_selector_for_multiple_bot_connections():
    provider = BackendProvider(
        Context([Adapter("x", "internal", Bot("10001", "10002"))]), []
    )
    with pytest.raises(BackendAmbiguousError, match="10001.*10002"):
        provider.resolve()
