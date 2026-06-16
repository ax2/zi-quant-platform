from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterable

from app.market_data import CleanMarketBar
from app.mini_backtest import run_signal_backtest
from app.performance_metrics import PerformanceMetrics, compute_performance_metrics


@dataclass(frozen=True)
class ParameterCandidate:
    short_window: int
    long_window: int
    position_ratio: float


@dataclass(frozen=True)
class ParameterSearchResult:
    symbol: str
    params: ParameterCandidate
    final_equity: float
    metrics: PerformanceMetrics


def parameter_grid(
    short_windows: Iterable[int],
    long_windows: Iterable[int],
    position_ratios: Iterable[float],
) -> list[ParameterCandidate]:
    candidates: list[ParameterCandidate] = []
    for short_window, long_window, position_ratio in product(short_windows, long_windows, position_ratios):
        if short_window <= 1 or long_window <= short_window:
            continue
        if not 0 < position_ratio <= 1:
            continue
        candidates.append(ParameterCandidate(short_window, long_window, round(float(position_ratio), 4)))
    return candidates


def score_search_result(result: ParameterSearchResult) -> float:
    metrics = result.metrics
    drawdown_penalty = abs(metrics.max_drawdown) * 0.5
    turnover_penalty = max(0.0, metrics.turnover - 4.0) * 0.02
    trade_penalty = 0.01 if metrics.trade_count == 0 else 0.0
    return round(metrics.total_return - drawdown_penalty - turnover_penalty - trade_penalty, 6)


def run_parameter_search(
    symbol: str,
    bars: Iterable[CleanMarketBar],
    initial_cash: float = 100000.0,
    short_windows: Iterable[int] = (3, 5, 8),
    long_windows: Iterable[int] = (15, 20, 30),
    position_ratios: Iterable[float] = (0.5, 0.8),
    top_n: int = 5,
) -> list[ParameterSearchResult]:
    all_bars = list(bars)
    results: list[ParameterSearchResult] = []
    for params in parameter_grid(short_windows, long_windows, position_ratios):
        backtest = run_signal_backtest(
            symbol,
            all_bars,
            initial_cash=initial_cash,
            position_ratio=params.position_ratio,
            short_window=params.short_window,
            long_window=params.long_window,
        )
        metrics = compute_performance_metrics(backtest.equity_curve, backtest.trades, initial_cash, backtest.max_drawdown)
        results.append(ParameterSearchResult(symbol, params, backtest.final_equity, metrics))
    return sorted(results, key=lambda item: (score_search_result(item), item.metrics.total_return), reverse=True)[:top_n]


def search_result_payload(result: ParameterSearchResult) -> dict[str, object]:
    return {
        "symbol": result.symbol,
        "params": result.params.__dict__,
        "final_equity": result.final_equity,
        "score": score_search_result(result),
        "metrics": result.metrics.__dict__,
    }
