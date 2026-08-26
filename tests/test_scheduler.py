from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from arcaea_pull.core.scheduler import (
    ScheduleConfigError,
    seconds_until_next,
)


def test_default_interval_is_thirty_minutes():
    now = datetime(2026, 1, 1, 0, 0, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert seconds_until_next(now, "Asia/Shanghai") == 29 * 60 + 50


def test_interval_is_anchored_at_local_midnight():
    now = datetime(2026, 1, 1, 0, 0, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert (
        seconds_until_next(
            now,
            "Asia/Shanghai",
            interval_minutes=15,
        )
        == 14 * 60 + 50
    )


def test_interval_rolls_over_to_next_midnight():
    now = datetime(2026, 1, 1, 23, 59, 50, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert (
        seconds_until_next(
            now,
            "Asia/Shanghai",
            interval_minutes=15,
        )
        == 10
    )


def test_extra_time_can_run_before_next_interval_slot():
    now = datetime(2026, 1, 1, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert (
        seconds_until_next(
            now,
            "Asia/Shanghai",
            interval_minutes=360,
            extra_check_times=["10:05", "22:30:15"],
        )
        == 5 * 60
    )


def test_timezone_conversion_preserves_local_midnight_anchor():
    now = datetime(2025, 12, 31, 16, 0, 10, tzinfo=timezone.utc)
    assert seconds_until_next(now, "Asia/Shanghai", interval_minutes=30) == 1790


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"interval_minutes": 0}, "positive integer"),
        ({"interval_minutes": -1}, "positive integer"),
        ({"interval_minutes": "30"}, "positive integer"),
        ({"interval_minutes": 1.5}, "positive integer"),
        ({"interval_minutes": True}, "positive integer"),
        ({"interval_minutes": 1441}, "cannot exceed 24 hours"),
        ({"extra_check_times": ["25:00"]}, "extra_check_times item"),
    ],
)
def test_invalid_composite_schedule_is_rejected(kwargs, message):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ScheduleConfigError, match=message):
        seconds_until_next(now, "Asia/Shanghai", **kwargs)

