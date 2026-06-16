from datetime import date

from app.paper_ledger import PaperAccountState, PaperPositionState
from app.rebalance_plan import build_rebalance_plan


def test_rebalance_plan_builds_buy_and_sell_orders():
    account = PaperAccountState(
        cash=50000.0,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 1000, 10.0)},
    )

    plan = build_rebalance_plan(
        account,
        trade_date=date(2026, 1, 12),
        last_prices={"000001.SZ": 10.0, "600000.SH": 20.0},
        target_weights={"000001.SZ": 0.05, "600000.SH": 0.3},
    )

    assert plan.total_equity == 60000.0
    assert [(order.symbol, order.side, order.shares) for order in plan.orders] == [
        ("000001.SZ", "sell", 700),
        ("600000.SH", "buy", 900),
    ]


def test_rebalance_plan_skips_small_or_unpriced_changes():
    account = PaperAccountState(
        cash=90000.0,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 1000, 10.0)},
    )

    plan = build_rebalance_plan(
        account,
        trade_date=date(2026, 1, 12),
        last_prices={"000001.SZ": 10.0},
        target_weights={"000001.SZ": 0.105, "600000.SH": 0.1},
        min_trade_value=1000.0,
    )

    assert plan.orders == ()
