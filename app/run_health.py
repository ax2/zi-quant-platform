from __future__ import annotations

from dataclasses import dataclass

from app.notification_channels import NotificationReceipt
from app.price_providers import PriceSnapshot
from app.production_checks import ProductionCheckReport


@dataclass(frozen=True)
class RunHealthReport:
    status: str
    issue_count: int
    notification_accepted: bool
    missing_price_count: int
    summary: str


def build_run_health_report(
    *,
    price_snapshot: PriceSnapshot,
    input_check: ProductionCheckReport,
    result_check: ProductionCheckReport,
    notification_receipt: NotificationReceipt | None = None,
) -> RunHealthReport:
    issue_count = len(input_check.issues) + len(result_check.issues)
    missing_price_count = len(price_snapshot.missing_symbols)
    notification_accepted = notification_receipt.accepted if notification_receipt else False

    if issue_count:
        status = "blocker"
        summary = "每日模拟盘运行存在阻断问题"
    elif missing_price_count:
        status = "warning"
        summary = "每日模拟盘运行缺少部分价格"
    elif notification_receipt is not None and not notification_accepted:
        status = "warning"
        summary = "每日模拟盘结果已生成，但提醒未成功接收"
    else:
        status = "ok"
        summary = "每日模拟盘运行健康"

    return RunHealthReport(
        status=status,
        issue_count=issue_count,
        notification_accepted=notification_accepted,
        missing_price_count=missing_price_count,
        summary=summary,
    )
