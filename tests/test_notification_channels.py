from datetime import datetime, timezone

from app.alert_messages import PaperAlertMessage
from app.notification_channels import MemoryNotificationChannel, send_paper_alert


def test_memory_notification_channel_accepts_valid_message():
    message = PaperAlertMessage(title="日报", body="总权益：10000.00", severity="ok")

    receipt = send_paper_alert(
        MemoryNotificationChannel(),
        message,
        destination="paper-daily",
        sent_at=datetime(2026, 1, 21, 9, 0, tzinfo=timezone.utc),
    )

    assert receipt.accepted is True
    assert receipt.channel == "memory"
    assert receipt.destination == "paper-daily"
    assert receipt.message_title == "日报"


def test_memory_notification_channel_rejects_missing_destination():
    message = PaperAlertMessage(title="日报", body="总权益：10000.00", severity="ok")

    receipt = send_paper_alert(
        MemoryNotificationChannel(),
        message,
        destination="",
        sent_at=datetime(2026, 1, 21, 9, 0, tzinfo=timezone.utc),
    )

    assert receipt.accepted is False
    assert receipt.error == "missing_destination"


def test_memory_notification_channel_rejects_empty_body():
    message = PaperAlertMessage(title="日报", body="  ", severity="ok")

    receipt = send_paper_alert(
        MemoryNotificationChannel(),
        message,
        destination="paper-daily",
        sent_at=datetime(2026, 1, 21, 9, 0, tzinfo=timezone.utc),
    )

    assert receipt.accepted is False
    assert receipt.error == "empty_message_body"
