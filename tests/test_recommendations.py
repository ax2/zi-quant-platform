from datetime import date

from app.paper_ledger import PaperAccountState, PaperPositionState
from app.paper_risk import evaluate_paper_risk
from app.paper_snapshots import build_paper_account_snapshot
from app.rebalance_plan import build_rebalance_plan
from app.recommendations import build_paper_recommendation


def test_recommendation_reduces_risk_when_blocked():
    account = PaperAccountState(
        cash=1000.0,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 3000, 10.0)},
    )
    snapshot = build_paper_account_snapshot(
        account,
        trade_date=date(2026, 1, 14),
        last_prices={"000001.SZ": 10.0},
    )
    risk = evaluate_paper_risk(snapshot, max_position_weight=0.4, max_exposure_ratio=1.0)
    plan = build_rebalance_plan(
        account,
        trade_date=date(2026, 1, 14),
        last_prices={"000001.SZ": 10.0},
        target_weights={"000001.SZ": 0.4},
    )

    recommendation = build_paper_recommendation(snapshot, risk, plan)

    assert recommendation.action == "REDUCE_RISK"
    assert recommendation.severity == "blocker"
    assert "position_too_large" in recommendation.reasons


def test_recommendation_rebalances_when_orders_are_ready():
    account = PaperAccountState(
        cash=50000.0,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 1000, 10.0)},
    )
    snapshot = build_paper_account_snapshot(
        account,
        trade_date=date(2026, 1, 14),
        last_prices={"000001.SZ": 10.0, "600000.SH": 20.0},
    )
    risk = evaluate_paper_risk(snapshot)
    plan = build_rebalance_plan(
        account,
        trade_date=date(2026, 1, 14),
        last_prices={"000001.SZ": 10.0, "600000.SH": 20.0},
        target_weights={"000001.SZ": 0.1, "600000.SH": 0.2},
    )

    recommendation = build_paper_recommendation(snapshot, risk, plan)

    assert recommendation.action == "REBALANCE"
    assert recommendation.order_count == 2
    assert "rebalance_orders_ready" in recommendation.reasons


def test_recommendation_holds_empty_account():
    account = PaperAccountState(cash=10000.0)
    snapshot = build_paper_account_snapshot(account, trade_date=date(2026, 1, 14), last_prices={})
    risk = evaluate_paper_risk(snapshot)
    plan = build_rebalance_plan(account, trade_date=date(2026, 1, 14), last_prices={}, target_weights={})

    recommendation = build_paper_recommendation(snapshot, risk, plan)

    assert recommendation.action == "HOLD"
    assert recommendation.reasons == ("empty_portfolio",)
