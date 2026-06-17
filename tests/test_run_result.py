from datetime import date, datetime

from app.ops_checklist import OpsChecklist, OpsChecklistItem
from app.run_request import build_daily_run_request
from app.run_result import build_daily_run_result, result_is_actionable


def test_build_daily_run_result_marks_ready_when_checklist_passes():
    request = build_daily_run_request(
        trade_date=date(2026, 2, 4),
        generated_at=datetime(2026, 2, 4, 15, 20),
        required_symbols=["000001.SZ"],
        dry_run=False,
    )
    checklist = OpsChecklist(True, (OpsChecklistItem("run_window", True, "within_window"),))

    result = build_daily_run_result(request=request, checklist=checklist)

    assert result.status == "ready"
    assert result.trade_date == "2026-02-04"
    assert result.failed_checks == ()
    assert result_is_actionable(result) is True


def test_build_daily_run_result_keeps_failed_check_names():
    request = build_daily_run_request(
        trade_date=date(2026, 2, 4),
        generated_at=datetime(2026, 2, 4, 15, 20),
        required_symbols=["000001.SZ"],
    )
    checklist = OpsChecklist(
        False,
        (
            OpsChecklistItem("run_window", False, "outside_window"),
            OpsChecklistItem("data_gaps", False, "blocker"),
        ),
    )

    result = build_daily_run_result(request=request, checklist=checklist)

    assert result.status == "blocked"
    assert result.dry_run is True
    assert result.failed_checks == ("run_window", "data_gaps")
    assert result_is_actionable(result) is False


def test_build_daily_run_result_marks_dry_run_ready():
    request = build_daily_run_request(
        trade_date=date(2026, 2, 4),
        generated_at=datetime(2026, 2, 4, 15, 20),
        required_symbols=["000001.SZ"],
    )
    checklist = OpsChecklist(True, ())

    result = build_daily_run_result(request=request, checklist=checklist)

    assert result.status == "dry_run_ready"
    assert result_is_actionable(result) is True
