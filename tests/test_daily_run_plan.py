from datetime import date, datetime

from app.daily_run_plan import build_daily_run_plan, plan_can_execute
from app.ops_checklist import OpsChecklist, OpsChecklistItem
from app.run_request import build_daily_run_request


def test_build_daily_run_plan_allows_real_run_when_ready():
    request = build_daily_run_request(
        trade_date=date(2026, 2, 10),
        generated_at=datetime(2026, 2, 10, 15, 20),
        required_symbols=["000001.SZ"],
        dry_run=False,
    )
    checklist = OpsChecklist(True, (OpsChecklistItem("run_window", True, "within_window"),))

    plan = build_daily_run_plan(request=request, checklist=checklist)

    assert plan.result.status == "ready"
    assert plan.action_summary == "no_action_required"
    assert plan.failure_actions == ()
    assert plan_can_execute(plan) is True


def test_build_daily_run_plan_blocks_and_returns_failure_actions():
    request = build_daily_run_request(
        trade_date=date(2026, 2, 10),
        generated_at=datetime(2026, 2, 10, 14, 0),
        required_symbols=["000001.SZ"],
        dry_run=False,
    )
    checklist = OpsChecklist(
        False,
        (
            OpsChecklistItem("run_window", False, "outside_window"),
            OpsChecklistItem("data_gaps", False, "blocker"),
        ),
    )

    plan = build_daily_run_plan(request=request, checklist=checklist)

    assert plan.result.status == "blocked"
    assert [item.action for item in plan.failure_actions] == ["wait_next_window", "repair_market_data"]
    assert plan.action_summary == "blocker"
    assert plan_can_execute(plan) is False


def test_dry_run_plan_is_actionable_but_not_executable():
    request = build_daily_run_request(
        trade_date=date(2026, 2, 10),
        generated_at=datetime(2026, 2, 10, 15, 20),
        required_symbols=["000001.SZ"],
    )
    checklist = OpsChecklist(True, ())

    plan = build_daily_run_plan(request=request, checklist=checklist)

    assert plan.result.status == "dry_run_ready"
    assert plan_can_execute(plan) is False
