from datetime import datetime, time, timezone

from app.run_window import RunWindow, evaluate_run_window, is_within_run_window


def test_run_window_allows_time_inside_same_day_window():
    window = RunWindow(start=time(15, 10), end=time(15, 40))

    assert is_within_run_window(datetime(2026, 1, 27, 15, 20, tzinfo=timezone.utc), window) is True


def test_run_window_rejects_time_outside_and_returns_next_start():
    window = RunWindow(start=time(15, 10), end=time(15, 40))

    status = evaluate_run_window(datetime(2026, 1, 27, 16, 0, tzinfo=timezone.utc), window)

    assert status.allowed is False
    assert status.reason == "outside_window"
    assert status.next_run_at == datetime(2026, 1, 28, 15, 10, tzinfo=timezone.utc)


def test_run_window_supports_overnight_window():
    window = RunWindow(start=time(23, 0), end=time(1, 0))

    assert is_within_run_window(datetime(2026, 1, 27, 23, 30), window) is True
    assert is_within_run_window(datetime(2026, 1, 28, 0, 30), window) is True
    assert is_within_run_window(datetime(2026, 1, 28, 2, 0), window) is False
