from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from app.paper_risk import PaperRiskReport
from app.paper_snapshots import PaperAccountSnapshot
from app.recommendations import PaperRecommendation


@dataclass(frozen=True)
class PaperReviewRecord:
    trade_date: date
    total_equity: float
    cash_ratio: float
    risk_severity: str
    recommendation_action: str
    note: str


@dataclass(frozen=True)
class PaperReviewSummary:
    records: tuple[PaperReviewRecord, ...]
    latest_equity: float
    equity_change: float
    blocker_days: int
    action_counts: dict[str, int]


def create_paper_review_record(
    snapshot: PaperAccountSnapshot,
    risk_report: PaperRiskReport,
    recommendation: PaperRecommendation,
    *,
    note: str = "",
) -> PaperReviewRecord:
    return PaperReviewRecord(
        trade_date=snapshot.trade_date,
        total_equity=snapshot.total_equity,
        cash_ratio=snapshot.cash_ratio,
        risk_severity=risk_report.severity,
        recommendation_action=recommendation.action,
        note=note,
    )


def summarize_paper_reviews(records: Iterable[PaperReviewRecord]) -> PaperReviewSummary:
    ordered = tuple(sorted(records, key=lambda item: item.trade_date))
    if not ordered:
        return PaperReviewSummary((), 0.0, 0.0, 0, {})

    action_counts: dict[str, int] = {}
    blocker_days = 0
    for record in ordered:
        action_counts[record.recommendation_action] = action_counts.get(record.recommendation_action, 0) + 1
        if record.risk_severity == "blocker":
            blocker_days += 1

    return PaperReviewSummary(
        records=ordered,
        latest_equity=ordered[-1].total_equity,
        equity_change=round(ordered[-1].total_equity - ordered[0].total_equity, 2),
        blocker_days=blocker_days,
        action_counts=action_counts,
    )
