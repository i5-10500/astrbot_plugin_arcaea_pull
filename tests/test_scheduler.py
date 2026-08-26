from datetime import datetime, timezone

import pytest

from arcaea_pull.core.scheduler import (
    ScheduleConfigError,
    parse_check_time,
    seconds_until_next,
)


def test_parse_time():
    assert parse_check_time("04:05") == (4, 5)
    with pytest.raises(ScheduleConfigError):
        parse_check_time("25:00")


def test_seconds_until_next_respects_timezone_and_next_day():
    now = datetime(2026, 1, 1, 20, 30, tzinfo=timezone.utc)  # 04:30 next day in Shanghai
    assert seconds_until_next(now, "04:00", "Asia/Shanghai") == 23.5 * 3600

