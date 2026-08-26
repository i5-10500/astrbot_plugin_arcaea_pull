import os

import pytest

from arcaea_pull.verification import tools
from arcaea_pull.verification.base import ToolUnavailableError


def executable_name(name):
    return f"{name}.bat" if os.name == "nt" else name


def test_explicit_tool_path_is_used_and_missing_path_fails(tmp_path):
    signer = tmp_path / executable_name("apksigner")
    aapt2 = tmp_path / executable_name("aapt2")
    signer.write_text("tool", encoding="utf-8")
    aapt2.write_text("tool", encoding="utf-8")
    assert tools.resolve_apksigner(str(signer)) == signer.resolve()
    assert tools.resolve_aapt2(str(aapt2)) == aapt2.resolve()
    with pytest.raises(ToolUnavailableError, match="does not exist"):
        tools.resolve_apksigner(str(tmp_path / "missing"))
    with pytest.raises(ToolUnavailableError, match="does not exist"):
        tools.resolve_aapt2(str(tmp_path / "missing"))


def test_tools_are_discovered_from_android_sdk_with_newest_build_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.shutil, "which", lambda _name: None)
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path))
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    old = tmp_path / "build-tools" / "34.0.0" / executable_name("apksigner")
    newest = tmp_path / "build-tools" / "36.0.0" / executable_name("apksigner")
    aapt2 = tmp_path / "build-tools" / "36.0.0" / executable_name("aapt2")
    for path in (old, newest, aapt2):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("tool", encoding="utf-8")
    assert tools.resolve_apksigner() == newest.resolve()
    assert tools.resolve_aapt2() == aapt2.resolve()


def test_missing_sdk_tools_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.shutil, "which", lambda _name: None)
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path))
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    with pytest.raises(ToolUnavailableError, match="not found"):
        tools.resolve_apksigner()
    with pytest.raises(ToolUnavailableError, match="not found"):
        tools.resolve_aapt2()
