from datetime import date, timedelta

from app.market_data import CleanMarketBar
from app.portfolio_backtest import clip_bars_by_date, portfolio_trade_summary, run_equal_weight_portfolio_backtest


def _bars(symbol: str, closes: list[float]) -> list[CleanMarketBar]:
    start = date(2026, 1, 1)
    return [
        CleanMarketBar(symbol, start + timedelta(days=index), close, close, close, close, 100000, close * 100000, "fixture")
        for index, close in enumerate(closes)
    ]


def test_equal_weight_portfolio_backtest_splits_cash_and_aggregates_equity():
    bars = _bars("600519.SH", [10 + index * 0.1 for index in range(40)]) + _bars("000001.SZ", [20 + index * 0.05 for index in range(40)])
    result = run_equal_weight_portfolio_backtest(["600519.SH", "000001.SZ"], bars, initial_cash=100000)
    assert len(result.symbol_results) == 2
    assert result.symbol_results[0].initial_cash == 50000
    assert result.final_equity > 100000
    assert result.total_return > 0
    assert result.equity_curve[-1]["equity"] == result.final_equity


def test_equal_weight_portfolio_backtest_deduplicates_and_limits_symbols():
    bars = _bars("600519.SH", [10 + index * 0.1 for index in range(40)]) + _bars("000001.SZ", [20 + index * 0.05 for index in range(40)])
    result = run_equal_weight_portfolio_backtest(["600519.SH", "600519.SH", "000001.SZ"], bars, initial_cash=90000, max_symbols=1)
    assert len(result.symbol_results) == 1
    assert result.symbol_results[0].symbol == "600519.SH"
    assert result.symbol_results[0].initial_cash == 90000


def test_portfolio_trade_summary_counts_side_and_symbols():
    bars = _bars("600519.SH", [10 + index * 0.1 for index in range(40)])
    result = run_equal_weight_portfolio_backtest(["600519.SH"], bars, initial_cash=100000)
    summary = portfolio_trade_summary(result)
    assert summary["symbols"] == 1
    assert summary["traded_symbols"] == 1
    assert summary["buy_count"] == 1
    assert summary["trade_count"] == 1


def test_clip_bars_by_date_filters_inclusive_range():
    bars = _bars("600519.SH", [10, 11, 12, 13])
    clipped = clip_bars_by_date(bars, start=date(2026, 1, 2), end=date(2026, 1, 3))
    assert [bar.trade_date for bar in clipped] == [date(2026, 1, 2), date(2026, 1, 3)]
