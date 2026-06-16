from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.alert_messages import PaperAlertMessage, format_paper_daily_alert
from app.paper_ledger import PaperAccountState
from app.paper_review import PaperReviewRecord, create_paper_review_record
from app.paper_risk import PaperRiskReport, evaluate_paper_risk
from app.paper_snapshots import PaperAccountSnapshot, build_paper_account_snapshot
from app.rebalance_plan import RebalancePlan, build_rebalance_plan
from app.recommendations import PaperRecommendation, build_paper_recommendation


@dataclass(frozen=True)
class PaperDailyCycleResult:
    snapshot: PaperAccountSnapshot
    risk_report: PaperRiskReport
    rebalance_plan: RebalancePlan
    recommendation: PaperRecommendation
    alert_message: PaperAlertMessage
    review_record: PaperReviewRecord


def run_paper_daily_cycle(
    account: PaperAccountState,
    *,
    trade_date: date,
    last_prices: dict[str, float],
    target_weights: dict[str, float],
    review_note: str = "",
) -> PaperDailyCycleResult:
    snapshot = build_paper_account_snapshot(account, trade_date=trade_date, last_prices=last_prices)
    risk_report = evaluate_paper_risk(snapshot)
    rebalance_plan = build_rebalance_plan(
        account,
        trade_date=trade_date,
        last_prices=last_prices,
        target_weights=target_weights,
    )
    recommendation = build_paper_recommendation(snapshot, risk_report, rebalance_plan)
    alert_message = format_paper_daily_alert(snapshot, risk_report, rebalance_plan)
    review_record = create_paper_review_record(snapshot, risk_report, recommendation, note=review_note)
    return PaperDailyCycleResult(
        snapshot=snapshot,
        risk_report=risk_report,
        rebalance_plan=rebalance_plan,
        recommendation=recommendation,
        alert_message=alert_message,
        review_record=review_record,
    )
