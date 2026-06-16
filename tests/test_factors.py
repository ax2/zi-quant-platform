from datetime import date, timedelta

import pytest

from app.factors import build_factor_points, daily_returns, rolling_volatility, simple_moving_average
from app.market_data import CleanMarketBar


def _bars(closes: list[float]) -> list[CleanMarketBar]:
    start = date(2026, 1, 1)
    return [
        CleanMarketBar("600519.SH", start + timedelta(days=index), close, close, close, close, 10000, close * 10000, "fixture")
        for index, close in enumerate(closes)
    ]


def test_simple_moving_average_requires_positive_window_and_returns_none_until_ready():
    with pytest.raises(ValueError):
        simple_moving_average([1, 2, 3], 0)
    assert simple_moving_average([1, 2, 3, 4], 3) == [None, None, 2.0, 3.0]


def test_daily_returns_and_rolling_volatility():
    returns = daily_returns([10, 11, 10])
    assert returns == [None, 0.1, -0.090909]
    vol = rolling_volatility(returns, 2)
    assert vol[0] is None
    assert vol[1] is None
    assert vol[2] and vol[2] > 0


def test_build_factor_points_marks_insufficient_data_before_long_window():
    points = build_factor_points(_bars([10, 11, 12, 13]), short_window=2, long_window=3, volatility_window=2)
    assert points[0].signal == "insufficient_data"
    assert points[2].ma_long == 11.0
    assert points[-1].momentum == 0.3


def test_build_factor_points_generates_buy_watch_for_stable_uptrend():
    closes = [10 + index * 0.1 for index in range(40)]
    points = build_factor_points(_bars(closes), short_window=5, long_window=20, volatility_window=5)
    assert points[-1].signal == "buy_watch"
    assert points[-1].ma_short > points[-1].ma_long
    assert points[-1].momentum and points[-1].momentum > 0


def test_build_factor_points_generates_risk_watch_for_downtrend():
    closes = [20 - index * 0.2 for index in range(40)]
    points = build_factor_points(_bars(closes), short_window=5, long_window=20, volatility_window=5)
    assert points[-1].signal == "risk_watch"
    assert points[-1].momentum and points[-1].momentum < -0.08
