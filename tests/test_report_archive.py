from datetime import date

from app.alert_messages import PaperAlertMessage
from app.paper_review import PaperReviewRecord
from app.report_archive import archive_daily_report, read_archived_report
from app.run_health import RunHealthReport


def test_archive_daily_report_writes_stable_json(tmp_path):
    archived = archive_daily_report(
        directory=tmp_path,
        trade_date=date(2026, 1, 28),
        alert_message=PaperAlertMessage("日报", "总权益：10000.00", "ok"),
        health_report=RunHealthReport("ok", 0, True, 0, "运行健康"),
        review_record=PaperReviewRecord(date(2026, 1, 28), 10000.0, 0.2, "ok", "HOLD", "done"),
    )

    payload = read_archived_report(archived.path)

    assert archived.status == "ok"
    assert archived.path.name == "2026-01-28-paper-report.json"
    assert payload["trade_date"] == "2026-01-28"
    assert payload["health"]["status"] == "ok"
    assert payload["review"]["recommendation_action"] == "HOLD"
