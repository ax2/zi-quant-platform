from datetime import date

from app.alert_messages import format_paper_daily_alert
from app.paper_ledger import PaperAccountState, PaperPositionState
from app.paper_risk import evaluate_paper_risk
from app.paper_snapshots import build_paper_account_snapshot
from app.rebalance_plan import build_rebalance_plan


def test_daily_alert_includes_snapshot_risk_and_rebalance_orders():
    account = PaperAccountState(
        cash=1000.0,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 3000, 10.0)},
    )
    snapshot = build_paper_account_snapshot(
        account,
        trade_date=date(2026, 1, 13),
        last_prices={"000001.SZ": 10.0, "600000.SH": 20.0},
    )
    risk_report = evaluate_paper_risk(snapshot, max_position_weight=0.4, min_cash_ratio=0.1, max_exposure_ratio=1.0)
    plan = build_rebalance_plan(
        account,
        trade_date=date(2026, 1, 13),
        last_prices={"000001.SZ": 10.0, "600000.SH": 20.0},
        target_weights={"000001.SZ": 0.4, "600000.SH": 0.2},
    )

    message = format_paper_daily_alert(snapshot, risk_report, plan)

    assert message.title == "ZiQuant 模拟盘日报 2026-01-13"
    assert message.severity == "blocker"
    assert "总权益：31000.00" in message.body
    assert "风控提示：" in message.body
    assert "sell 000001.SZ" in message.body
    assert "buy 600000.SH" in message.body


def test_daily_alert_handles_no_rebalance_orders():
    account = PaperAccountState(cash=10000.0)
    snapshot = build_paper_account_snapshot(account, trade_date=date(2026, 1, 13), last_prices={})
    risk_report = evaluate_paper_risk(snapshot)
    plan = build_rebalance_plan(account, trade_date=date(2026, 1, 13), last_prices={}, target_weights={})

    message = format_paper_daily_alert(snapshot, risk_report, plan)

    assert message.severity == "ok"
    assert "调仓建议：无需调仓" in message.body
