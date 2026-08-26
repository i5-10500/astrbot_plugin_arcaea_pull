"""Discover official Android SDK tools without bundling the SDK."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .base import ToolUnavailableError


def resolve_apksigner(configured: str = "") -> Path:
    try:
        candidates = _sdk_candidates("build-tools", "apksigner")
    except OSError as exc:
        raise ToolUnavailableError(f"could not inspect Android SDK build-tools: {exc}") from exc
    return _resolve("apksigner", configured, candidates)


def resolve_apkanalyzer(configured: str = "") -> Path:
    try:
        candidates = _sdk_candidates("cmdline-tools", "apkanalyzer", bin_subdir=True)
    except OSError as exc:
        raise ToolUnavailableError(
            f"could not inspect Android SDK command-line tools: {exc}"
        ) from exc
    return _resolve("apkanalyzer", configured, candidates)


def _resolve(name: str, configured: str, candidates: list[Path]) -> Path:
    if configured.strip():
        explicit = Path(configured.strip())
        if explicit.is_file():
            return explicit.resolve()
        raise ToolUnavailableError(f"configured {name} does not exist: {explicit}")
    discovered = shutil.which(name)
    if discovered:
        return Path(discovered).resolve()
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ToolUnavailableError(f"{name} not found in PATH or Android SDK; configure {name}_path")


def _sdk_candidates(component: str, tool: str, *, bin_subdir: bool = False) -> list[Path]:
    suffixes = (".bat", ".exe", "") if os.name == "nt" else ("",)
    roots: list[Path] = []
    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(variable, "").strip()
        if value:
            root = Path(value)
            if root not in roots:
                roots.append(root)
    found: list[Path] = []
    for root in roots:
        parent = root / component
        if not parent.is_dir():
            continue
        versions = sorted(
            (item for item in parent.iterdir() if item.is_dir()),
            key=lambda item: _version_key(item.name),
            reverse=True,
        )
        for version in versions:
            tool_root = version / "bin" if bin_subdir else version
            found.extend(tool_root / f"{tool}{suffix}" for suffix in suffixes)
    return found


def _version_key(value: str) -> tuple[int, ...]:
    if value.lower() == "latest":
        return (10**9,)
    numbers = tuple(int(item) for item in re.findall(r"\d+", value))
    return numbers or (0,)
