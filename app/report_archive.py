from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.alert_messages import PaperAlertMessage
from app.paper_review import PaperReviewRecord
from app.run_health import RunHealthReport


@dataclass(frozen=True)
class ArchivedReport:
    path: Path
    trade_date: date
    status: str


def archive_daily_report(
    *,
    directory: str | Path,
    trade_date: date,
    alert_message: PaperAlertMessage,
    health_report: RunHealthReport,
    review_record: PaperReviewRecord,
) -> ArchivedReport:
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{trade_date.isoformat()}-paper-report.json"
    payload: dict[str, Any] = {
        "trade_date": trade_date.isoformat(),
        "alert": {
            "title": alert_message.title,
            "body": alert_message.body,
            "severity": alert_message.severity,
        },
        "health": {
            "status": health_report.status,
            "summary": health_report.summary,
            "issue_count": health_report.issue_count,
            "missing_price_count": health_report.missing_price_count,
            "notification_accepted": health_report.notification_accepted,
        },
        "review": {
            "total_equity": review_record.total_equity,
            "cash_ratio": review_record.cash_ratio,
            "risk_severity": review_record.risk_severity,
            "recommendation_action": review_record.recommendation_action,
            "note": review_record.note,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return ArchivedReport(path=path, trade_date=trade_date, status=health_report.status)


def read_archived_report(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
