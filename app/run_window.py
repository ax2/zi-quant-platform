from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True)
class RunWindow:
    start: time
    end: time
    timezone_name: str = "Asia/Shanghai"


@dataclass(frozen=True)
class RunWindowStatus:
    allowed: bool
    reason: str
    next_run_at: datetime | None = None


def is_within_run_window(now: datetime, window: RunWindow) -> bool:
    current = now.time()
    if window.start <= window.end:
        return window.start <= current <= window.end
    return current >= window.start or current <= window.end


def evaluate_run_window(now: datetime, window: RunWindow) -> RunWindowStatus:
    if is_within_run_window(now, window):
        return RunWindowStatus(True, "within_window")

    candidate = datetime.combine(now.date(), window.start, tzinfo=now.tzinfo)
    if candidate <= now:
        candidate += timedelta(days=1)
    return RunWindowStatus(False, "outside_window", candidate)
