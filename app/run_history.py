from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.report_archive import read_archived_report


@dataclass(frozen=True)
class RunHistorySummary:
    report_count: int
    latest_trade_date: str
    latest_status: str
    blocker_count: int
    notification_success_rate: float


def summarize_archived_reports(directory: str | Path) -> RunHistorySummary:
    reports = []
    for path in sorted(Path(directory).glob("*-paper-report.json")):
        reports.append(read_archived_report(path))
    if not reports:
        return RunHistorySummary(0, "", "missing", 0, 0.0)

    blocker_count = sum(1 for item in reports if item["health"]["status"] == "blocker")
    notification_count = sum(1 for item in reports if item["health"].get("notification_accepted"))
    latest = reports[-1]
    return RunHistorySummary(
        report_count=len(reports),
        latest_trade_date=latest["trade_date"],
        latest_status=latest["health"]["status"],
        blocker_count=blocker_count,
        notification_success_rate=round(notification_count / len(reports), 6),
    )
