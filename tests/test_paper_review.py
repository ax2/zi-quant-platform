from datetime import date

from app.paper_ledger import PaperAccountState, PaperPositionState
from app.paper_review import create_paper_review_record, summarize_paper_reviews
from app.paper_risk import evaluate_paper_risk
from app.paper_snapshots import build_paper_account_snapshot
from app.rebalance_plan import build_rebalance_plan
from app.recommendations import build_paper_recommendation


def _record(trade_date: date, cash: float, price: float):
    account = PaperAccountState(
        cash=cash,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 1000, 10.0)},
    )
    snapshot = build_paper_account_snapshot(account, trade_date=trade_date, last_prices={"000001.SZ": price})
    risk = evaluate_paper_risk(snapshot, max_position_weight=0.7, max_exposure_ratio=1.0)
    plan = build_rebalance_plan(
        account,
        trade_date=trade_date,
        last_prices={"000001.SZ": price},
        target_weights={"000001.SZ": 0.4},
    )
    recommendation = build_paper_recommendation(snapshot, risk, plan)
    return create_paper_review_record(snapshot, risk, recommendation, note="daily review")


def test_create_review_record_from_runtime_outputs():
    record = _record(date(2026, 1, 15), cash=10000.0, price=10.0)

    assert record.trade_date == date(2026, 1, 15)
    assert record.total_equity == 20000.0
    assert record.recommendation_action == "REBALANCE"
    assert record.note == "daily review"


def test_summarize_reviews_sorts_and_counts_actions():
    older = _record(date(2026, 1, 15), cash=10000.0, price=10.0)
    newer = _record(date(2026, 1, 16), cash=9000.0, price=12.0)

    summary = summarize_paper_reviews([newer, older])

    assert [item.trade_date for item in summary.records] == [date(2026, 1, 15), date(2026, 1, 16)]
    assert summary.latest_equity == 21000.0
    assert summary.equity_change == 1000.0
    assert summary.action_counts == {"REBALANCE": 2}


def test_summarize_empty_reviews():
    summary = summarize_paper_reviews([])

    assert summary.latest_equity == 0.0
    assert summary.action_counts == {}
