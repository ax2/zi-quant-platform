from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from app.trading_rules import check_a_share_order, estimate_a_share_fee


@dataclass(frozen=True)
class PaperPositionState:
    symbol: str
    shares: int
    avg_cost: float
    realized_pnl: float = 0.0


@dataclass(frozen=True)
class PaperAccountState:
    cash: float
    positions: dict[str, PaperPositionState] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperExecution:
    accepted: bool
    trade_date: date
    symbol: str
    side: str
    price: float
    requested_shares: int
    filled_shares: int
    amount: float
    fee: float
    reason: str
    account: PaperAccountState


def _position(account: PaperAccountState, symbol: str) -> PaperPositionState:
    return account.positions.get(symbol, PaperPositionState(symbol=symbol, shares=0, avg_cost=0.0))


def apply_paper_order(
    account: PaperAccountState,
    *,
    trade_date: date,
    symbol: str,
    side: str,
    price: float,
    shares: int,
) -> PaperExecution:
    position = _position(account, symbol)
    if side == "buy":
        check = check_a_share_order(side="buy", price=price, shares=shares, available_cash=account.cash)
        if not check.accepted:
            return PaperExecution(False, trade_date, symbol, side, price, shares, check.normalized_shares, check.amount, check.fee.total, check.reason or "rejected", account)
        total_cost = check.amount + check.fee.total
        new_shares = position.shares + check.normalized_shares
        avg_cost = round(((position.avg_cost * position.shares) + total_cost) / new_shares, 6) if new_shares else 0.0
        new_position = replace(position, shares=new_shares, avg_cost=avg_cost)
        new_positions = {**account.positions, symbol: new_position}
        new_account = PaperAccountState(cash=round(account.cash - total_cost, 2), positions=new_positions)
        return PaperExecution(True, trade_date, symbol, side, price, shares, check.normalized_shares, check.amount, check.fee.total, "filled", new_account)

    if side == "sell":
        check = check_a_share_order(side="sell", price=price, shares=shares, available_shares=position.shares)
        if not check.accepted:
            return PaperExecution(False, trade_date, symbol, side, price, shares, check.normalized_shares, check.amount, check.fee.total, check.reason or "rejected", account)
        fee = estimate_a_share_fee(check.amount, "sell")
        realized = round((price - position.avg_cost) * check.normalized_shares - fee.total, 2)
        remaining = position.shares - check.normalized_shares
        new_positions = dict(account.positions)
        if remaining > 0:
            new_positions[symbol] = replace(position, shares=remaining, realized_pnl=round(position.realized_pnl + realized, 2))
        else:
            new_positions.pop(symbol, None)
        new_account = PaperAccountState(cash=round(account.cash + check.amount - fee.total, 2), positions=new_positions)
        return PaperExecution(True, trade_date, symbol, side, price, shares, check.normalized_shares, check.amount, fee.total, "filled", new_account)

    return PaperExecution(False, trade_date, symbol, side, price, shares, 0, 0.0, 0.0, "invalid_side", account)


def account_market_value(account: PaperAccountState, last_prices: dict[str, float]) -> float:
    return round(sum(position.shares * float(last_prices.get(symbol, 0.0)) for symbol, position in account.positions.items()), 2)


def account_total_equity(account: PaperAccountState, last_prices: dict[str, float]) -> float:
    return round(account.cash + account_market_value(account, last_prices), 2)
