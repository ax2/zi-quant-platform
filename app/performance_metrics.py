from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from app.mini_backtest import MiniBacktestTrade


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_like: float | None
    max_drawdown: float
    win_rate: float | None
    profit_loss_ratio: float | None
    trade_count: int
    turnover: float


def equity_returns(equity_curve: Iterable[dict[str, object]]) -> list[float]:
    values = [float(row["equity"]) for row in equity_curve]
    out: list[float] = []
    for previous, current in zip(values, values[1:], strict=False):
        if previous:
            out.append(round(current / previous - 1, 8))
    return out


def annualized_return(total_return: float, trading_days: int) -> float:
    if trading_days <= 0:
        return 0.0
    return round((1 + total_return) ** (252 / trading_days) - 1, 6)


def annualized_volatility(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return round(math.sqrt(variance * 252), 6)


def trade_pnls(trades: Iterable[MiniBacktestTrade]) -> list[float]:
    pnls: list[float] = []
    open_cost: float | None = None
    for trade in trades:
        if trade.side == "buy":
            open_cost = trade.amount + trade.fee
        elif trade.side == "sell" and open_cost is not None:
            pnls.append(round(trade.amount - trade.fee - open_cost, 2))
            open_cost = None
    return pnls


def win_rate(pnls: list[float]) -> float | None:
    if not pnls:
        return None
    return round(sum(1 for value in pnls if value > 0) / len(pnls), 6)


def profit_loss_ratio(pnls: list[float]) -> float | None:
    wins = [value for value in pnls if value > 0]
    losses = [-value for value in pnls if value < 0]
    if not wins or not losses:
        return None
    return round((sum(wins) / len(wins)) / (sum(losses) / len(losses)), 6)


def compute_performance_metrics(
    equity_curve: Iterable[dict[str, object]],
    trades: Iterable[MiniBacktestTrade],
    initial_cash: float,
    max_drawdown: float,
) -> PerformanceMetrics:
    curve = list(equity_curve)
    final_equity = float(curve[-1]["equity"]) if curve else initial_cash
    total_return = round(final_equity / initial_cash - 1, 6) if initial_cash else 0.0
    returns = equity_returns(curve)
    ann_return = annualized_return(total_return, len(curve))
    ann_vol = annualized_volatility(returns)
    sharpe = round(ann_return / ann_vol, 6) if ann_vol else None
    trade_list = list(trades)
    pnls = trade_pnls(trade_list)
    traded_amount = sum(trade.amount for trade in trade_list)
    turnover = round(traded_amount / initial_cash, 6) if initial_cash else 0.0
    return PerformanceMetrics(
        total_return=total_return,
        annualized_return=ann_return,
        annualized_volatility=ann_vol,
        sharpe_like=sharpe,
        max_drawdown=max_drawdown,
        win_rate=win_rate(pnls),
        profit_loss_ratio=profit_loss_ratio(pnls),
        trade_count=len(trade_list),
        turnover=turnover,
    )
