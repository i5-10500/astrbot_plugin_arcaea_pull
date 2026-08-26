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

from ..models import DistributionStatus, DownloadRecord

SCHEMA_VERSION = 2


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
                state, migrated = self._migrate(state)
                self._validate(state)
                if migrated:
                    self.save(state)
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
        with self._lock:
            state = self.load()
            state["remote"] = {"version": version, "url": url}
            state["observed"] = {"version": version, "observed_at": observed_at}
            self.save(state)

    def record_notification(self, version: str) -> None:
        with self._lock:
            state = self.load()
            state["notification"]["last_notified_version"] = version
            self.save(state)

    def record_download_success(self, record: DownloadRecord) -> None:
        with self._lock:
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
        with self._lock:
            state = self.load()
            state["download"]["last_attempt"] = {
                "version": version,
                "source_url": source_url,
                "attempted_at": attempted_at,
                "success": False,
                "error": error,
            }
            self.save(state)

    def distribution_target(self, version: str, target: str) -> dict[str, Any]:
        state = self.load()
        versions = state["distribution"].get("versions", {})
        version_state = versions.get(str(version), {})
        targets = version_state.get("targets", {})
        value = targets.get(str(target), {})
        return copy.deepcopy(value) if isinstance(value, dict) else {}

    def record_distribution_pending(
        self,
        record: DownloadRecord,
        target: str,
        *,
        attempted_at: str,
    ) -> None:
        with self._lock:
            state = self.load()
            entry = self._distribution_entry(state, record.version, target)
            entry.update(
                {
                    "status": DistributionStatus.PENDING.value,
                    "sha256": record.sha256,
                    "path": str(record.path),
                    "last_attempted_at": attempted_at,
                    "attempts": int(entry.get("attempts", 0)) + 1,
                }
            )
            entry.pop("error", None)
            self.save(state)

    def record_distribution_success(
        self,
        record: DownloadRecord,
        target: str,
        *,
        file_set_id: str,
        backend: str,
        sent_at: str,
    ) -> None:
        with self._lock:
            state = self.load()
            entry = self._distribution_entry(state, record.version, target)
            entry.update(
                {
                    "status": DistributionStatus.SUCCESS.value,
                    "sha256": record.sha256,
                    "path": str(record.path),
                    "file_set_id": file_set_id,
                    "backend": backend,
                    "sent_at": sent_at,
                }
            )
            entry.pop("error", None)
            self.save(state)

    def record_distribution_failure(
        self,
        record: DownloadRecord,
        target: str,
        *,
        error: str,
        attempted_at: str,
    ) -> None:
        with self._lock:
            state = self.load()
            entry = self._distribution_entry(state, record.version, target)
            already_counted = (
                entry.get("status") == DistributionStatus.PENDING.value
                and entry.get("sha256") == record.sha256
            )
            attempts = int(entry.get("attempts", 0)) + (0 if already_counted else 1)
            entry.update(
                {
                    "status": DistributionStatus.FAILED.value,
                    "sha256": record.sha256,
                    "path": str(record.path),
                    "last_attempted_at": attempted_at,
                    "attempts": attempts,
                    "error": error,
                }
            )
            self.save(state)

    @staticmethod
    def _distribution_entry(state: dict[str, Any], version: str, target: str) -> dict[str, Any]:
        versions = state["distribution"].setdefault("versions", {})
        version_state = versions.setdefault(str(version), {"targets": {}})
        targets = version_state.setdefault("targets", {})
        return targets.setdefault(str(target), {})

    @staticmethod
    def _migrate(state: object) -> tuple[dict[str, Any], bool]:
        if not isinstance(state, dict):
            raise StateError("state root must be an object")
        version = state.get("schema_version")
        if version == SCHEMA_VERSION:
            return state, False
        if version != 1:
            raise StateError(f"unsupported state schema: {version!r}")
        migrated = copy.deepcopy(state)
        legacy_distribution = migrated.get("distribution")
        migrated["distribution"] = {"versions": {}}
        if legacy_distribution:
            migrated["distribution"]["legacy_v1"] = legacy_distribution
        migrated["schema_version"] = SCHEMA_VERSION
        return migrated, True

    @staticmethod
    def _validate(state: object) -> None:
        if not isinstance(state, dict):
            raise StateError("state root must be an object")
        if state.get("schema_version") != SCHEMA_VERSION:
            raise StateError(f"unsupported state schema: {state.get('schema_version')!r}")
        for key in ("remote", "observed", "notification", "download", "distribution"):
            if not isinstance(state.get(key), dict):
                raise StateError(f"state field {key!r} must be an object")
