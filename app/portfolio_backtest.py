from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from app.market_data import CleanMarketBar
from app.mini_backtest import MiniBacktestResult, run_signal_backtest


@dataclass(frozen=True)
class PortfolioBacktestResult:
    initial_cash: float
    final_equity: float
    total_return: float
    max_drawdown: float
    symbol_results: tuple[MiniBacktestResult, ...]
    equity_curve: tuple[dict[str, object], ...]


def _sum_equity_by_date(results: Iterable[MiniBacktestResult]) -> list[dict[str, object]]:
    by_date: dict[str, float] = {}
    for result in results:
        for row in result.equity_curve:
            trade_date = str(row["trade_date"])
            by_date[trade_date] = by_date.get(trade_date, 0.0) + float(row["equity"])
    return [{"trade_date": trade_date, "equity": round(equity, 2)} for trade_date, equity in sorted(by_date.items())]


def _max_drawdown(values: list[float]) -> float:
    peak = None
    worst = 0.0
    for value in values:
        peak = value if peak is None else max(peak, value)
        if peak:
            worst = min(worst, value / peak - 1)
    return round(worst, 6)


def run_equal_weight_portfolio_backtest(
    symbols: list[str],
    bars: Iterable[CleanMarketBar],
    initial_cash: float = 100000.0,
    max_symbols: int | None = None,
    position_ratio: float = 0.8,
) -> PortfolioBacktestResult:
    selected = list(dict.fromkeys(symbols))
    if max_symbols is not None:
        selected = selected[:max_symbols]
    if not selected:
        return PortfolioBacktestResult(initial_cash, initial_cash, 0.0, 0.0, (), ())

    all_bars = list(bars)
    cash_per_symbol = initial_cash / len(selected)
    results = tuple(
        run_signal_backtest(
            symbol,
            all_bars,
            initial_cash=cash_per_symbol,
            position_ratio=position_ratio,
        )
        for symbol in selected
    )
    final_equity = round(sum(result.final_equity for result in results), 2)
    curve = tuple(_sum_equity_by_date(results))
    total_return = round(final_equity / initial_cash - 1, 6) if initial_cash else 0.0
    max_drawdown = _max_drawdown([float(row["equity"]) for row in curve])
    return PortfolioBacktestResult(initial_cash, final_equity, total_return, max_drawdown, results, curve)


def portfolio_trade_summary(result: PortfolioBacktestResult) -> dict[str, object]:
    buy_count = 0
    sell_count = 0
    traded_symbols: set[str] = set()
    for symbol_result in result.symbol_results:
        for trade in symbol_result.trades:
            if trade.side == "buy":
                buy_count += 1
            elif trade.side == "sell":
                sell_count += 1
            traded_symbols.add(symbol_result.symbol)
    return {
        "symbols": len(result.symbol_results),
        "traded_symbols": len(traded_symbols),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "trade_count": buy_count + sell_count,
    }


def clip_bars_by_date(bars: Iterable[CleanMarketBar], start: date | None = None, end: date | None = None) -> list[CleanMarketBar]:
    out: list[CleanMarketBar] = []
    for bar in bars:
        if start and bar.trade_date < start:
            continue
        if end and bar.trade_date > end:
            continue
        out.append(bar)
    return sorted(out, key=lambda item: (item.symbol, item.trade_date))
