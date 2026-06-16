from datetime import date, datetime, timezone

from app.notification_channels import NotificationReceipt
from app.price_providers import PriceSnapshot
from app.production_checks import ProductionCheckIssue, ProductionCheckReport
from app.run_health import build_run_health_report


def test_run_health_is_ok_when_checks_pass_and_notification_is_accepted():
    report = build_run_health_report(
        price_snapshot=PriceSnapshot(date(2026, 1, 26), {"000001.SZ": 10.0}, ()),
        input_check=ProductionCheckReport(True, ()),
        result_check=ProductionCheckReport(True, ()),
        notification_receipt=NotificationReceipt("file", True, "paper-daily", "日报", datetime(2026, 1, 26, tzinfo=timezone.utc)),
    )

    assert report.status == "ok"
    assert report.notification_accepted is True
    assert report.summary == "每日模拟盘运行健康"


def test_run_health_is_blocker_when_checks_have_issues():
    report = build_run_health_report(
        price_snapshot=PriceSnapshot(date(2026, 1, 26), {}, ()),
        input_check=ProductionCheckReport(False, (ProductionCheckIssue("missing_prices", "缺行情", "blocker"),)),
        result_check=ProductionCheckReport(True, ()),
    )

    assert report.status == "blocker"
    assert report.issue_count == 1


def test_run_health_warns_when_notification_fails():
    report = build_run_health_report(
        price_snapshot=PriceSnapshot(date(2026, 1, 26), {"000001.SZ": 10.0}, ()),
        input_check=ProductionCheckReport(True, ()),
        result_check=ProductionCheckReport(True, ()),
        notification_receipt=NotificationReceipt("file", False, "paper-daily", "日报", datetime(2026, 1, 26, tzinfo=timezone.utc), "invalid"),
    )

    assert report.status == "warning"
    assert report.notification_accepted is False
