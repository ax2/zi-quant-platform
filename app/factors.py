from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from app.market_data import CleanMarketBar


@dataclass(frozen=True)
class FactorPoint:
    symbol: str
    trade_date: date
    close: float
    return_1d: float | None
    ma_short: float | None
    ma_long: float | None
    momentum: float | None
    volatility: float | None
    signal: str


def simple_moving_average(values: list[float], window: int) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")
    out: list[float | None] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        out.append(round(running / window, 6) if index + 1 >= window else None)
    return out


def daily_returns(values: list[float]) -> list[float | None]:
    out: list[float | None] = [None]
    for previous, current in zip(values, values[1:], strict=False):
        out.append(round(current / previous - 1, 6) if previous else None)
    return out


def rolling_volatility(returns: list[float | None], window: int) -> list[float | None]:
    if window <= 1:
        raise ValueError("window must be greater than 1")
    out: list[float | None] = []
    for index in range(len(returns)):
        sample = [value for value in returns[max(0, index - window + 1) : index + 1] if value is not None]
        if len(sample) < window:
            out.append(None)
            continue
        mean = sum(sample) / len(sample)
        variance = sum((value - mean) ** 2 for value in sample) / (len(sample) - 1)
        out.append(round(math.sqrt(variance * 252), 6))
    return out


def build_factor_points(
    bars: Iterable[CleanMarketBar],
    short_window: int = 5,
    long_window: int = 20,
    volatility_window: int = 20,
) -> list[FactorPoint]:
    ordered = sorted(bars, key=lambda item: item.trade_date)
    closes = [bar.close for bar in ordered]
    returns = daily_returns(closes)
    ma_short = simple_moving_average(closes, short_window)
    ma_long = simple_moving_average(closes, long_window)
    vol = rolling_volatility(returns, volatility_window)
    points: list[FactorPoint] = []
    for index, bar in enumerate(ordered):
        momentum = None
        signal = "insufficient_data"
        if index >= long_window and closes[index - long_window] > 0:
            momentum = round(closes[index] / closes[index - long_window] - 1, 6)
        if ma_short[index] is not None and ma_long[index] is not None and momentum is not None and vol[index] is not None:
            if ma_short[index] > ma_long[index] and momentum > 0 and vol[index] < 0.45:
                signal = "buy_watch"
            elif momentum < -0.08 or vol[index] >= 0.65:
                signal = "risk_watch"
            else:
                signal = "observe"
        points.append(
            FactorPoint(
                symbol=bar.symbol,
                trade_date=bar.trade_date,
                close=bar.close,
                return_1d=returns[index],
                ma_short=ma_short[index],
                ma_long=ma_long[index],
                momentum=momentum,
                volatility=vol[index],
                signal=signal,
            )
        )
    return points
