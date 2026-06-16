from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class PriceSnapshot:
    trade_date: date
    prices: dict[str, float]
    missing_symbols: tuple[str, ...]


class PriceProvider(Protocol):
    def get_last_prices(self, symbols: list[str], *, trade_date: date) -> PriceSnapshot:
        ...


@dataclass(frozen=True)
class StaticPriceProvider:
    prices: dict[str, float]

    def get_last_prices(self, symbols: list[str], *, trade_date: date) -> PriceSnapshot:
        unique_symbols = list(dict.fromkeys(symbols))
        found: dict[str, float] = {}
        missing: list[str] = []
        for symbol in unique_symbols:
            if symbol in self.prices:
                found[symbol] = float(self.prices[symbol])
            else:
                missing.append(symbol)
        return PriceSnapshot(trade_date=trade_date, prices=found, missing_symbols=tuple(missing))


def collect_required_price_symbols(position_symbols: list[str], target_weights: dict[str, float]) -> list[str]:
    return sorted(set(position_symbols) | set(target_weights))
