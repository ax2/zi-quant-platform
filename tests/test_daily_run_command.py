from datetime import date, datetime

from app.daily_run_artifacts import write_daily_run_artifact
from app.daily_run_command import (
    build_daily_run_command_response,
    daily_run_exit_code,
    write_daily_run_command_response,
)
from app.daily_run_plan import build_daily_run_plan
from app.ops_checklist import OpsChecklist, OpsChecklistItem
from app.run_request import build_daily_run_request


def _plan(*, passed: bool, check_name: str | None = None, dry_run: bool = False):
    request = build_daily_run_request(
        trade_date=date(2026, 2, 13),
        generated_at=datetime(2026, 2, 13, 15, 20),
        required_symbols=["000001.SZ"],
        dry_run=dry_run,
    )
    items = () if passed else (OpsChecklistItem(check_name or "data_gaps", False, "failed"),)
    return build_daily_run_plan(request=request, checklist=OpsChecklist(passed, items))


def test_daily_run_exit_code_maps_ready_and_dry_run_to_success():
    assert daily_run_exit_code(_plan(passed=True, dry_run=False)) == 0
    assert daily_run_exit_code(_plan(passed=True, dry_run=True)) == 0


def test_daily_run_exit_code_distinguishes_blocker_and_warning():
    assert daily_run_exit_code(_plan(passed=False, check_name="data_gaps")) == 1
    assert daily_run_exit_code(_plan(passed=False, check_name="history_ready")) == 2


def test_build_daily_run_command_response_points_to_artifact(tmp_path):
    plan = _plan(passed=True)
    artifact = write_daily_run_artifact(plan, directory=tmp_path)

    response = build_daily_run_command_response(plan=plan, artifact=artifact)

    assert response.status == "ready"
    assert response.exit_code == 0
    assert response.artifact_path == artifact.path
    assert "status=ready" in response.message


def test_write_daily_run_command_response_creates_artifact(tmp_path):
    response = write_daily_run_command_response(plan=_plan(passed=False), artifact_dir=tmp_path)

    assert response.status == "blocked"
    assert response.exit_code == 1
    assert response.artifact_path.exists()
