from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.daily_run_artifacts import DailyRunArtifact, write_daily_run_artifact
from app.daily_run_plan import DailyRunPlan
from app.daily_run_summary import build_daily_run_summary, format_daily_run_summary


@dataclass(frozen=True)
class DailyRunCommandResponse:
    status: str
    message: str
    artifact_path: Path
    exit_code: int


def daily_run_exit_code(plan: DailyRunPlan) -> int:
    if plan.result.status in {"ready", "dry_run_ready"}:
        return 0
    if plan.action_summary == "warning":
        return 2
    return 1


def build_daily_run_command_response(
    *,
    plan: DailyRunPlan,
    artifact: DailyRunArtifact,
) -> DailyRunCommandResponse:
    summary = build_daily_run_summary(plan)
    return DailyRunCommandResponse(
        status=summary.status,
        message=format_daily_run_summary(summary),
        artifact_path=artifact.path,
        exit_code=daily_run_exit_code(plan),
    )


def write_daily_run_command_response(
    *,
    plan: DailyRunPlan,
    artifact_dir: Path,
) -> DailyRunCommandResponse:
    artifact = write_daily_run_artifact(plan, directory=artifact_dir)
    return build_daily_run_command_response(plan=plan, artifact=artifact)
