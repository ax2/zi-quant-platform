from datetime import date, timedelta

from app.market_data import CleanMarketBar
from app.mini_backtest import run_signal_backtest


def _bars(symbol: str, closes: list[float]) -> list[CleanMarketBar]:
    start = date(2026, 1, 1)
    return [
        CleanMarketBar(symbol, start + timedelta(days=index), close, close, close, close, 100000, close * 100000, "fixture")
        for index, close in enumerate(closes)
    ]


def test_run_signal_backtest_returns_flat_result_without_data():
    result = run_signal_backtest("600519.SH", [], initial_cash=100000)
    assert result.final_equity == 100000
    assert result.trades == ()
    assert result.equity_curve == ()


def test_run_signal_backtest_buys_stable_uptrend_with_lot_size_and_fees():
    closes = [10 + index * 0.1 for index in range(40)]
    result = run_signal_backtest("600519.SH", _bars("600519.SH", closes), initial_cash=100000, position_ratio=0.5, short_window=5, long_window=20)
    assert result.trades
    assert result.trades[0].side == "buy"
    assert result.trades[0].shares % 100 == 0
    assert result.cash < 100000
    assert result.final_equity > result.initial_cash
    assert result.total_return > 0


def test_run_signal_backtest_sells_when_later_risk_watch_appears():
    up = [10 + index * 0.15 for index in range(35)]
    down = [up[-1] - index * 0.4 for index in range(1, 25)]
    result = run_signal_backtest("000001.SZ", _bars("000001.SZ", up + down), initial_cash=100000, position_ratio=0.8, short_window=5, long_window=20)
    assert [trade.side for trade in result.trades] == ["buy", "sell"]
    assert result.shares == 0
    assert result.equity_curve[-1]["shares"] == 0
    assert result.max_drawdown <= 0


def test_run_signal_backtest_ignores_other_symbols():
    bars = _bars("600519.SH", [10 + index * 0.1 for index in range(40)])
    result = run_signal_backtest("300750.SZ", bars, initial_cash=50000)
    assert result.final_equity == 50000
    assert result.trades == ()
