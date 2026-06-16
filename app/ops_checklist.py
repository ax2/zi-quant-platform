from __future__ import annotations

from dataclasses import dataclass

from app.data_gaps import DataGapPlan
from app.run_health import RunHealthReport
from app.run_history import RunHistorySummary
from app.run_window import RunWindowStatus


@dataclass(frozen=True)
class OpsChecklistItem:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class OpsChecklist:
    passed: bool
    items: tuple[OpsChecklistItem, ...]


def build_ops_checklist(
    *,
    window_status: RunWindowStatus,
    history_summary: RunHistorySummary,
    gap_plan: DataGapPlan,
    health_report: RunHealthReport,
) -> OpsChecklist:
    items = (
        OpsChecklistItem("run_window", window_status.allowed, window_status.reason),
        OpsChecklistItem("history_ready", history_summary.report_count > 0, history_summary.latest_status),
        OpsChecklistItem("data_gaps", not gap_plan.gaps, gap_plan.severity),
        OpsChecklistItem("run_health", health_report.status != "blocker", health_report.status),
    )
    return OpsChecklist(passed=all(item.passed for item in items), items=items)
