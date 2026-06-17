from datetime import date, datetime

from app.daily_run_plan import build_daily_run_plan
from app.ops_checklist import OpsChecklist, OpsChecklistItem
from app.ops_runbook import build_ops_runbook, runbook_as_lines
from app.run_request import build_daily_run_request


def _plan(*, dry_run: bool = False, item: OpsChecklistItem | None = None):
    request = build_daily_run_request(
        trade_date=date(2026, 2, 15),
        generated_at=datetime(2026, 2, 15, 15, 20),
        required_symbols=["000001.SZ"],
        dry_run=dry_run,
    )
    return build_daily_run_plan(
        request=request,
        checklist=OpsChecklist(item is None, () if item is None else (item,)),
    )


def test_build_ops_runbook_for_ready_plan_contains_execution_steps():
    runbook = build_ops_runbook(_plan())

    assert runbook.trade_date == "2026-02-15"
    assert runbook.status == "ready"
    assert [step.title for step in runbook.steps] == ["confirm artifact", "execute plan"]


def test_build_ops_runbook_for_dry_run_requires_manual_confirmation():
    runbook = build_ops_runbook(_plan(dry_run=True))

    assert [step.title for step in runbook.steps] == ["disable_dry_run"]
    assert "dry_run=false" in runbook.steps[0].command


def test_build_ops_runbook_for_blocked_plan_follows_failure_actions():
    runbook = build_ops_runbook(_plan(item=OpsChecklistItem("run_window", False, "too_early")))

    assert runbook.status == "blocked"
    assert [step.title for step in runbook.steps] == ["wait_next_window"]
    assert "run window" in runbook.steps[0].command


def test_runbook_as_lines_is_readable_in_alerts():
    lines = runbook_as_lines(build_ops_runbook(_plan(item=OpsChecklistItem("data_gaps", False, "missing"))))

    assert lines == (
        "2026-02-15 status=blocked",
        "- repair_market_data: reload missing market data and rerun checklist",
    )
