from datetime import date

from app.alert_messages import PaperAlertMessage
from app.paper_review import PaperReviewRecord
from app.report_archive import archive_daily_report
from app.report_index import build_report_index, latest_report_entry
from app.run_health import RunHealthReport


def _archive(tmp_path, trade_date: date, status: str):
    return archive_daily_report(
        directory=tmp_path,
        trade_date=trade_date,
        alert_message=PaperAlertMessage("日报", "body", status),
        health_report=RunHealthReport(status, 1 if status == "blocker" else 0, True, 0, status),
        review_record=PaperReviewRecord(trade_date, 10000.0, 0.2, status, "HOLD", ""),
    )


def test_build_report_index_lists_archived_reports_in_date_order(tmp_path):
    _archive(tmp_path, date(2026, 2, 5), "ok")
    _archive(tmp_path, date(2026, 2, 6), "blocker")

    entries = build_report_index(tmp_path)

    assert [entry.trade_date for entry in entries] == ["2026-02-05", "2026-02-06"]
    assert [entry.status for entry in entries] == ["ok", "blocker"]
    assert entries[0].path.name == "2026-02-05-paper-report.json"
    assert latest_report_entry(entries) == entries[-1]


def test_latest_report_entry_handles_empty_index():
    assert latest_report_entry(()) is None
