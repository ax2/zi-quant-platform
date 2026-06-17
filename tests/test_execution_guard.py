from datetime import date, datetime

from app.daily_run_plan import build_daily_run_plan
from app.execution_guard import decide_execution, execution_decision_line
from app.ops_checklist import OpsChecklist, OpsChecklistItem
from app.run_request import build_daily_run_request


def _plan(*, dry_run: bool = False, item: OpsChecklistItem | None = None):
    request = build_daily_run_request(
        trade_date=date(2026, 2, 14),
        generated_at=datetime(2026, 2, 14, 15, 20),
        required_symbols=["000001.SZ"],
        dry_run=dry_run,
    )
    return build_daily_run_plan(
        request=request,
        checklist=OpsChecklist(item is None, () if item is None else (item,)),
    )


def test_decide_execution_allows_ready_plan():
    decision = decide_execution(_plan())

    assert decision.allowed is True
    assert decision.reason == "ready"
    assert decision.required_actions == ()


def test_decide_execution_blocks_dry_run_plan():
    decision = decide_execution(_plan(dry_run=True))

    assert decision.allowed is False
    assert decision.reason == "dry_run"
    assert decision.required_actions == ("disable_dry_run",)


def test_decide_execution_returns_failure_actions_for_blocked_plan():
    decision = decide_execution(_plan(item=OpsChecklistItem("data_gaps", False, "missing")))

    assert decision.allowed is False
    assert decision.reason == "blocker"
    assert decision.required_actions == ("repair_market_data",)


def test_execution_decision_line_is_stable_for_logs():
    line = execution_decision_line(
        decide_execution(_plan(item=OpsChecklistItem("history_ready", False, "missing")))
    )

    assert line == "allowed=false reason=warning actions=inspect_archive"
