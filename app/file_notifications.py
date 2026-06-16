from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.alert_messages import PaperAlertMessage
from app.notification_channels import NotificationReceipt


@dataclass(frozen=True)
class FileNotificationChannel:
    path: Path
    name: str = "file"

    def send(self, message: PaperAlertMessage, *, destination: str, sent_at: datetime) -> NotificationReceipt:
        receipt = NotificationReceipt(
            channel=self.name,
            accepted=bool(destination and message.body.strip()),
            destination=destination,
            message_title=message.title,
            sent_at=sent_at,
            error="" if destination and message.body.strip() else "invalid_notification",
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "channel": receipt.channel,
            "accepted": receipt.accepted,
            "destination": receipt.destination,
            "message_title": receipt.message_title,
            "sent_at": receipt.sent_at.isoformat(),
            "severity": message.severity,
            "body": message.body,
            "error": receipt.error,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return receipt


def read_file_notifications(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
