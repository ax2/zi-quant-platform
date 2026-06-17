from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.daily_run_plan import DailyRunPlan
from app.daily_run_summary import build_daily_run_summary


@dataclass(frozen=True)
class DailyRunArtifact:
    path: Path
    payload: dict[str, Any]


def daily_run_artifact_payload(plan: DailyRunPlan) -> dict[str, Any]:
    summary = build_daily_run_summary(plan)
    return {
        "trade_date": summary.trade_date,
        "status": summary.status,
        "dry_run": summary.dry_run,
        "symbol_count": summary.symbol_count,
        "required_symbols": list(plan.request.required_symbols),
        "failed_checks": list(plan.result.failed_checks),
        "actions": [
            {
                "check_name": action.check_name,
                "action": action.action,
                "severity": action.severity,
            }
            for action in plan.failure_actions
        ],
        "action_summary": summary.action_summary,
        "executable": summary.executable,
        "generated_at": plan.request.generated_at.isoformat(),
    }


def write_daily_run_artifact(plan: DailyRunPlan, *, directory: Path) -> DailyRunArtifact:
    payload = daily_run_artifact_payload(plan)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"daily-run-{payload['trade_date']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return DailyRunArtifact(path=path, payload=payload)


def read_daily_run_artifact(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
