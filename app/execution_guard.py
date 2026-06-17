from __future__ import annotations

from dataclasses import dataclass

from app.daily_run_plan import DailyRunPlan


@dataclass(frozen=True)
class ExecutionDecision:
    allowed: bool
    reason: str
    required_actions: tuple[str, ...]


def decide_execution(plan: DailyRunPlan) -> ExecutionDecision:
    if plan.result.status == "ready":
        return ExecutionDecision(allowed=True, reason="ready", required_actions=())
    if plan.result.status == "dry_run_ready":
        return ExecutionDecision(allowed=False, reason="dry_run", required_actions=("disable_dry_run",))
    if plan.failure_actions:
        return ExecutionDecision(
            allowed=False,
            reason=plan.action_summary,
            required_actions=tuple(action.action for action in plan.failure_actions),
        )
    return ExecutionDecision(allowed=False, reason="not_ready", required_actions=("manual_review",))


def execution_decision_line(decision: ExecutionDecision) -> str:
    actions = ",".join(decision.required_actions) if decision.required_actions else "none"
    return f"allowed={str(decision.allowed).lower()} reason={decision.reason} actions={actions}"
