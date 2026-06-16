from __future__ import annotations

from dataclasses import dataclass

from app.paper_risk import PaperRiskReport
from app.paper_snapshots import PaperAccountSnapshot
from app.rebalance_plan import RebalancePlan


@dataclass(frozen=True)
class PaperAlertMessage:
    title: str
    body: str
    severity: str


def format_paper_daily_alert(
    snapshot: PaperAccountSnapshot,
    risk_report: PaperRiskReport,
    rebalance_plan: RebalancePlan | None = None,
) -> PaperAlertMessage:
    title = f"ZiQuant 模拟盘日报 {snapshot.trade_date.isoformat()}"
    lines = [
        f"总权益：{snapshot.total_equity:.2f}",
        f"现金：{snapshot.cash:.2f}（{snapshot.cash_ratio:.2%}）",
        f"持仓市值：{snapshot.market_value:.2f}",
        f"风控状态：{risk_report.severity}",
    ]

    if risk_report.violations:
        lines.append("风控提示：")
        for violation in risk_report.violations:
            target = f"{violation.symbol} " if violation.symbol else ""
            lines.append(f"- {target}{violation.message}：{violation.value:.2%} / {violation.limit:.2%}")

    if rebalance_plan is not None:
        if rebalance_plan.orders:
            lines.append("调仓建议：")
            for order in rebalance_plan.orders:
                lines.append(f"- {order.side} {order.symbol} {order.shares} 股 @ {order.price:.2f}")
        else:
            lines.append("调仓建议：无需调仓")

    return PaperAlertMessage(title=title, body="\n".join(lines), severity=risk_report.severity)
