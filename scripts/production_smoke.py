from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.settings import settings
from scripts.db_backup import backup_database


@dataclass
class SmokeCheck:
    name: str
    status: str
    passed: bool
    detail: str


def _status_from_bool(passed: bool) -> str:
    return "pass" if passed else "fail"


def evaluate_smoke_results(payloads: dict[str, dict[str, Any]], migration_ok: bool, backup_report: dict[str, Any] | None = None, strict_production: bool = False) -> dict[str, Any]:
    ready = payloads.get("ready") or {}
    ops = payloads.get("ops") or {}
    acceptance = payloads.get("acceptance") or {}
    risk = payloads.get("risk") or {}
    provenance = payloads.get("provenance") or {}
    recommendations = payloads.get("recommendations") or {}
    review = payloads.get("recommendation_review") or {}
    stock_analysis = payloads.get("stock_analysis") or {}
    backup = backup_report or {"status": "skipped", "passed": True, "detail": "backup check skipped"}
    recommendation_items = recommendations.get("recommendations") or []
    review_items = review.get("items") or []
    stock_recommendation = stock_analysis.get("recommendation") or {}
    stock_quote = stock_analysis.get("latest_quote") or {}
    recommendation_workflow = ready.get("recommendation_workflow") or {}
    feishu_job = recommendation_workflow.get("feishu_signal_job") or {}
    lark_cli = recommendation_workflow.get("lark_cli") or {}
    feishu_passed = (
        recommendation_workflow.get("passed") is True
        and feishu_job.get("ready") is True
        and lark_cli.get("available") is True
        and (feishu_job.get("live_ready") is True if strict_production else feishu_job.get("exists") is True)
    )
    feishu_detail = (
        f"workflow={recommendation_workflow.get('status')} send_mode={feishu_job.get('send_mode')} "
        f"live_ready={feishu_job.get('live_ready')} lark_cli={lark_cli.get('available')}"
    )
    checks = [
        SmokeCheck("migration_current", _status_from_bool(migration_ok), migration_ok, "Alembic revision matches migration head."),
        SmokeCheck("ready", ready.get("status") or "missing", ready.get("status") == "ready", f"ready status={ready.get('status')}"),
        SmokeCheck("ops_status", ops.get("status") or "missing", ops.get("status") == "ready", f"ops status={ops.get('status')}"),
        SmokeCheck(
            "production_acceptance",
            acceptance.get("decision") or "missing",
            acceptance.get("decision") == "accepted_for_paper_observation" and acceptance.get("required_passed") == acceptance.get("required_total"),
            f"decision={acceptance.get('decision')} required={acceptance.get('required_passed')}/{acceptance.get('required_total')}",
        ),
        SmokeCheck("paper_risk_events", risk.get("status") or "missing", risk.get("status") in {"clear", "watch"}, f"risk status={risk.get('status')} events={risk.get('event_count')}"),
        SmokeCheck("data_provenance", provenance.get("status") or "missing", provenance.get("status") == "ready", f"provenance status={provenance.get('status')}"),
        SmokeCheck("realtime_recommendations", recommendations.get("status") or "missing", recommendations.get("status") == "ready" and len(recommendation_items) > 0 and recommendations.get("paper_only") is True, f"recommendations status={recommendations.get('status')} count={len(recommendation_items)}"),
        SmokeCheck("yesterday_recommendation_review", review.get("status") or "missing", review.get("status") == "ready" and len(review_items) > 0 and review.get("paper_only") is True, f"review status={review.get('status')} count={len(review_items)}"),
        SmokeCheck("stock_analysis", "ready" if stock_analysis.get("found") else stock_analysis.get("reason") or "missing", stock_analysis.get("found") is True and bool(stock_recommendation.get("action")) and bool(stock_quote.get("close")) and stock_analysis.get("paper_only") is True, f"stock found={stock_analysis.get('found')} action={stock_recommendation.get('action')} close={stock_quote.get('close')}"),
        SmokeCheck("feishu_signal_workflow", "ready" if feishu_passed else recommendation_workflow.get("status") or "missing", feishu_passed, feishu_detail),
        SmokeCheck("database_backup_dry_run", backup.get("status") or "missing", bool(backup.get("passed")), backup.get("detail") or f"backup status={backup.get('status')}"),
    ]
    failed = [check for check in checks if not check.passed]
    return {
        "status": "ready" if not failed else "failed",
        "paper_only": True,
        "strict_production": bool(strict_production),
        "checks": [check.__dict__ for check in checks],
        "failed": [check.name for check in failed],
        "summary": {
            "ready": ready.get("status"),
            "ops": ops.get("status"),
            "acceptance": acceptance.get("decision"),
            "risk": risk.get("status"),
            "risk_events": risk.get("event_count"),
            "data_provenance": provenance.get("status"),
            "realtime_recommendations": recommendations.get("status"),
            "recommendation_count": len(recommendation_items),
            "recommendation_review": review.get("status"),
            "stock_analysis": "ready" if stock_analysis.get("found") else stock_analysis.get("reason"),
            "feishu_signal": "live_ready" if feishu_job.get("live_ready") else feishu_job.get("send_mode") or "missing",
            "database_backup": backup.get("status"),
            "ops_action_items": len(ops.get("action_items") or []),
        },
        "warning": "Smoke check only validates research, backtest, recommendations, stock analysis, data, LLM optimization, and paper-observation readiness; it never places real orders and is not investment advice.",
    }


