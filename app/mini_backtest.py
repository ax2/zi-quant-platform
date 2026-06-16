from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from app.factors import build_factor_points
from app.market_data import CleanMarketBar
from app.trading_rules import check_a_share_order, estimate_a_share_fee


@dataclass(frozen=True)
class MiniBacktestTrade:
    trade_date: date
    side: str
    price: float
    shares: int
    amount: float
    fee: float
    reason: str


@dataclass(frozen=True)
class MiniBacktestResult:
    symbol: str
    initial_cash: float
    final_equity: float
    cash: float
    shares: int
    total_return: float
    max_drawdown: float
    trades: tuple[MiniBacktestTrade, ...] = field(default_factory=tuple)
    equity_curve: tuple[dict[str, object], ...] = field(default_factory=tuple)


def _max_drawdown(equity_values: list[float]) -> float:
    peak = None
    worst = 0.0
    for value in equity_values:
        peak = value if peak is None else max(peak, value)
        if peak:
            worst = min(worst, value / peak - 1)
    return round(worst, 6)


def run_signal_backtest(
    symbol: str,
    bars: Iterable[CleanMarketBar],
    initial_cash: float = 100000.0,
    position_ratio: float = 0.8,
    short_window: int = 5,
    long_window: int = 20,
) -> MiniBacktestResult:
    ordered = sorted([bar for bar in bars if bar.symbol == symbol], key=lambda item: item.trade_date)
    if not ordered:
        return MiniBacktestResult(symbol, initial_cash, initial_cash, initial_cash, 0, 0.0, 0.0)

    factors = build_factor_points(ordered, short_window=short_window, long_window=long_window, volatility_window=max(short_window, 2))
    cash = float(initial_cash)
    shares = 0
    trades: list[MiniBacktestTrade] = []
    equity_curve: list[dict[str, object]] = []

    for bar, factor in zip(ordered, factors, strict=True):
        if factor.signal == "buy_watch" and shares == 0:
            target_cash = cash * position_ratio
            raw_shares = int(target_cash // bar.close)
            check = check_a_share_order(side="buy", price=bar.close, shares=raw_shares, available_cash=cash)
            if check.accepted:
                cash = round(cash - check.amount - check.fee.total, 2)
                shares += check.normalized_shares
                trades.append(MiniBacktestTrade(bar.trade_date, "buy", bar.close, check.normalized_shares, check.amount, check.fee.total, "buy_watch"))
        elif factor.signal == "risk_watch" and shares > 0:
            fee = estimate_a_share_fee(round(bar.close * shares, 2), "sell")
            amount = round(bar.close * shares, 2)
            cash = round(cash + amount - fee.total, 2)
            trades.append(MiniBacktestTrade(bar.trade_date, "sell", bar.close, shares, amount, fee.total, "risk_watch"))
            shares = 0

        equity = round(cash + shares * bar.close, 2)
        equity_curve.append({"trade_date": bar.trade_date.isoformat(), "cash": cash, "shares": shares, "equity": equity, "signal": factor.signal})

    final_price = ordered[-1].close
    final_equity = round(cash + shares * final_price, 2)
    total_return = round(final_equity / initial_cash - 1, 6) if initial_cash else 0.0
    max_drawdown = _max_drawdown([float(row["equity"]) for row in equity_curve])
    return MiniBacktestResult(
        symbol=symbol,
        initial_cash=initial_cash,
        final_equity=final_equity,
        cash=cash,
        shares=shares,
        total_return=total_return,
        max_drawdown=max_drawdown,
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
    )
