from __future__ import annotations

from dataclasses import dataclass

from app.paper_risk import PaperRiskReport
from app.paper_snapshots import PaperAccountSnapshot
from app.rebalance_plan import RebalancePlan


@dataclass(frozen=True)
class PaperRecommendation:
    action: str
    severity: str
    summary: str
    reasons: tuple[str, ...]
    order_count: int


def build_paper_recommendation(
    snapshot: PaperAccountSnapshot,
    risk_report: PaperRiskReport,
    rebalance_plan: RebalancePlan,
) -> PaperRecommendation:
    reasons: list[str] = []
    if risk_report.violations:
        reasons.extend(violation.code for violation in risk_report.violations)
    if rebalance_plan.orders:
        reasons.append("rebalance_orders_ready")
    if snapshot.positions:
        top_position = max(snapshot.positions, key=lambda item: item.weight)
        reasons.append(f"top_position:{top_position.symbol}:{top_position.weight:.2%}")
    else:
        reasons.append("empty_portfolio")

    if risk_report.severity == "blocker":
        action = "REDUCE_RISK"
        summary = "模拟盘存在阻断级风险，优先处理风控问题"
    elif rebalance_plan.orders:
        action = "REBALANCE"
        summary = "模拟盘可按计划检查调仓建议"
    else:
        action = "HOLD"
        summary = "模拟盘暂无必要动作，继续观察"

    return PaperRecommendation(
        action=action,
        severity=risk_report.severity,
        summary=summary,
        reasons=tuple(reasons),
        order_count=len(rebalance_plan.orders),
    )
