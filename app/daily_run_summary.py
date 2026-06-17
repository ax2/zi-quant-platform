from __future__ import annotations

from dataclasses import dataclass

from app.daily_run_plan import DailyRunPlan, plan_can_execute


@dataclass(frozen=True)
class DailyRunSummary:
    trade_date: str
    status: str
    dry_run: bool
    symbol_count: int
    failed_check_count: int
    action_summary: str
    executable: bool


def build_daily_run_summary(plan: DailyRunPlan) -> DailyRunSummary:
    return DailyRunSummary(
        trade_date=plan.result.trade_date,
        status=plan.result.status,
        dry_run=plan.result.dry_run,
        symbol_count=len(plan.request.required_symbols),
        failed_check_count=len(plan.result.failed_checks),
        action_summary=plan.action_summary,
        executable=plan_can_execute(plan),
    )


def format_daily_run_summary(summary: DailyRunSummary) -> str:
    return (
        f"{summary.trade_date} "
        f"status={summary.status} "
        f"symbols={summary.symbol_count} "
        f"failed_checks={summary.failed_check_count} "
        f"actions={summary.action_summary} "
        f"executable={str(summary.executable).lower()}"
    )
