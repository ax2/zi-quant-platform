from datetime import date, datetime

from app.daily_run_artifacts import (
    daily_run_artifact_payload,
    read_daily_run_artifact,
    write_daily_run_artifact,
)
from app.daily_run_plan import build_daily_run_plan
from app.ops_checklist import OpsChecklist, OpsChecklistItem
from app.run_request import build_daily_run_request


def test_daily_run_artifact_payload_contains_debuggable_context():
    request = build_daily_run_request(
        trade_date=date(2026, 2, 12),
        generated_at=datetime(2026, 2, 12, 15, 20),
        required_symbols=["000001.SZ", "000002.SZ"],
        dry_run=False,
    )
    plan = build_daily_run_plan(request=request, checklist=OpsChecklist(True, ()))

    payload = daily_run_artifact_payload(plan)

    assert payload["trade_date"] == "2026-02-12"
    assert payload["status"] == "ready"
    assert payload["required_symbols"] == ["000001.SZ", "000002.SZ"]
    assert payload["actions"] == []
    assert payload["executable"] is True


def test_write_daily_run_artifact_round_trips_json(tmp_path):
    request = build_daily_run_request(
        trade_date=date(2026, 2, 12),
        generated_at=datetime(2026, 2, 12, 14, 0),
        required_symbols=["000001.SZ"],
        dry_run=False,
    )
    checklist = OpsChecklist(False, (OpsChecklistItem("run_health", False, "stale"),))
    plan = build_daily_run_plan(request=request, checklist=checklist)

    artifact = write_daily_run_artifact(plan, directory=tmp_path)

    assert artifact.path.name == "daily-run-2026-02-12.json"
    assert read_daily_run_artifact(artifact.path) == artifact.payload
    assert artifact.payload["actions"] == [
        {"check_name": "run_health", "action": "inspect_run_health", "severity": "blocker"}
    ]
