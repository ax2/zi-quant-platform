from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.alert_messages import PaperAlertMessage


@dataclass(frozen=True)
class NotificationReceipt:
    channel: str
    accepted: bool
    destination: str
    message_title: str
    sent_at: datetime
    error: str = ""


class NotificationChannel(Protocol):
    name: str

    def send(self, message: PaperAlertMessage, *, destination: str, sent_at: datetime) -> NotificationReceipt:
        ...


@dataclass(frozen=True)
class MemoryNotificationChannel:
    name: str = "memory"

    def send(self, message: PaperAlertMessage, *, destination: str, sent_at: datetime) -> NotificationReceipt:
        if not destination:
            return NotificationReceipt(
                channel=self.name,
                accepted=False,
                destination=destination,
                message_title=message.title,
                sent_at=sent_at,
                error="missing_destination",
            )
        if not message.body.strip():
            return NotificationReceipt(
                channel=self.name,
                accepted=False,
                destination=destination,
                message_title=message.title,
                sent_at=sent_at,
                error="empty_message_body",
            )
        return NotificationReceipt(
            channel=self.name,
            accepted=True,
            destination=destination,
            message_title=message.title,
            sent_at=sent_at,
        )


def send_paper_alert(
    channel: NotificationChannel,
    message: PaperAlertMessage,
    *,
    destination: str,
    sent_at: datetime,
) -> NotificationReceipt:
    return channel.send(message, destination=destination, sent_at=sent_at)
