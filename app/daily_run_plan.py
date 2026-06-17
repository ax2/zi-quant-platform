from __future__ import annotations

from dataclasses import dataclass

from app.failure_policy import FailureAction, build_failure_actions, failure_action_summary
from app.ops_checklist import OpsChecklist
from app.run_request import DailyRunRequest
from app.run_result import DailyRunResult, build_daily_run_result


@dataclass(frozen=True)
class DailyRunPlan:
    request: DailyRunRequest
    result: DailyRunResult
    failure_actions: tuple[FailureAction, ...]
    action_summary: str


def build_daily_run_plan(*, request: DailyRunRequest, checklist: OpsChecklist) -> DailyRunPlan:
    result = build_daily_run_result(request=request, checklist=checklist)
    actions = build_failure_actions(result)
    return DailyRunPlan(
        request=request,
        result=result,
        failure_actions=actions,
        action_summary=failure_action_summary(actions),
    )


def plan_can_execute(plan: DailyRunPlan) -> bool:
    return plan.result.status == "ready"
