from __future__ import annotations

from scripts.production_smoke import evaluate_smoke_results


def test_evaluate_smoke_results_passes_ready_paper_observation_state():
    report = evaluate_smoke_results(
        {
            "ready": {
                "status": "ready",
                "recommendation_workflow": {
                    "status": "ready",
                    "passed": True,
                    "feishu_signal_job": {"exists": True, "ready": True, "send_mode": "dry_run", "live_ready": False},
                    "lark_cli": {"available": True},
                },
            },
            "ops": {"status": "ready", "action_items": [{"severity": "low"}]},
            "acceptance": {"decision": "accepted_for_paper_observation", "required_passed": 12, "required_total": 12},
            "risk": {"status": "clear", "event_count": 0},
            "provenance": {"status": "ready"},
            "recommendations": {"status": "ready", "paper_only": True, "recommendations": [{"symbol": "600519.SH"}]},
            "recommendation_review": {"status": "ready", "paper_only": True, "items": [{"symbol": "600519.SH"}]},
            "stock_analysis": {"found": True, "paper_only": True, "recommendation": {"action": "HOLD_WATCH"}, "latest_quote": {"close": 1200.0}},
        },
        migration_ok=True,
        backup_report={"status": "ready", "passed": True, "detail": "dry_run=dry_run"},
    )

    assert report["status"] == "ready"
    assert report["paper_only"] is True
    assert report["failed"] == []
    assert report["summary"]["ops_action_items"] == 1
    assert report["summary"]["data_provenance"] == "ready"
    assert report["summary"]["realtime_recommendations"] == "ready"
    assert report["summary"]["recommendation_count"] == 1
    assert report["summary"]["recommendation_review"] == "ready"
    assert report["summary"]["stock_analysis"] == "ready"
    assert report["summary"]["feishu_signal"] == "dry_run"
    assert report["summary"]["database_backup"] == "ready"
    assert "never places real orders" in report["warning"]


def test_evaluate_smoke_results_fails_blocking_conditions():
    report = evaluate_smoke_results(
        {
            "ready": {
                "status": "ready",
                "recommendation_workflow": {
                    "status": "degraded",
                    "passed": False,
                    "feishu_signal_job": {"exists": False, "ready": False},
                    "lark_cli": {"available": False},
                },
            },
            "ops": {"status": "degraded", "action_items": [{"severity": "high"}]},
            "acceptance": {"decision": "not_accepted", "required_passed": 11, "required_total": 12},
            "risk": {"status": "risk", "event_count": 2},
            "provenance": {"status": "degraded"},
            "recommendations": {"status": "empty", "paper_only": True, "recommendations": []},
            "recommendation_review": {"status": "insufficient_history", "paper_only": True, "items": []},
            "stock_analysis": {"found": False, "reason": "missing_stock"},
        },
        migration_ok=False,
        backup_report={"status": "missing_pg_dump", "passed": False, "detail": "pg_dump is not available on PATH"},
    )

    assert report["status"] == "failed"
    assert set(report["failed"]) == {"migration_current", "ops_status", "production_acceptance", "paper_risk_events", "data_provenance", "realtime_recommendations", "yesterday_recommendation_review", "stock_analysis", "feishu_signal_workflow", "database_backup_dry_run"}


def test_evaluate_smoke_results_allows_explicit_backup_skip():
    report = evaluate_smoke_results(
        {
            "ready": {
                "status": "ready",
                "recommendation_workflow": {
                    "status": "ready",
                    "passed": True,
                    "feishu_signal_job": {"exists": True, "ready": True, "send_mode": "dry_run", "live_ready": False},
                    "lark_cli": {"available": True},
                },
            },
            "ops": {"status": "ready"},
            "acceptance": {"decision": "accepted_for_paper_observation", "required_passed": 12, "required_total": 12},
            "risk": {"status": "watch", "event_count": 1},
            "provenance": {"status": "ready"},
            "recommendations": {"status": "ready", "paper_only": True, "recommendations": [{"symbol": "600519.SH"}]},
            "recommendation_review": {"status": "ready", "paper_only": True, "items": [{"symbol": "600519.SH"}]},
            "stock_analysis": {"found": True, "paper_only": True, "recommendation": {"action": "HOLD_WATCH"}, "latest_quote": {"close": 1200.0}},
        },
        migration_ok=True,
        backup_report=None,
    )

    assert report["status"] == "ready"
    assert report["summary"]["database_backup"] == "skipped"


def test_evaluate_smoke_results_strict_production_requires_live_feishu_signal():
    base_payloads = {
        "ready": {
            "status": "ready",
            "recommendation_workflow": {
                "status": "ready",
                "passed": True,
                "feishu_signal_job": {"exists": True, "ready": True, "send_mode": "dry_run", "live_ready": False},
                "lark_cli": {"available": True},
            },
        },
        "ops": {"status": "ready"},
        "acceptance": {"decision": "accepted_for_paper_observation", "required_passed": 12, "required_total": 12},
        "risk": {"status": "clear", "event_count": 0},
        "provenance": {"status": "ready"},
        "recommendations": {"status": "ready", "paper_only": True, "recommendations": [{"symbol": "600519.SH"}]},
        "recommendation_review": {"status": "ready", "paper_only": True, "items": [{"symbol": "600519.SH"}]},
        "stock_analysis": {"found": True, "paper_only": True, "recommendation": {"action": "HOLD_WATCH"}, "latest_quote": {"close": 1200.0}},
    }

    report = evaluate_smoke_results(
        base_payloads,
        migration_ok=True,
        backup_report={"status": "ready", "passed": True, "detail": "dry_run=dry_run"},
        strict_production=True,
    )

    assert report["status"] == "failed"
    assert report["failed"] == ["feishu_signal_workflow"]

    base_payloads["ready"]["recommendation_workflow"]["feishu_signal_job"]["send_mode"] = "live"
    base_payloads["ready"]["recommendation_workflow"]["feishu_signal_job"]["live_ready"] = True
    live_report = evaluate_smoke_results(
        base_payloads,
        migration_ok=True,
        backup_report={"status": "ready", "passed": True, "detail": "dry_run=dry_run"},
        strict_production=True,
    )

    assert live_report["status"] == "ready"
    assert live_report["summary"]["feishu_signal"] == "live_ready"
