from datetime import date, datetime

from app.daily_run_plan import build_daily_run_plan
from app.daily_run_summary import build_daily_run_summary, format_daily_run_summary
from app.ops_checklist import OpsChecklist, OpsChecklistItem
from app.run_request import build_daily_run_request


def test_build_daily_run_summary_reports_ready_plan():
    request = build_daily_run_request(
        trade_date=date(2026, 2, 11),
        generated_at=datetime(2026, 2, 11, 15, 20),
        required_symbols=["000001.SZ", "000002.SZ", "000001.SZ"],
        dry_run=False,
    )
    checklist = OpsChecklist(True, ())
    plan = build_daily_run_plan(request=request, checklist=checklist)

    summary = build_daily_run_summary(plan)

    assert summary.trade_date == "2026-02-11"
    assert summary.status == "ready"
    assert summary.symbol_count == 2
    assert summary.failed_check_count == 0
    assert summary.executable is True


def test_format_daily_run_summary_keeps_key_fields_in_one_line():
    request = build_daily_run_request(
        trade_date=date(2026, 2, 11),
        generated_at=datetime(2026, 2, 11, 14, 30),
        required_symbols=["000001.SZ"],
        dry_run=False,
    )
    checklist = OpsChecklist(False, (OpsChecklistItem("data_gaps", False, "missing"),))
    plan = build_daily_run_plan(request=request, checklist=checklist)

    line = format_daily_run_summary(build_daily_run_summary(plan))

    assert line == (
        "2026-02-11 status=blocked symbols=1 failed_checks=1 "
        "actions=blocker executable=false"
    )
