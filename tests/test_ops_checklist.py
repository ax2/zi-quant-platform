from datetime import date, datetime, time

from app.data_gaps import DataGapPlan
from app.ops_checklist import build_ops_checklist
from app.run_health import RunHealthReport
from app.run_history import RunHistorySummary
from app.run_window import RunWindow, evaluate_run_window


def test_ops_checklist_passes_when_all_inputs_are_healthy():
    checklist = build_ops_checklist(
        window_status=evaluate_run_window(datetime(2026, 2, 2, 15, 20), RunWindow(time(15, 10), time(15, 40))),
        history_summary=RunHistorySummary(3, "2026-02-02", "ok", 0, 1.0),
        gap_plan=DataGapPlan((), "ok"),
        health_report=RunHealthReport("ok", 0, True, 0, "healthy"),
    )

    assert checklist.passed is True
    assert [item.name for item in checklist.items] == ["run_window", "history_ready", "data_gaps", "run_health"]


def test_ops_checklist_fails_for_missing_history_or_blocker_health():
    checklist = build_ops_checklist(
        window_status=evaluate_run_window(datetime(2026, 2, 2, 14, 0), RunWindow(time(15, 10), time(15, 40))),
        history_summary=RunHistorySummary(0, "", "missing", 0, 0.0),
        gap_plan=DataGapPlan((), "ok"),
        health_report=RunHealthReport("blocker", 1, False, 0, "bad"),
    )

    assert checklist.passed is False
    failed = {item.name for item in checklist.items if not item.passed}
    assert failed == {"run_window", "history_ready", "run_health"}
