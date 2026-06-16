from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.price_providers import PriceSnapshot


@dataclass(frozen=True)
class DataGap:
    symbol: str
    trade_date: date
    field: str
    severity: str


@dataclass(frozen=True)
class DataGapPlan:
    gaps: tuple[DataGap, ...]
    severity: str


def build_price_gap_plan(price_snapshot: PriceSnapshot, *, required_symbols: list[str]) -> DataGapPlan:
    required = list(dict.fromkeys(required_symbols))
    missing = sorted(set(required) - set(price_snapshot.prices))
    gaps = tuple(
        DataGap(symbol=symbol, trade_date=price_snapshot.trade_date, field="last_price", severity="blocker")
        for symbol in missing
    )
    return DataGapPlan(gaps=gaps, severity="blocker" if gaps else "ok")


def gap_symbols(plan: DataGapPlan) -> list[str]:
    return [gap.symbol for gap in plan.gaps]