def _fetch_json(base_url: str, path: str, token: str | None = None, admin_email: str | None = None, timeout: float = 20.0) -> dict[str, Any]:
    request = urllib.request.Request(base_url.rstrip("/") + path)
    if token:
        request.add_header("X-Zi-Api-Token", token)
    if admin_email:
        request.add_header("X-Zi-User-Email", admin_email)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": "http_error", "code": exc.code, "body": body[:1000]}
    except Exception as exc:
        return {"status": "request_error", "error": type(exc).__name__, "detail": str(exc)}


def _migration_current() -> bool:
    result = subprocess.run([sys.executable, "scripts/check_migrations.py"], check=False, capture_output=True, text=True)
    return result.returncode == 0 and "migration_current" in result.stdout


def _backup_dry_run_check(output_dir: str) -> dict[str, Any]:
    if not shutil.which("pg_dump"):
        return {"status": "missing_pg_dump", "passed": False, "detail": "pg_dump is not available on PATH"}
    try:
        report = backup_database(settings.database_url, Path(output_dir), dry_run=True)
    except Exception as exc:
        return {"status": "error", "passed": False, "detail": f"{type(exc).__name__}: {exc}"}
    command = report.get("command") or []
    passed = (
        report.get("status") == "dry_run"
        and report.get("format") == "pg_dump_custom"
        and report.get("paper_only") is True
        and "--dbname" in command
    )
    return {
        "status": "ready" if passed else "failed",
        "passed": passed,
        "detail": f"dry_run={report.get('status')} format={report.get('format')} output={report.get('output_path')}",
    }


def run_smoke(base_url: str, token: str | None, admin_email: str, timeout: float, backup_check: bool = True, backup_output_dir: str = "/tmp/zi-quant-smoke-backups", strict_production: bool = False) -> dict[str, Any]:
    acceptance_path = "/api/admin/production-acceptance?strict_production=true" if strict_production else "/api/admin/production-acceptance"
    payloads = {
        "ready": _fetch_json(base_url, "/ready", token=token, timeout=timeout),
        "ops": _fetch_json(base_url, "/api/admin/ops-status", token=token, admin_email=admin_email, timeout=timeout),
        "acceptance": _fetch_json(base_url, acceptance_path, token=token, admin_email=admin_email, timeout=timeout),
        "risk": _fetch_json(base_url, "/api/risk/events?limit=50", timeout=timeout),
        "provenance": _fetch_json(base_url, "/api/data/provenance", timeout=timeout),
        "recommendations": _fetch_json(base_url, "/api/recommendations/realtime?limit=5", timeout=timeout),
        "recommendation_review": _fetch_json(base_url, "/api/recommendations/yesterday-review?limit=5", timeout=timeout),
        "stock_analysis": _fetch_json(base_url, "/api/stocks/analyze?symbol=600519.SH", timeout=timeout),
    }
    backup_report = _backup_dry_run_check(backup_output_dir) if backup_check else None
    return evaluate_smoke_results(payloads, migration_ok=_migration_current(), backup_report=backup_report, strict_production=strict_production)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ZiQuant production smoke checks against a running service.")
    parser.add_argument("--base-url", default=os.getenv("ZI_SMOKE_BASE_URL", "http://127.0.0.1:8092"))
    parser.add_argument("--token-env", default="ZI_API_TOKEN", help="Environment variable containing the API token.")
    parser.add_argument("--admin-email", default=os.getenv("ZI_SMOKE_ADMIN_EMAIL", "admin@local.zicode"))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--backup-output-dir", default=os.getenv("ZI_SMOKE_BACKUP_DIR", "/tmp/zi-quant-smoke-backups"))
    parser.add_argument("--skip-backup-check", action="store_true")
    parser.add_argument("--strict-production", action="store_true", help="Require production deployment profile in acceptance.")
    args = parser.parse_args()
    report = run_smoke(args.base_url, os.getenv(args.token_env), args.admin_email, args.timeout, backup_check=not args.skip_backup_check, backup_output_dir=args.backup_output_dir, strict_production=args.strict_production)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
