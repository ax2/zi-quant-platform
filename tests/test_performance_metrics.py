from datetime import date

from app.mini_backtest import MiniBacktestTrade
from app.performance_metrics import annualized_return, annualized_volatility, compute_performance_metrics, equity_returns, profit_loss_ratio, trade_pnls, win_rate


def test_equity_returns_and_annualized_helpers():
    curve = [{"equity": 100}, {"equity": 110}, {"equity": 99}]
    returns = equity_returns(curve)
    assert returns == [0.1, -0.1]
    assert annualized_return(0.1, 252) == 0.1
    assert annualized_volatility(returns) > 0


def test_trade_pnls_pair_buy_sell_trades():
    trades = [
        MiniBacktestTrade(date(2026, 1, 1), "buy", 10, 1000, 10000, 5, "entry"),
        MiniBacktestTrade(date(2026, 1, 2), "sell", 11, 1000, 11000, 6, "exit"),
        MiniBacktestTrade(date(2026, 1, 3), "buy", 12, 1000, 12000, 5, "entry"),
    ]
    assert trade_pnls(trades) == [989]
    assert win_rate([989, -100]) == 0.5
    assert profit_loss_ratio([200, -100, 100, -50]) == 2.0
    assert profit_loss_ratio([200]) is None


def test_compute_performance_metrics_handles_curve_and_trades():
    curve = [{"equity": 100000}, {"equity": 101000}, {"equity": 102000}]
    trades = [
        MiniBacktestTrade(date(2026, 1, 1), "buy", 10, 1000, 10000, 5, "entry"),
        MiniBacktestTrade(date(2026, 1, 2), "sell", 11, 1000, 11000, 6, "exit"),
    ]
    metrics = compute_performance_metrics(curve, trades, initial_cash=100000, max_drawdown=-0.01)
    assert metrics.total_return == 0.02
    assert metrics.trade_count == 2
    assert metrics.turnover == 0.21
    assert metrics.win_rate == 1.0
    assert metrics.max_drawdown == -0.01


def test_compute_performance_metrics_handles_empty_curve():
    metrics = compute_performance_metrics([], [], initial_cash=100000, max_drawdown=0)
    assert metrics.total_return == 0
    assert metrics.annualized_volatility == 0
    assert metrics.sharpe_like is None
    assert metrics.win_rate is None
