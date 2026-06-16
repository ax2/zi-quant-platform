from datetime import date

from app.paper_daily_cycle import run_paper_daily_cycle
from app.paper_ledger import PaperAccountState, PaperPositionState


def test_daily_cycle_composes_snapshot_risk_plan_alert_and_review():
    account = PaperAccountState(
        cash=50000.0,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 1000, 10.0)},
    )

    result = run_paper_daily_cycle(
        account,
        trade_date=date(2026, 1, 19),
        last_prices={"000001.SZ": 10.0, "600000.SH": 20.0},
        target_weights={"000001.SZ": 0.1, "600000.SH": 0.2},
        review_note="cycle ok",
    )

    assert result.snapshot.total_equity == 60000.0
    assert result.risk_report.severity == "ok"
    assert result.rebalance_plan.orders
    assert result.recommendation.action == "REBALANCE"
    assert result.alert_message.title == "ZiQuant 模拟盘日报 2026-01-19"
    assert result.review_record.note == "cycle ok"


def test_daily_cycle_prefers_risk_reduction_when_blocked():
    account = PaperAccountState(
        cash=1000.0,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 3000, 10.0)},
    )

    result = run_paper_daily_cycle(
        account,
        trade_date=date(2026, 1, 19),
        last_prices={"000001.SZ": 10.0},
        target_weights={"000001.SZ": 0.4},
    )

    assert result.risk_report.severity == "blocker"
    assert result.recommendation.action == "REDUCE_RISK"
    assert result.review_record.risk_severity == "blocker"
