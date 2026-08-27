from pathlib import Path

import pytest

from arcaea_pull.distribution.base import (
    BackendActionError,
    BackendUnavailableError,
    TargetNotAllowedError,
)
from arcaea_pull.distribution.napcat_flash_transfer import (
    CREATE_ACTION,
    SEND_ACTION,
    NapCatFlashTransferBackend,
)


def source_file(tmp_path: Path) -> Path:
    path = tmp_path / "probe.txt"
    path.write_text("non-sensitive probe", encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_constructs_create_then_send_actions(tmp_path):
    calls = []

    async def caller(action, **payload):
        calls.append((action, payload))
        if action == CREATE_ACTION:
            return {"result": 0, "createFlashTransferResult": {"fileSetId": "set-1"}}
        return {"errCode": 0, "errMsg": ""}

    backend = NapCatFlashTransferBackend(caller, ["123"], self_id="bot")
    result = await backend.send_file("123", source_file(tmp_path), name="probe")
    assert result.file_set_id == "set-1"
    assert calls[0][0] == CREATE_ACTION
    assert calls[0][1]["files"].endswith("probe.txt")
    assert calls[0][1]["self_id"] == "bot"
    assert calls[1] == (
        SEND_ACTION,
        {"fileset_id": "set-1", "group_id": "123", "self_id": "bot"},
    )


@pytest.mark.asyncio
async def test_rejects_non_allowlisted_group_before_action(tmp_path):
    called = False

    async def caller(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}

    backend = NapCatFlashTransferBackend(caller, ["allowed"])
    with pytest.raises(TargetNotAllowedError):
        await backend.send_file("denied", source_file(tmp_path))
    assert not called


@pytest.mark.asyncio
async def test_unsupported_action_has_typed_error(tmp_path):
    async def caller(*_args, **_kwargs):
        raise RuntimeError("unknown action")

    backend = NapCatFlashTransferBackend(caller, ["123"])
    with pytest.raises(BackendUnavailableError, match="v4.10.47"):
        await backend.send_file("123", source_file(tmp_path))


@pytest.mark.asyncio
async def test_empty_api_unavailable_error_keeps_exception_type(tmp_path):
    api_unavailable = type("ApiNotAvailable", (Exception,), {})

    async def caller(*_args, **_kwargs):
        raise api_unavailable

    backend = NapCatFlashTransferBackend(caller, ["123"])
    with pytest.raises(BackendUnavailableError, match="ApiNotAvailable"):
        await backend.send_file("123", source_file(tmp_path))


@pytest.mark.asyncio
async def test_empty_backend_error_keeps_exception_type(tmp_path):
    async def caller(*_args, **_kwargs):
        raise TimeoutError

    backend = NapCatFlashTransferBackend(caller, ["123"])
    with pytest.raises(BackendActionError, match="TimeoutError"):
        await backend.send_file("123", source_file(tmp_path))


@pytest.mark.asyncio
async def test_create_action_failure_propagates(tmp_path):
    async def caller(*_args, **_kwargs):
        return {"result": 12, "message": "upload rejected"}

    backend = NapCatFlashTransferBackend(caller, ["123"])
    with pytest.raises(BackendActionError, match="upload rejected"):
        await backend.send_file("123", source_file(tmp_path))


@pytest.mark.asyncio
async def test_send_action_requires_explicit_success_and_never_falls_back(tmp_path):
    actions = []

    async def caller(action, **_kwargs):
        actions.append(action)
        if action == CREATE_ACTION:
            return {"result": 0, "createFlashTransferResult": {"fileSetId": "set-1"}}
        return {"errCode": 1, "errMsg": "send failed"}

    backend = NapCatFlashTransferBackend(caller, ["123"])
    with pytest.raises(BackendActionError, match="send failed"):
        await backend.send_file("123", source_file(tmp_path))
    assert actions == [CREATE_ACTION, SEND_ACTION]
    assert "send_group_msg" not in actions
