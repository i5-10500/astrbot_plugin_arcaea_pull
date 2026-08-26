"""Timezone-aware daily scheduling helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ScheduleConfigError(ValueError):
    """Daily schedule configuration is invalid."""


def parse_check_time(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ScheduleConfigError("check_time must use HH:MM")
    hour, minute = (int(part) for part in parts)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ScheduleConfigError("check_time is outside 00:00..23:59")
    return hour, minute


def seconds_until_next(now: datetime, check_time: str, timezone_name: str) -> float:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleConfigError(f"unknown timezone: {timezone_name}") from exc
    hour, minute = parse_check_time(check_time)
    local_now = now.astimezone(zone)
    target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local_now:
        target += timedelta(days=1)
    return max((target - local_now).total_seconds(), 0.0)

