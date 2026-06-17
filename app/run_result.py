from __future__ import annotations

from dataclasses import dataclass

from app.ops_checklist import OpsChecklist
from app.run_request import DailyRunRequest


@dataclass(frozen=True)
class DailyRunResult:
    trade_date: str
    status: str
    dry_run: bool
    failed_checks: tuple[str, ...]


def build_daily_run_result(*, request: DailyRunRequest, checklist: OpsChecklist) -> DailyRunResult:
    failed = tuple(item.name for item in checklist.items if not item.passed)
    if failed:
        status = "blocked"
    elif request.dry_run:
        status = "dry_run_ready"
    else:
        status = "ready"
    return DailyRunResult(
        trade_date=request.trade_date.isoformat(),
        status=status,
        dry_run=request.dry_run,
        failed_checks=failed,
    )


def result_is_actionable(result: DailyRunResult) -> bool:
    return result.status in {"ready", "dry_run_ready"}
