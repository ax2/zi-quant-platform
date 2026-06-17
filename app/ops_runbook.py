from __future__ import annotations

from dataclasses import dataclass

from app.daily_run_plan import DailyRunPlan
from app.execution_guard import decide_execution


@dataclass(frozen=True)
class RunbookStep:
    title: str
    command: str
    required: bool


@dataclass(frozen=True)
class OpsRunbook:
    trade_date: str
    status: str
    steps: tuple[RunbookStep, ...]


_COMMAND_BY_ACTION = {
    "disable_dry_run": "rerun with dry_run=false after manual confirmation",
    "inspect_archive": "check report archive index for the previous successful run",
    "inspect_run_health": "inspect recent run health events and retry only after recovery",
    "repair_market_data": "reload missing market data and rerun checklist",
    "wait_next_window": "wait until the configured run window opens",
    "manual_review": "open the artifact and review the failed checklist item manually",
}


def build_ops_runbook(plan: DailyRunPlan) -> OpsRunbook:
    decision = decide_execution(plan)
    if decision.allowed:
        steps = (
            RunbookStep("confirm artifact", "open the daily-run artifact before execution", True),
            RunbookStep("execute plan", "start the simulated trading daily run", True),
        )
    else:
        steps = tuple(
            RunbookStep(action, _COMMAND_BY_ACTION.get(action, _COMMAND_BY_ACTION["manual_review"]), True)
            for action in decision.required_actions
        )
    return OpsRunbook(trade_date=plan.result.trade_date, status=plan.result.status, steps=steps)


def runbook_as_lines(runbook: OpsRunbook) -> tuple[str, ...]:
    header = f"{runbook.trade_date} status={runbook.status}"
    step_lines = tuple(f"- {step.title}: {step.command}" for step in runbook.steps)
    return (header, *step_lines)
