from __future__ import annotations

from dataclasses import dataclass

from app.run_result import DailyRunResult


@dataclass(frozen=True)
class FailureAction:
    check_name: str
    action: str
    severity: str


_ACTION_BY_CHECK = {
    "run_window": ("wait_next_window", "info"),
    "history_ready": ("inspect_archive", "warning"),
    "data_gaps": ("repair_market_data", "blocker"),
    "run_health": ("inspect_run_health", "blocker"),
}


def build_failure_actions(result: DailyRunResult) -> tuple[FailureAction, ...]:
    actions: list[FailureAction] = []
    for check_name in result.failed_checks:
        action, severity = _ACTION_BY_CHECK.get(check_name, ("manual_review", "warning"))
        actions.append(FailureAction(check_name=check_name, action=action, severity=severity))
    return tuple(actions)


def failure_action_summary(actions: tuple[FailureAction, ...]) -> str:
    if not actions:
        return "no_action_required"
    if any(action.severity == "blocker" for action in actions):
        return "blocker"
    return "warning"
