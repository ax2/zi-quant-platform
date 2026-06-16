from __future__ import annotations

from datetime import UTC, datetime

from scripts.run_due_jobs import _next_sleep_seconds, _parse_now


def test_parse_now_normalizes_to_utc():
    parsed = _parse_now("2026-06-11T16:00:00+08:00")
    assert parsed == datetime(2026, 6, 11, 8, 0, tzinfo=UTC)

    naive = _parse_now("2026-06-11T16:00:00")
    assert naive == datetime(2026, 6, 11, 16, 0, tzinfo=UTC)


def test_next_sleep_seconds_aligns_to_polling_interval():
    assert _next_sleep_seconds(datetime(2026, 6, 11, 16, 0, 30, tzinfo=UTC), 60) == 30.0
    assert _next_sleep_seconds(datetime(2026, 6, 11, 16, 0, 59, tzinfo=UTC), 60) == 1.0
    assert _next_sleep_seconds(datetime(2026, 6, 11, 16, 0, 0, tzinfo=UTC), 60) == 60.0
    assert _next_sleep_seconds(datetime(2026, 6, 11, 16, 0, 14, tzinfo=UTC), 15) == 1.0
    assert _next_sleep_seconds(datetime(2026, 6, 11, 16, 0, 14, tzinfo=UTC), 0) == 1.0
