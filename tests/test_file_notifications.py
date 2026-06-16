from datetime import datetime, timezone

from app.alert_messages import PaperAlertMessage
from app.file_notifications import FileNotificationChannel, read_file_notifications
from app.notification_channels import send_paper_alert


def test_file_notification_channel_appends_jsonl_rows(tmp_path):
    path = tmp_path / "notifications" / "paper-alerts.jsonl"
    channel = FileNotificationChannel(path=path)
    message = PaperAlertMessage(title="日报", body="总权益：10000.00", severity="ok")

    receipt = send_paper_alert(
        channel,
        message,
        destination="paper-daily",
        sent_at=datetime(2026, 1, 22, 9, 0, tzinfo=timezone.utc),
    )

    rows = read_file_notifications(path)
    assert receipt.accepted is True
    assert len(rows) == 1
    assert rows[0]["message_title"] == "日报"
    assert rows[0]["body"] == "总权益：10000.00"


def test_file_notification_channel_records_invalid_notification(tmp_path):
    path = tmp_path / "paper-alerts.jsonl"
    channel = FileNotificationChannel(path=path)
    message = PaperAlertMessage(title="日报", body="", severity="ok")

    receipt = send_paper_alert(
        channel,
        message,
        destination="paper-daily",
        sent_at=datetime(2026, 1, 22, 9, 0, tzinfo=timezone.utc),
    )

    rows = read_file_notifications(path)
    assert receipt.accepted is False
    assert rows[0]["accepted"] is False
    assert rows[0]["error"] == "invalid_notification"


def test_read_file_notifications_returns_empty_for_missing_file(tmp_path):
    assert read_file_notifications(tmp_path / "missing.jsonl") == []
