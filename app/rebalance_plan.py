from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.paper_ledger import PaperAccountState
from app.paper_snapshots import build_paper_account_snapshot


@dataclass(frozen=True)
class RebalanceOrderPlan:
    symbol: str
    side: str
    shares: int
    price: float
    target_weight: float
    current_weight: float
    delta_value: float


@dataclass(frozen=True)
class RebalancePlan:
    trade_date: date
    total_equity: float
    orders: tuple[RebalanceOrderPlan, ...]


def _lot_shares(raw_shares: float) -> int:
    lots = int(abs(raw_shares) // 100)
    return lots * 100


def build_rebalance_plan(
    account: PaperAccountState,
    *,
    trade_date: date,
    last_prices: dict[str, float],
    target_weights: dict[str, float],
    min_trade_value: float = 1000.0,
) -> RebalancePlan:
    snapshot = build_paper_account_snapshot(account, trade_date=trade_date, last_prices=last_prices)
    current_weights = {position.symbol: position.weight for position in snapshot.positions}
    symbols = sorted(set(current_weights) | set(target_weights))
    orders: list[RebalanceOrderPlan] = []

    for symbol in symbols:
        price = float(last_prices.get(symbol, 0.0))
        if price <= 0:
            continue
        target_weight = float(target_weights.get(symbol, 0.0))
        current_weight = float(current_weights.get(symbol, 0.0))
        delta_value = round((target_weight - current_weight) * snapshot.total_equity, 2)
        if abs(delta_value) < min_trade_value:
            continue
        shares = _lot_shares(delta_value / price)
        if shares <= 0:
            continue
        orders.append(
            RebalanceOrderPlan(
                symbol=symbol,
                side="buy" if delta_value > 0 else "sell",
                shares=shares,
                price=price,
                target_weight=round(target_weight, 6),
                current_weight=round(current_weight, 6),
                delta_value=delta_value,
            )
        )

    return RebalancePlan(trade_date=trade_date, total_equity=snapshot.total_equity, orders=tuple(orders))
