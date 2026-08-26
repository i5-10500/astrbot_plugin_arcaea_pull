"""Timezone-aware interval and fixed-time scheduling helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SECONDS_PER_DAY = 24 * 60 * 60


class ScheduleConfigError(ValueError):
    """Schedule configuration is invalid."""


def seconds_until_next(
    now: datetime,
    timezone_name: str,
    *,
    interval_minutes: int = 30,
    extra_check_times: Iterable[str] = (),
) -> float:
    """Return the delay to the next interval slot or extra wall time.

    The positive whole-minute interval is anchored at local midnight. Extra
    wall times are merged into the schedule.
    """
    if now.utcoffset() is None:
        raise ScheduleConfigError("now must be timezone-aware")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleConfigError(f"unknown timezone: {timezone_name}") from exc

    interval = _interval_seconds(interval_minutes)
    local_now = now.astimezone(zone)
    candidates = [_next_interval_slot(local_now, interval)]

    for value in extra_check_times:
        hour, minute, second = _parse_wall_time(
            str(value), field="extra_check_times item"
        )
        candidates.append(_next_wall_time(local_now, hour, minute, second))

    utc_now = now.astimezone(timezone.utc)
    next_utc = min(candidate.astimezone(timezone.utc) for candidate in candidates)
    return max((next_utc - utc_now).total_seconds(), 0.0)


def _interval_seconds(minutes: int) -> int:
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise ScheduleConfigError("check_interval_minutes must be a positive integer")
    total = minutes * 60
    if total > SECONDS_PER_DAY:
        raise ScheduleConfigError("check interval cannot exceed 24 hours")
    return total


def _parse_wall_time(value: str, *, field: str) -> tuple[int, int, int]:
    parts = value.split(":")
    if len(parts) not in {2, 3} or not all(part.isdigit() for part in parts):
        raise ScheduleConfigError(f"{field} must use HH:MM or HH:MM:SS")
    hour, minute = (int(part) for part in parts[:2])
    second = int(parts[2]) if len(parts) == 3 else 0
    if not 0 <= hour <= 23 or not 0 <= minute <= 59 or not 0 <= second <= 59:
        raise ScheduleConfigError(f"{field} is outside 00:00:00..23:59:59")
    return hour, minute, second


def _next_wall_time(
    local_now: datetime, hour: int, minute: int, second: int
) -> datetime:
    target = local_now.replace(
        hour=hour, minute=minute, second=second, microsecond=0, fold=0
    )
    if target <= local_now:
        target += timedelta(days=1)
    return target


def _next_interval_slot(local_now: datetime, interval: int) -> datetime:
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0, fold=0)
    elapsed = int((local_now - midnight).total_seconds())
    slot = elapsed // interval + 1
    target = midnight + timedelta(seconds=slot * interval)
    next_midnight = midnight + timedelta(days=1)
    return min(target, next_midnight)
