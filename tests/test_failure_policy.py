from app.failure_policy import build_failure_actions, failure_action_summary
from app.run_result import DailyRunResult


def test_build_failure_actions_maps_known_checks_to_actions():
    result = DailyRunResult(
        trade_date="2026-02-09",
        status="blocked",
        dry_run=True,
        failed_checks=("run_window", "data_gaps", "run_health"),
    )

    actions = build_failure_actions(result)

    assert [(item.check_name, item.action, item.severity) for item in actions] == [
        ("run_window", "wait_next_window", "info"),
        ("data_gaps", "repair_market_data", "blocker"),
        ("run_health", "inspect_run_health", "blocker"),
    ]
    assert failure_action_summary(actions) == "blocker"


def test_failure_action_summary_handles_warning_and_empty_actions():
    unknown = build_failure_actions(
        DailyRunResult("2026-02-09", "blocked", True, ("unknown_check",))
    )

    assert unknown[0].action == "manual_review"
    assert failure_action_summary(unknown) == "warning"
    assert failure_action_summary(()) == "no_action_required"
