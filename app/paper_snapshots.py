from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.paper_ledger import PaperAccountState


@dataclass(frozen=True)
class PaperPositionSnapshot:
    symbol: str
    shares: int
    avg_cost: float
    last_price: float
    market_value: float
    cost_value: float
    unrealized_pnl: float
    weight: float


@dataclass(frozen=True)
class PaperAccountSnapshot:
    trade_date: date
    cash: float
    market_value: float
    total_equity: float
    cash_ratio: float
    positions: tuple[PaperPositionSnapshot, ...]


def build_paper_account_snapshot(
    account: PaperAccountState,
    *,
    trade_date: date,
    last_prices: dict[str, float],
) -> PaperAccountSnapshot:
    rows: list[PaperPositionSnapshot] = []
    market_value = 0.0
    for symbol, position in sorted(account.positions.items()):
        last_price = float(last_prices.get(symbol, 0.0))
        value = round(position.shares * last_price, 2)
        cost_value = round(position.shares * position.avg_cost, 2)
        rows.append(
            PaperPositionSnapshot(
                symbol=symbol,
                shares=position.shares,
                avg_cost=position.avg_cost,
                last_price=last_price,
                market_value=value,
                cost_value=cost_value,
                unrealized_pnl=round(value - cost_value, 2),
                weight=0.0,
            )
        )
        market_value += value

    total_equity = round(account.cash + market_value, 2)
    positions = tuple(
        PaperPositionSnapshot(
            symbol=row.symbol,
            shares=row.shares,
            avg_cost=row.avg_cost,
            last_price=row.last_price,
            market_value=row.market_value,
            cost_value=row.cost_value,
            unrealized_pnl=row.unrealized_pnl,
            weight=round(row.market_value / total_equity, 6) if total_equity else 0.0,
        )
        for row in rows
    )
    return PaperAccountSnapshot(
        trade_date=trade_date,
        cash=round(account.cash, 2),
        market_value=round(market_value, 2),
        total_equity=total_equity,
        cash_ratio=round(account.cash / total_equity, 6) if total_equity else 0.0,
        positions=positions,
    )
