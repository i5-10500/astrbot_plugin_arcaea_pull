"""Idempotent per-version, per-target Flash Transfer distribution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from datetime import datetime, timezone

from ..core.state_manager import StateManager
from ..models import (
    DistributionResult,
    DistributionStatus,
    DistributionTargetResult,
    DownloadRecord,
    VerifiedArtifact,
)
from .base import FlashTransferBackend


class DistributionService:
    def __init__(
        self,
        state: StateManager,
        backend_factory: Callable[[], FlashTransferBackend],
        targets: Iterable[str],
    ) -> None:
        self.state = state
        self.backend_factory = backend_factory
        self.targets = tuple(dict.fromkeys(str(item) for item in targets if str(item)))
        self._lock = asyncio.Lock()

    async def distribute(self, artifact: VerifiedArtifact) -> DistributionResult:
        if not isinstance(artifact, VerifiedArtifact):
            raise TypeError("DistributionService requires a VerifiedArtifact")
        record = DownloadRecord(
            version=artifact.version,
            source_url=artifact.source_url,
            path=artifact.path,
            size=artifact.size,
            sha256=artifact.file_sha256,
            downloaded_at=artifact.verified_at,
        )
        async with self._lock:
            due: list[str] = []
            results: list[DistributionTargetResult] = []
            for target in self.targets:
                prior = self.state.distribution_target(record.version, target)
                if (
                    prior.get("status") == DistributionStatus.SUCCESS
                    and prior.get("sha256") == record.sha256
                ):
                    results.append(
                        DistributionTargetResult(
                            target=target,
                            status=DistributionStatus.SUCCESS,
                            skipped=True,
                            file_set_id=prior.get("file_set_id"),
                        )
                    )
                else:
                    due.append(target)

            if not due:
                return DistributionResult(record.version, tuple(results))

            try:
                backend = self.backend_factory()
            except Exception as exc:
                error = str(exc)
                for target in due:
                    self.state.record_distribution_failure(
                        record, target, error=error, attempted_at=_now()
                    )
                    results.append(
                        DistributionTargetResult(
                            target=target,
                            status=DistributionStatus.FAILED,
                            error=error,
                        )
                    )
                return DistributionResult(record.version, tuple(results))

            for target in due:
                self.state.record_distribution_pending(record, target, attempted_at=_now())
                try:
                    sent = await backend.send_file(target, record.path, name=record.path.name)
                except Exception as exc:
                    error = str(exc)
                    self.state.record_distribution_failure(
                        record, target, error=error, attempted_at=_now()
                    )
                    results.append(
                        DistributionTargetResult(
                            target=target,
                            status=DistributionStatus.FAILED,
                            error=error,
                        )
                    )
                else:
                    self.state.record_distribution_success(
                        record,
                        target,
                        file_set_id=sent.file_set_id,
                        backend=sent.backend,
                        sent_at=_now(),
                    )
                    results.append(
                        DistributionTargetResult(
                            target=target,
                            status=DistributionStatus.SUCCESS,
                            file_set_id=sent.file_set_id,
                        )
                    )
            order = {target: index for index, target in enumerate(self.targets)}
            results.sort(key=lambda item: order[item.target])
            return DistributionResult(record.version, tuple(results))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
