from datetime import date

from app.alert_messages import PaperAlertMessage
from app.paper_review import PaperReviewRecord
from app.report_archive import archive_daily_report
from app.run_health import RunHealthReport
from app.run_history import summarize_archived_reports


def _archive(tmp_path, trade_date: date, status: str, notification_accepted: bool):
    return archive_daily_report(
        directory=tmp_path,
        trade_date=trade_date,
        alert_message=PaperAlertMessage("日报", "body", status),
        health_report=RunHealthReport(status, 1 if status == "blocker" else 0, notification_accepted, 0, status),
        review_record=PaperReviewRecord(trade_date, 10000.0, 0.2, status, "HOLD", ""),
    )


def test_summarize_archived_reports_counts_status_and_notifications(tmp_path):
    _archive(tmp_path, date(2026, 1, 28), "ok", True)
    _archive(tmp_path, date(2026, 1, 29), "blocker", False)

    summary = summarize_archived_reports(tmp_path)

    assert summary.report_count == 2
    assert summary.latest_trade_date == "2026-01-29"
    assert summary.latest_status == "blocker"
    assert summary.blocker_count == 1
    assert summary.notification_success_rate == 0.5


def test_summarize_archived_reports_handles_empty_directory(tmp_path):
    summary = summarize_archived_reports(tmp_path)

    assert summary.report_count == 0
    assert summary.latest_status == "missing"
