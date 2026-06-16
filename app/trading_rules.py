from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


OrderSide = Literal["buy", "sell"]


@dataclass(frozen=True)
class AShareFeeBreakdown:
    commission: float
    transfer_fee: float
    stamp_tax: float
    total: float


@dataclass(frozen=True)
class AShareOrderCheck:
    accepted: bool
    normalized_shares: int
    amount: float
    fee: AShareFeeBreakdown
    reason: str | None = None


def normalize_a_share_lot(shares: int, lot_size: int = 100) -> int:
    if shares <= 0 or lot_size <= 0:
        return 0
    return shares // lot_size * lot_size


def estimate_a_share_fee(amount: float, side: OrderSide) -> AShareFeeBreakdown:
    if amount <= 0:
        return AShareFeeBreakdown(commission=0.0, transfer_fee=0.0, stamp_tax=0.0, total=0.0)
    commission = max(amount * 0.0003, 5.0)
    transfer_fee = amount * 0.00001
    stamp_tax = amount * 0.0005 if side == "sell" else 0.0
    total = commission + transfer_fee + stamp_tax
    return AShareFeeBreakdown(
        commission=round(commission, 2),
        transfer_fee=round(transfer_fee, 2),
        stamp_tax=round(stamp_tax, 2),
        total=round(total, 2),
    )


def check_a_share_order(
    *,
    side: OrderSide,
    price: float,
    shares: int,
    available_cash: float | None = None,
    available_shares: int | None = None,
    lot_size: int = 100,
) -> AShareOrderCheck:
    normalized = normalize_a_share_lot(shares, lot_size=lot_size)
    if price <= 0:
        return AShareOrderCheck(False, normalized, 0.0, estimate_a_share_fee(0, side), "invalid_price")
    if normalized <= 0:
        return AShareOrderCheck(False, 0, 0.0, estimate_a_share_fee(0, side), "lot_size_not_met")

    amount = round(price * normalized, 2)
    fee = estimate_a_share_fee(amount, side)
    if side == "buy" and available_cash is not None and amount + fee.total > available_cash:
        return AShareOrderCheck(False, normalized, amount, fee, "insufficient_cash")
    if side == "sell" and available_shares is not None and normalized > normalize_a_share_lot(available_shares, lot_size=lot_size):
        return AShareOrderCheck(False, normalized, amount, fee, "insufficient_position")
    return AShareOrderCheck(True, normalized, amount, fee)
