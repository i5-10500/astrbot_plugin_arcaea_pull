"""Crash-safe JSON state persistence."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arcaea_pull.models import DownloadRecord

SCHEMA_VERSION = 1


class StateError(RuntimeError):
    """State could not be read or written safely."""


def default_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "remote": {},
        "observed": {},
        "notification": {},
        "download": {},
        "distribution": {},
        "last_extracted_version": None,
    }


class StateManager:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                state = default_state()
                self.save(state)
                return copy.deepcopy(state)
            try:
                with self.path.open("r", encoding="utf-8") as stream:
                    state = json.load(stream)
                self._validate(state)
                return state
            except (json.JSONDecodeError, UnicodeDecodeError, StateError) as exc:
                suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                recovery_path = self.path.with_name(f"{self.path.name}.corrupt-{suffix}")
                try:
                    os.replace(self.path, recovery_path)
                    self.save(default_state())
                except OSError as recovery_exc:
                    raise StateError(
                        f"invalid state ({exc}); recovery failed: {recovery_exc}"
                    ) from recovery_exc
                return default_state()
            except OSError as exc:
                raise StateError(f"unable to read state: {exc}") from exc

    def save(self, state: dict[str, Any]) -> None:
        self._validate(state)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as stream:
                    temp_path = Path(stream.name)
                    json.dump(state, stream, ensure_ascii=False, indent=2, sort_keys=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, self.path)
            except OSError as exc:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
                raise StateError(f"unable to write state atomically: {exc}") from exc

    def record_observed(self, version: str, url: str, observed_at: str) -> None:
        state = self.load()
        state["remote"] = {"version": version, "url": url}
        state["observed"] = {"version": version, "observed_at": observed_at}
        self.save(state)

    def record_notification(self, version: str) -> None:
        state = self.load()
        state["notification"]["last_notified_version"] = version
        self.save(state)

    def record_download_success(self, record: DownloadRecord) -> None:
        state = self.load()
        values = {
            "last_downloaded_version": record.version,
            "source_url": record.source_url,
            "path": str(record.path),
            "size": record.size,
            "sha256": record.sha256,
            "downloaded_at": record.downloaded_at,
        }
        state["download"].update(values)
        state["download"]["last_attempt"] = {**values, "success": True}
        self.save(state)

    def record_download_failure(
        self,
        *,
        version: str,
        source_url: str,
        attempted_at: str,
        error: str,
    ) -> None:
        state = self.load()
        state["download"]["last_attempt"] = {
            "version": version,
            "source_url": source_url,
            "attempted_at": attempted_at,
            "success": False,
            "error": error,
        }
        self.save(state)

    @staticmethod
    def _validate(state: object) -> None:
        if not isinstance(state, dict):
            raise StateError("state root must be an object")
        if state.get("schema_version") != SCHEMA_VERSION:
            raise StateError(f"unsupported state schema: {state.get('schema_version')!r}")
        for key in ("remote", "observed", "notification", "download", "distribution"):
            if not isinstance(state.get(key), dict):
                raise StateError(f"state field {key!r} must be an object")
