from app.models import table_names
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException

import app.services as services_module
from app.main import api_token_valid, require_admin_for_public_resource, require_platform_operator_role
from app.models import AdminAuditLog, BacktestRun, DataJob, DataJobRun, DataSourceConfig, FinancialReport, JobStatus, MarketBar, PaperEquitySnapshot, PaperOrder, PaperPortfolio, PaperPosition, Strategy, StrategyExperiment, StrategyOptimizationRun, User, UserRole, Visibility
from app.services import SUPPORTED_DATA_JOB_TYPES, FactorRow, _alpha_grid_candidates, _alpha_search_score, _apply_financial_quality, _apply_parameter_changes, _buy_rejection_reason, _candidate_base_rule, _candidate_source_strategy_id, _compare_backtest_metrics, _cron_schedule_matches, _data_job_payload, _data_job_run_diagnostic, _data_job_start_blocker, _data_source_capability_row, _data_source_capability_status, _eastmoney_secid, _equal_weight_benchmark, _extract_qveris_rows, _filter_tradable_buy_candidates, _freshness_status, _limit_state, _market_bar_volume_shares, _market_breadth, _market_factor_from_bars, _merge_strategy_rule_config, _metric_driven_parameter_changes, _normalize_bar_rows, _normalize_data_source_config, _normalize_eastmoney_kline_rows, _normalize_financial_rows, _normalize_eastmoney_stock_rows, _normalize_optimization_result, _operations_status_level, _out_of_sample_performance, _paper_order_audit_payload, _paper_portfolio_health_from_rows, _paper_rebalance_order_plan, _portfolio_performance_from_snapshots, _portfolio_risk_config, _qveris_call_telemetry, _qveris_response_usage, _rank_percentiles, _readiness_status, _rebalance_due, _record_qveris_call, _redact_data_source_config, _research_action_result_summary, _sector_exposure_after_order, _slippage_price, _stock_universe_job_params, _strategy_backtest_params, _strategy_research_job_params, _strategy_optimization_loop_health, _uuid_or_none, _visibility_after_promotion, _volume_limited_lot_shares, _walk_forward_stability, admin_audit_log_payload, apply_research_history_to_readiness, build_seed_stocks, built_in_real_stock_supplements, compute_factor, data_job_due, data_job_due_or_recent_missed, data_job_recent_missed_due, data_quality_targets, data_source_config_payload, deployment_config_status, integration_config_status, latest_research_history_hint, paper_equity_snapshot_payload, paper_rebalance_execution_guard, paper_rebalance_observation_payload, production_readiness_audit_payload, strategy_effectiveness_evidence, strategy_experiment_payload, strategy_health_from_metrics, strategy_health_repair_plan, strategy_next_research_action_plan, strategy_promotion_candidate_payload, strategy_promotion_readiness, strategy_repair_timeline_payload, synthetic_bars, user_payload
from app.services import production_acceptance_report_payload
from app.services import _paper_risk_events_for_portfolio
from app.services import _data_provenance_status
from app.services import _feishu_live_send_preflight, _format_feishu_signal_message, _recommendation_sort_key, _stock_recommendation_from_factor
from app.services import _feishu_signal_job_params


def test_seed_pool_has_500_unique_stocks():
    stocks = build_seed_stocks()
    assert len(stocks) == 500
    assert len({s["symbol"] for s in stocks}) == 500
    assert stocks[0]["symbol"] == "600519.SH"


def test_core_seed_stocks_are_bootstrap_candidates():
    stocks = build_seed_stocks()
    core = {row["symbol"] for row in stocks[:10]}
    assert {"600519.SH", "300750.SZ", "688981.SH"}.issubset(core)


def test_real_stock_supplements_are_tradeable_names():
    rows = built_in_real_stock_supplements()
    assert len(rows) >= 30
    assert {"600519.SH", "300750.SZ"}.isdisjoint({row["symbol"] for row in rows})
    assert all("样本" not in row["name"] and "退市" not in row["name"] and not row["name"].upper().startswith(("ST", "*ST")) for row in rows)


def test_factor_computation_shape():
    class S:
        symbol = "600519.SH"
        name = "贵州茅台"
        sector = "白酒食品"

    row = compute_factor(S())
    assert row.symbol == "600519.SH"
    assert isinstance(row.score, float)


def test_schema_contains_core_tables():
    names = table_names()
    assert "zi_quant_users" in names
    assert "zi_quant_stock_pools" in names
    assert "zi_quant_data_source_configs" in names
    assert "zi_quant_paper_portfolios" in names
    assert "zi_quant_paper_positions" in names
    assert "zi_quant_market_bars" in names
    assert "zi_quant_backtest_runs" in names
    assert "zi_quant_strategy_optimization_runs" in names
    assert "zi_quant_data_job_runs" in names
    assert "zi_quant_strategy_experiments" in names
    assert "zi_quant_paper_equity_snapshots" in names


def test_api_token_valid_fails_closed_and_matches_exactly():
    assert api_token_valid("", None) is False
    assert api_token_valid("", "anything") is False
    assert api_token_valid("secret-token", None) is False
    assert api_token_valid("secret-token", "wrong") is False
    assert api_token_valid("secret-token", "secret-token") is True


def test_platform_write_role_requires_admin_or_operator():
    researcher = User(email="r@example.com", display_name="r", role=UserRole.researcher)
    operator = User(email="o@example.com", display_name="o", role=UserRole.operator)
    admin = User(email="a@example.com", display_name="a", role=UserRole.admin)

    with pytest.raises(HTTPException) as exc:
        require_platform_operator_role(researcher)
    assert exc.value.status_code == 403
    assert exc.value.detail == {"reason": "platform_operator_required"}

    require_platform_operator_role(operator)
    require_platform_operator_role(admin)


def test_public_resource_write_requires_admin():
    researcher = User(email="r@example.com", display_name="r", role=UserRole.researcher)
    operator = User(email="o@example.com", display_name="o", role=UserRole.operator)
    admin = User(email="a@example.com", display_name="a", role=UserRole.admin)

    require_admin_for_public_resource(researcher, Visibility.private)
    require_admin_for_public_resource(operator, Visibility.private)
    require_admin_for_public_resource(admin, Visibility.public)

    with pytest.raises(HTTPException) as researcher_exc:
        require_admin_for_public_resource(researcher, Visibility.public)
    assert researcher_exc.value.status_code == 403
    assert researcher_exc.value.detail == {"reason": "admin_required_for_public_resource"}

    with pytest.raises(HTTPException) as operator_exc:
        require_admin_for_public_resource(operator, Visibility.public)
    assert operator_exc.value.status_code == 403
    assert operator_exc.value.detail == {"reason": "admin_required_for_public_resource"}


def test_data_source_config_redacts_secret_values():
    redacted = _redact_data_source_config({"api_key": "secret", "nested": {"token": "secret2", "safe": "ok"}})
    assert redacted == {"api_key": "***redacted***", "nested": {"token": "***redacted***", "safe": "ok"}}


def test_data_source_config_normalization_strips_inline_secrets():
    normalized, stripped = _normalize_data_source_config({"api_key": "secret", "tools": {"daily": "tool"}, "nested": {"password": "pw"}})
    assert normalized["api_key"] == "***managed-by-secret-ref***"
    assert normalized["nested"]["password"] == "***managed-by-secret-ref***"
    assert normalized["tools"]["daily"] == "tool"
    assert stripped == ["api_key", "password"]


def test_data_source_payload_is_redacted():
    source = DataSourceConfig(name="Tushare", adapter="tushare", enabled=True, priority=20, config_json={"token": "secret"}, secret_ref="env:TUSHARE_TOKEN", last_status={"password": "pw"})
    payload = data_source_config_payload(source)
    assert payload["config"]["token"] == "***redacted***"
    assert payload["last_status"]["password"] == "***redacted***"
    assert payload["has_secret_ref"] is True


def test_integration_config_status_exposes_only_safe_metadata(monkeypatch):
    monkeypatch.setattr("app.services.settings.qveris_data_api_key", "secret-qveris")
    monkeypatch.setattr("app.services.settings.qveris_base_url", "https://qveris.example/api/v1")
    monkeypatch.setattr("app.services.settings.deepseek_api_key", "secret-deepseek")
    monkeypatch.setattr("app.services.settings.deepseek_base_url", "https://deepseek.example")
    monkeypatch.setattr("app.services.settings.deepseek_model", "deepseek-v4-pro")
    monkeypatch.setattr("app.services.settings.zi_api_token", "secret-token")
    source = DataSourceConfig(
        name="QVeris 数据接口",
        adapter="qveris",
        enabled=True,
        config_json={"discovery": False, "tools": {"historical_bars": "tool-a", "financial_report": "tool-b"}},
    )
    status = integration_config_status(source)
    assert status["status"] == "ready"
    assert status["qveris"]["api_key_configured"] is True
    assert status["qveris"]["base_url_host"] == "qveris.example"
    assert status["qveris"]["prepared_tool_count"] == 2
    assert status["deepseek"]["model"] == "deepseek-v4-pro"
    assert "secret" not in str(status)


def test_deployment_config_status_requires_explicit_migration_in_production(monkeypatch):
    monkeypatch.setattr("app.services.settings.zi_deployment_mode", "production")
    monkeypatch.setattr("app.services.settings.auto_create_schema", True)
    blocked = deployment_config_status()
    assert blocked["status"] == "degraded"
    assert blocked["production_safe"] is False
    assert blocked["reasons"] == ["auto_create_schema_enabled_in_production"]
    assert blocked["next_action"] == "set_auto_create_schema_false"

    monkeypatch.setattr("app.services.settings.auto_create_schema", False)
    ready = deployment_config_status()
    assert ready["status"] == "ready"
    assert ready["production_safe"] is True


def test_data_source_capability_row_tracks_ready_default_chain(monkeypatch):
    monkeypatch.setattr("app.services.settings.qveris_data_api_key", "configured")
    qveris = DataSourceConfig(
        name="QVeris 数据接口",
        adapter="qveris",
        enabled=True,
        config_json={"discovery": False, "tools": {"historical_bars": "tool-a", "financial_report": "tool-b"}},
    )
    row = _data_source_capability_row(qveris, "qveris", {"qveris": 100}, {"qveris": 10}, {})
    assert row["status"] == "ready"
    assert row["production_ready"] is True
    assert row["prepared_tool_count"] == 2
    assert row["discovery_disabled"] is True
    assert row["observed_rows"]["market_bars"] == 100
    assert "configured" not in row.get("prepared_tool_keys", [])


def test_data_source_capability_row_requires_secret_ref_for_replaceable_adapters():
    tushare = DataSourceConfig(name="Tushare", adapter="tushare", enabled=True, config_json={"apis": ["daily"]})
    row = _data_source_capability_row(tushare, "tushare", {}, {}, {})
    assert row["status"] == "degraded"
    assert row["production_ready"] is False
    assert row["missing"] == ["secret_ref"]
    assert row["next_action"] == "set_secret_ref"


def test_data_provenance_status_requires_real_rows_and_low_fallback_ratio():
    ready = _data_provenance_status(
        {"fallback_bar_ratio": 0.02, "targets": {"max_fallback_bar_ratio": 0.05}},
        [{"source": "qveris", "rows": 100}, {"source": "simulated_fallback", "rows": 2}],
        [{"source": "qveris", "rows": 20}],
    )
    assert ready["status"] == "ready"
    assert ready["real_market_rows"] == 100
    assert ready["real_financial_rows"] == 20
    assert ready["missing"] == []

    degraded = _data_provenance_status(
        {"fallback_bar_ratio": 0.2, "targets": {"max_fallback_bar_ratio": 0.05}},
        [{"source": "simulated_fallback", "rows": 100}],
        [],
    )
    assert degraded["status"] == "degraded"
    assert set(degraded["missing"]) == {"real_market_rows", "real_financial_rows", "fallback_ratio"}


def test_qveris_call_telemetry_tracks_usage_success_empty_and_errors():
    telemetry = _qveris_call_telemetry("tool-a", "search-1")

    _record_qveris_call(telemetry, payload={"usage": {"cost": 1.25, "remaining_credits": 98}}, row_count=3)
    _record_qveris_call(telemetry, payload={"metadata": {"credits_used": 0.75, "credits_remaining": 97}}, row_count=0)
    _record_qveris_call(telemetry, error="HTTPStatusError")

    assert telemetry["tool_id"] == "tool-a"
    assert telemetry["search_id_cached"] is True
    assert telemetry["attempted"] == 3
    assert telemetry["success"] == 1
    assert telemetry["empty"] == 1
    assert telemetry["errors"] == 1
    assert telemetry["cost"] == 2.0
    assert telemetry["remaining_credits"] == 97
    assert telemetry["last_error"] == "HTTPStatusError"
    assert "secret" not in str(telemetry).lower()


def test_qveris_response_usage_handles_top_level_and_missing_payloads():
    assert _qveris_response_usage({"cost": 2, "remainingCredits": 30}) == {"cost": 2, "remaining_credits": 30}
    assert _qveris_response_usage({"data": []}) == {}
    assert _qveris_response_usage(None) == {}


def test_data_source_capability_status_requires_core_capabilities(monkeypatch):
    monkeypatch.setattr("app.services.settings.qveris_data_api_key", "configured")
    qveris = _data_source_capability_row(
        DataSourceConfig(name="QVeris 数据接口", adapter="qveris", enabled=True, config_json={"tools": {"historical_bars": "a", "financial_report": "b"}}),
        "qveris",
        {"qveris": 10},
        {"qveris": 2},
        {},
    )
    eastmoney = _data_source_capability_row(DataSourceConfig(name="东方财富公开行情", adapter="eastmoney", enabled=True), "eastmoney", {"eastmoney": 10}, {}, {"eastmoney_public": 500})
    status = _data_source_capability_status([qveris, eastmoney])
    assert status["status"] == "ready"
    assert status["default_chain_ready"] is True
    assert status["capability_coverage"]["historical_bars"] is True
    assert status["capability_coverage"]["financial_report"] is True


def test_data_job_run_model_tracks_result_payload():
    run = DataJobRun(job_name="因子刷新", job_type="factor_refresh", status=JobStatus.success, payload={"limit": 500}, result={"rows": 10}, duration_ms=12)
    assert run.__tablename__ == "zi_quant_data_job_runs"
    assert run.status == JobStatus.success
    assert run.result["rows"] == 10


def test_data_job_run_diagnostic_summarizes_common_run_states():
    success = DataJobRun(job_name="策略研究", job_type="strategy_research", status=JobStatus.success, result={"plan_action": "paper_observe", "paper_observations": [{}, {}]})
    success_diag = _data_job_run_diagnostic(success)
    assert success_diag["category"] == "strategy_observation"
    assert success_diag["suggested_action"] == "paper_observe"
    assert "2 个组合" in success_diag["summary"]

    failed = DataJobRun(job_name="行情", job_type="quote", status=JobStatus.failed, result={"error": "stale_running_timeout"})
    failed_diag = _data_job_run_diagnostic(failed)
    assert failed_diag["category"] == "stale_timeout"
    assert failed_diag["retryable"] is True

    running = DataJobRun(job_name="回测", job_type="backtest", status=JobStatus.running, started_at=datetime(2026, 6, 11, tzinfo=UTC))
    running_diag = _data_job_run_diagnostic(running)
    assert running_diag["category"] in {"running", "stale_running"}
    assert running_diag["retryable"] is False


def test_supported_data_jobs_include_paper_snapshot():
    assert "paper_snapshot" in SUPPORTED_DATA_JOB_TYPES
    assert "strategy_research" in SUPPORTED_DATA_JOB_TYPES
    assert "feishu_signal" in SUPPORTED_DATA_JOB_TYPES
    assert {"market_bars", "financial_report", "factor_refresh", "backtest"}.issubset(SUPPORTED_DATA_JOB_TYPES)


def test_strategy_research_job_params_are_bounded_for_scheduled_runs():
    params = _strategy_research_job_params({"days": 9999, "initial_cash": 100, "max_symbols": 999, "max_trials": 99, "max_portfolios": 99, "paper_observe": False})
    assert params["days"] == 1800
    assert params["initial_cash"] == 1000.0
    assert params["max_symbols"] == 500
    assert params["max_trials"] == 30
    assert params["max_portfolios"] == 50
    assert params["paper_observe"] is False


def _health_strategy() -> Strategy:
    return Strategy(id=uuid.uuid4(), name="启用策略", visibility=Visibility.public, status="active")


def _health_backtest(metrics: dict) -> BacktestRun:
    return BacktestRun(
        id=uuid.uuid4(),
        strategy_id=uuid.uuid4(),
        name="策略健康回测",
        start_date=date(2025, 1, 1),
        end_date=date(2026, 6, 1),
        status="success",
        metrics=metrics,
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
    )


def test_strategy_health_accepts_valid_active_strategy_metrics():
    health = strategy_health_from_metrics(
        _health_strategy(),
        _health_backtest({
            "total_return": 0.18,
            "benchmark_return": 0.10,
            "alpha_return": 0.08,
            "max_drawdown": 0.12,
            "sharpe": 1.2,
            "trade_count": 12,
            "walk_forward_stability": {"passed": True},
            "out_of_sample": {"passed": True, "return": 0.05, "benchmark_return": 0.02, "alpha_return": 0.03},
        }),
    )
    assert health["status"] == "ready"
    assert health["passed"] is True
    assert health["metrics"]["alpha_return"] == 0.08
    assert health["effectiveness_evidence"]["verdict"] == "validated_for_paper_observation"
    assert "样本外 Alpha 为正" in health["effectiveness_evidence"]["strengths"]
    assert health["effectiveness_evidence"]["required_action"] == "paper_observe"


def test_strategy_health_degrades_when_backtest_missing():
    health = strategy_health_from_metrics(_health_strategy(), None)
    assert health["status"] == "degraded"
    assert health["passed"] is False
    assert "缺少成功回测" in health["reasons"][0]
    assert health["effectiveness_evidence"]["verdict"] == "missing_backtest"
    assert health["effectiveness_evidence"]["required_action"] == "run_formal_backtest"


def test_strategy_effectiveness_evidence_tracks_residual_risk_for_low_trade_count():
    backtest = _health_backtest({"total_return": 0.1})
    evidence = strategy_effectiveness_evidence(
        "ready",
        [],
        {"alpha_return": 0.05, "out_of_sample_alpha_return": 0.02, "walk_forward_passed": True, "trade_count": 5},
        backtest,
        {"id": "experiment-1", "passed": True},
    )
    assert evidence["confidence"] == "high"
    assert evidence["evidence_refs"]["backtest_run_id"] == str(backtest.id)
    assert evidence["evidence_refs"]["experiment_id"] == "experiment-1"
    assert "交易次数偏少" in evidence["residual_risks"][0]


def test_strategy_health_rejects_negative_out_of_sample_alpha():
    health = strategy_health_from_metrics(
        _health_strategy(),
        _health_backtest({
            "total_return": 0.06,
            "benchmark_return": 0.12,
            "alpha_return": -0.06,
            "max_drawdown": 0.16,
            "sharpe": 0.8,
            "trade_count": 8,
            "walk_forward_stability": {"passed": True},
            "out_of_sample": {"passed": True, "return": 0.01, "benchmark_return": 0.08, "alpha_return": -0.07},
        }),
    )
    assert health["status"] == "rejected"
    assert health["passed"] is False
    assert any("样本外 Alpha" in reason for reason in health["reasons"])
    actions = {item["action"] for item in health["repair_plan"]}
    assert {"remediate_health", "alpha_search", "tighten_signal_quality"}.issubset(actions)


def test_strategy_health_repair_plan_for_missing_backtest_runs_backtest_first():
    plan = strategy_health_repair_plan("degraded", ["启用策略缺少成功回测记录"], {})
    assert plan[0]["action"] == "run_backtest"
    assert plan[0]["endpoint"] == "/api/backtests/run"


def test_paper_rebalance_execution_guard_blocks_unhealthy_execute_by_default():
    unhealthy = {"status": "rejected", "passed": False, "reasons": ["样本外 Alpha 低于 -5%"]}
    plan_only = paper_rebalance_execution_guard(False, unhealthy)
    blocked = paper_rebalance_execution_guard(True, unhealthy)
    overridden = paper_rebalance_execution_guard(True, unhealthy, allow_unhealthy_strategy=True)
    assert plan_only["execution_blocked"] is False
    assert blocked["execution_allowed"] is False
    assert blocked["execution_blocked"] is True
    assert "样本外 Alpha" in blocked["details"][0]
    assert overridden["execution_allowed"] is True


def test_paper_rebalance_execution_guard_allows_healthy_execute():
    healthy = {"status": "ready", "passed": True, "reasons": []}
    guard = paper_rebalance_execution_guard(True, healthy)
    assert guard["execution_allowed"] is True
    assert guard["execution_blocked"] is False


def test_paper_portfolio_health_ready_with_bound_strategy_and_fresh_snapshot():
    strategy = Strategy(id=uuid.uuid4(), name="active", status="active", visibility=Visibility.public)
    portfolio = PaperPortfolio(id=uuid.uuid4(), name="paper", strategy_id=strategy.id, visibility=Visibility.public, cash=99000)
    snapshot = PaperEquitySnapshot(
        portfolio_id=portfolio.id,
        snapshot_at=datetime(2026, 6, 11, tzinfo=UTC),
        cash=99000,
        market_value=1000,
        total_equity=100000,
        source="scheduled_close",
    )
    health = _paper_portfolio_health_from_rows(
        [portfolio],
        {strategy.id: strategy},
        {portfolio.id: snapshot},
        {portfolio.id: 1},
        {},
        {"status": "ready", "passed": True},
        now=datetime(2026, 6, 12, tzinfo=UTC),
    )
    assert health["status"] == "ready"
    assert health["observation_ready_count"] == 1
    assert health["active_strategy_bound_count"] == 1
    assert health["fresh_snapshot_count"] == 1
    assert health["next_action"] == "paper_observe"


def test_paper_portfolio_health_degrades_unbound_and_stale_snapshot():
    portfolio = PaperPortfolio(id=uuid.uuid4(), name="paper", visibility=Visibility.public, cash=100000)
    snapshot = PaperEquitySnapshot(
        portfolio_id=portfolio.id,
        snapshot_at=datetime(2026, 6, 1, tzinfo=UTC),
        cash=100000,
        market_value=0,
        total_equity=100000,
        source="manual",
    )
    health = _paper_portfolio_health_from_rows(
        [portfolio],
        {},
        {portfolio.id: snapshot},
        {},
        {},
        {"status": "ready", "passed": True},
        now=datetime(2026, 6, 12, tzinfo=UTC),
    )
    assert health["status"] == "degraded"
    assert health["unbound_portfolio_count"] == 1
    assert health["stale_snapshot_count"] == 1
    assert health["next_action"] == "bind_active_strategy"
    assert any("未绑定有效策略" in reason for reason in health["reasons"])


def test_operations_status_level_combines_readiness_strategy_and_jobs():
    ready = {"status": "ready"}
    healthy = {"status": "ready", "passed": True}
    assert _operations_status_level(ready, healthy, active_strategy_count=1, failed_job_count=0) == "ready"
    assert _operations_status_level({"status": "blocked"}, healthy, active_strategy_count=1, failed_job_count=0) == "blocked"
    assert _operations_status_level(ready, healthy, active_strategy_count=0, failed_job_count=0) == "blocked"
    assert _operations_status_level(ready, {"status": "rejected", "passed": False}, active_strategy_count=1, failed_job_count=0) == "degraded"
    assert _operations_status_level(ready, healthy, active_strategy_count=2, failed_job_count=0) == "degraded"
    assert _operations_status_level(ready, healthy, active_strategy_count=1, failed_job_count=1) == "degraded"
    assert _operations_status_level(ready, healthy, active_strategy_count=1, failed_job_count=0, stale_running_job_count=1) == "degraded"
    assert _operations_status_level(ready, healthy, active_strategy_count=1, failed_job_count=0, paper_health_status="degraded") == "degraded"


def test_strategy_repair_timeline_payload_extracts_validation_summary():
    log = AdminAuditLog(
        id=uuid.uuid4(),
        action="remediate_strategy_health",
        target="strategy-1",
        created_at=datetime(2026, 6, 11, tzinfo=UTC),
        payload={
            "health_status": "rejected",
            "optimization_id": "opt-1",
            "candidate_strategy_id": "candidate-1",
            "validation_passed": False,
            "validation": {
                "metrics": {"alpha_return": -0.12, "out_of_sample": {"alpha_return": -0.08}},
                "comparison": {"reasons": ["样本外 Alpha 低于 -5%"]},
            },
        },
    )
    payload = strategy_repair_timeline_payload(log)
    assert payload["action"] == "remediate_strategy_health"
    assert payload["summary"]["health_status"] == "rejected"
    assert payload["summary"]["candidate_strategy_id"] == "candidate-1"
    assert payload["summary"]["validation_passed"] is False
    assert payload["summary"]["alpha_return"] == -0.12
    assert payload["summary"]["out_of_sample_alpha"] == -0.08
    assert payload["summary"]["comparison_reasons"] == ["样本外 Alpha 低于 -5%"]


def test_admin_audit_log_payload_redacts_secret_fields():
    log = AdminAuditLog(
        id=uuid.uuid4(),
        action="upsert_data_source_config",
        target="qveris-default",
        created_at=datetime(2026, 6, 11, tzinfo=UTC),
        payload={
            "adapter": "qveris",
            "api_key": "secret-api-key",
            "nested": {"token": "secret-token", "password": "secret-password"},
            "safe": "visible",
        },
    )

    payload = admin_audit_log_payload(log)

    assert payload["action"] == "upsert_data_source_config"
    assert payload["payload"]["api_key"] == "***redacted***"
    assert payload["payload"]["nested"]["token"] == "***redacted***"
    assert payload["payload"]["nested"]["password"] == "***redacted***"
    assert payload["payload"]["safe"] == "visible"


def test_strategy_repair_timeline_payload_extracts_remediation_audit_summary():
    log = AdminAuditLog(
        id=uuid.uuid4(),
        action="remediate_strategy_health",
        target="strategy-1",
        created_at=datetime(2026, 6, 11, tzinfo=UTC),
        payload={
            "health_status": "rejected",
            "optimization_id": "opt-1",
            "candidate_strategy_id": "candidate-1",
            "validation_passed": False,
            "next_action": "run_alpha_search_or_adjust_constraints",
            "validation": {
                "passed": False,
                "metrics": {"alpha_return": -0.2, "out_of_sample": {"alpha_return": -0.11}},
                "comparison": {"reasons": ["候选策略相对基准没有实质改善"]},
            },
        },
    )
    payload = strategy_repair_timeline_payload(log)
    assert payload["summary"]["next_action"] == "run_alpha_search_or_adjust_constraints"
    assert payload["summary"]["alpha_return"] == -0.2
    assert payload["summary"]["out_of_sample_alpha"] == -0.11
    assert payload["summary"]["comparison_reasons"] == ["候选策略相对基准没有实质改善"]


def test_strategy_repair_timeline_payload_extracts_next_action_wrapper_summary():
    log = AdminAuditLog(
        id=uuid.uuid4(),
        action="run_next_strategy_research_action",
        target="strategy-1",
        created_at=datetime(2026, 6, 11, tzinfo=UTC),
        payload={
            "plan": {"action": "alpha_search"},
            "readiness_after": {"next_action": "remediate_health", "candidate_strategy_ids": []},
            "strategy_health_after": {"status": "rejected"},
            "result_summary": {
                "searched": True,
                "best_strategy_id": "candidate-best",
                "optimization_id": "opt-grid",
                "alpha_return": 0.04,
                "out_of_sample_alpha": 0.02,
                "trial_count": 8,
            },
        },
    )
    payload = strategy_repair_timeline_payload(log)
    assert payload["summary"]["health_status"] == "rejected"
    assert payload["summary"]["optimization_id"] == "opt-grid"
    assert payload["summary"]["candidate_strategy_id"] == "candidate-best"
    assert payload["summary"]["next_action"] == "alpha_search"
    assert payload["summary"]["alpha_return"] == 0.04
    assert payload["summary"]["out_of_sample_alpha"] == 0.02
    assert payload["summary"]["trial_count"] == 8


def test_research_action_result_summary_includes_remediation_validation_metrics():
    summary = _research_action_result_summary(
        "remediate_health",
        {
            "remediated": True,
            "candidate": {"strategy_id": "candidate-1"},
            "validation": {
                "passed": False,
                "experiment_id": "experiment-1",
                "decision": "候选策略未通过基准对比",
                "metrics": {"alpha_return": -0.12, "out_of_sample": {"alpha_return": -0.07}},
            },
            "next_action": "run_alpha_search_or_adjust_constraints",
        },
    )
    assert summary["candidate_strategy_id"] == "candidate-1"
    assert summary["validation_passed"] is False
    assert summary["experiment_id"] == "experiment-1"
    assert summary["alpha_return"] == -0.12
    assert summary["out_of_sample_alpha"] == -0.07
    assert summary["next_action"] == "run_alpha_search_or_adjust_constraints"


def test_research_action_result_summary_includes_alpha_search_validation():
    summary = _research_action_result_summary(
        "alpha_search",
        {
            "searched": True,
            "best_strategy_id": "candidate-best",
            "optimization_id": "opt-grid",
            "best": {"score": 0.12, "metrics": {"alpha_return": 0.05, "out_of_sample": {"alpha_return": 0.03}}},
            "trials": [{"strategy_id": "a"}, {"strategy_id": "b"}],
            "validation": {"passed": True, "experiment_id": "experiment-1", "decision": "候选策略相对基准通过"},
            "next_action": "promote_candidate_after_review",
        },
    )
    assert summary["best_strategy_id"] == "candidate-best"
    assert summary["validation_passed"] is True
    assert summary["experiment_id"] == "experiment-1"
    assert summary["alpha_return"] == 0.05
    assert summary["out_of_sample_alpha"] == 0.03
    assert summary["trial_count"] == 2
    assert summary["next_action"] == "promote_candidate_after_review"


def test_research_action_result_summary_includes_tighten_validation():
    summary = _research_action_result_summary(
        "tighten_signal_quality",
        {
            "tightened": True,
            "optimization": {"id": "opt-1", "status": "success", "model": "deepseek-v4-pro"},
            "candidate": {"strategy_id": "candidate-tight"},
            "validation": {
                "passed": False,
                "experiment_id": "experiment-tight",
                "decision": "候选策略未通过基准对比",
                "metrics": {"alpha_return": -0.08, "out_of_sample": {"alpha_return": -0.04}},
            },
            "next_action": "run_alpha_search_or_adjust_constraints",
        },
    )
    assert summary["tightened"] is True
    assert summary["optimization_id"] == "opt-1"
    assert summary["candidate_strategy_id"] == "candidate-tight"
    assert summary["validation_passed"] is False
    assert summary["experiment_id"] == "experiment-tight"
    assert summary["alpha_return"] == -0.08
    assert summary["out_of_sample_alpha"] == -0.04


def test_candidate_source_strategy_id_supports_llm_and_alpha_grid_candidates():
    assert _candidate_source_strategy_id({"llm_optimization": {"source_strategy_id": "source-llm"}}) == "source-llm"
    assert _candidate_source_strategy_id({"alpha_grid_search": {"source_strategy_id": "source-alpha"}}) == "source-alpha"
    assert _candidate_source_strategy_id({}) is None


def test_uuid_or_none_handles_bad_values():
    value = uuid.uuid4()
    assert _uuid_or_none(str(value)) == value
    assert _uuid_or_none("local-alpha-grid") is None
    assert _uuid_or_none(None) is None


def test_latest_research_history_hint_prefers_alpha_search_after_failed_remediation():
    hint = latest_research_history_hint(
        {
            "items": [
                {
                    "action": "remediate_strategy_health",
                    "created_at": "2026-06-11T12:19:44+00:00",
                    "summary": {
                        "validation_passed": False,
                        "next_action": "run_alpha_search_or_adjust_constraints",
                        "candidate_strategy_id": "candidate-1",
                        "alpha_return": -0.2,
                        "out_of_sample_alpha": -0.11,
                    },
                }
            ]
        }
    )
    assert hint["preferred_next_action"] == "alpha_search"
    assert hint["reason"] == "latest_remediation_failed"
    assert hint["candidate_strategy_id"] == "candidate-1"


def test_latest_research_history_hint_tightens_after_failed_alpha_search():
    hint = latest_research_history_hint(
        {
            "items": [
                {
                    "action": "run_next_strategy_research_action",
                    "created_at": "2026-06-14T12:59:50+00:00",
                    "summary": {
                        "validation_passed": False,
                        "next_action": "run_alpha_search_or_adjust_constraints",
                        "candidate_strategy_id": "candidate-alpha",
                        "alpha_return": -0.64,
                        "out_of_sample_alpha": -0.22,
                        "trial_count": 8,
                    },
                    "payload": {"plan": {"action": "alpha_search"}},
                }
            ]
        }
    )
    assert hint["preferred_next_action"] == "tighten_signal_quality"
    assert hint["reason"] == "latest_alpha_search_failed"
    assert hint["candidate_strategy_id"] == "candidate-alpha"


def test_latest_research_history_hint_marks_failed_tighten_separately():
    hint = latest_research_history_hint(
        {
            "items": [
                {
                    "action": "run_next_strategy_research_action",
                    "created_at": "2026-06-14T13:06:35+00:00",
                    "summary": {
                        "validation_passed": False,
                        "next_action": "run_alpha_search_or_adjust_constraints",
                        "candidate_strategy_id": "candidate-tight",
                        "alpha_return": -0.64,
                        "out_of_sample_alpha": -0.2,
                    },
                    "payload": {"plan": {"action": "tighten_signal_quality"}},
                }
            ]
        }
    )
    assert hint["preferred_next_action"] == "alpha_search"
    assert hint["reason"] == "latest_tighten_failed"
    assert hint["candidate_strategy_id"] == "candidate-tight"


def test_apply_research_history_to_readiness_overrides_failed_next_action():
    readiness = {"passed": False, "next_action": "remediate_health"}
    updated = apply_research_history_to_readiness(readiness, {"preferred_next_action": "alpha_search", "reason": "latest_remediation_failed"})
    assert updated["next_action"] == "alpha_search"
    assert updated["history_hint"]["reason"] == "latest_remediation_failed"


def test_strategy_promotion_candidate_payload_marks_promotable_draft():
    strategy = Strategy(
        id=uuid.uuid4(),
        name="候选策略",
        status="draft",
        visibility=Visibility.private,
        rule_json={"latest_validation": {"passed": True}},
    )
    experiment = StrategyExperiment(
        id=uuid.uuid4(),
        strategy_id=strategy.id,
        name="候选验证实验",
        passed=True,
        status="passed",
        decision="候选策略相对基准通过，可进入模拟盘观察",
        metrics={
            "alpha_return": 0.06,
            "benchmark_return": 0.12,
            "out_of_sample": {"passed": True, "return": 0.03, "alpha_return": 0.02},
            "walk_forward_stability": {"passed": True},
            "max_drawdown": 0.08,
            "sharpe": 1.6,
            "trade_count": 20,
        },
        comparison={"reasons": []},
    )
    payload = strategy_promotion_candidate_payload(experiment, strategy)
    assert payload["promotable"] is True
    assert payload["next_action"] == "promote_after_manual_review"
    assert payload["metrics"]["alpha_return"] == 0.06
    assert payload["metrics"]["out_of_sample_alpha_return"] == 0.02


def test_strategy_promotion_candidate_payload_blocks_non_draft():
    strategy = Strategy(id=uuid.uuid4(), name="已启用", status="active", visibility=Visibility.public, rule_json={"latest_validation": {"passed": True}})
    experiment = StrategyExperiment(id=uuid.uuid4(), strategy_id=strategy.id, name="验证实验", passed=True, status="passed", decision="ok", metrics={})
    payload = strategy_promotion_candidate_payload(experiment, strategy)
    assert payload["promotable"] is False
    assert payload["blocking_reasons"] == ["策略状态不是 draft：active"]


def test_strategy_promotion_readiness_passes_when_active_strategy_ready():
    readiness = strategy_promotion_readiness(
        {"items": []},
        {"status": "ready", "passed": True, "repair_plan": []},
    )
    assert readiness["passed"] is True
    assert readiness["reason"] == "active_strategy_ready"
    assert readiness["next_action"] == "paper_observe"


def test_strategy_promotion_readiness_passes_when_candidate_is_promotable():
    readiness = strategy_promotion_readiness(
        {"items": [{"strategy_id": "candidate-1", "promotable": True}]},
        {"status": "rejected", "passed": False, "repair_plan": [{"action": "alpha_search"}]},
    )
    assert readiness["passed"] is True
    assert readiness["reason"] == "promotable_candidate_available"
    assert readiness["promotable_count"] == 1
    assert readiness["candidate_strategy_ids"] == ["candidate-1"]


def test_strategy_promotion_readiness_warns_when_unhealthy_without_candidate():
    readiness = strategy_promotion_readiness(
        {"items": [{"strategy_id": "candidate-1", "promotable": False}]},
        {"status": "rejected", "passed": False, "repair_plan": [{"action": "remediate_health"}]},
    )
    assert readiness["passed"] is False
    assert readiness["reason"] == "no_promotable_candidate_for_unhealthy_strategy"
    assert readiness["candidate_count"] == 1
    assert readiness["promotable_count"] == 0
    assert readiness["next_action"] == "remediate_health"


def test_strategy_optimization_loop_health_ready_for_recent_validated_loop(monkeypatch):
    monkeypatch.setattr("app.services.settings.deepseek_api_key", "configured")
    monkeypatch.setattr("app.services.settings.deepseek_base_url", "https://deepseek.example")
    monkeypatch.setattr("app.services.settings.deepseek_model", "deepseek-v4-pro")
    now = datetime(2026, 6, 12, tzinfo=UTC)
    optimization = StrategyOptimizationRun(
        id=uuid.uuid4(),
        status="success",
        model="deepseek-v4-pro",
        result_json={"summary": "ok"},
        created_at=datetime(2026, 6, 11, tzinfo=UTC),
    )
    experiment = StrategyExperiment(
        id=uuid.uuid4(),
        name="validated",
        passed=True,
        decision="候选策略相对基准通过",
        created_at=datetime(2026, 6, 11, tzinfo=UTC),
        comparison={"deltas": {"alpha_return": 0.1}},
    )
    health = _strategy_optimization_loop_health(
        optimization,
        experiment,
        {"items": []},
        {"status": "ready", "passed": True},
        now=now,
    )
    assert health["status"] == "ready"
    assert health["loop"]["llm_suggested"] is True
    assert health["loop"]["candidate_validated"] is True
    assert health["next_action"] == "paper_observe"
    assert health["deepseek"]["model"] == "deepseek-v4-pro"


def test_strategy_optimization_loop_health_requires_llm_record(monkeypatch):
    monkeypatch.setattr("app.services.settings.deepseek_api_key", "configured")
    monkeypatch.setattr("app.services.settings.deepseek_base_url", "https://deepseek.example")
    monkeypatch.setattr("app.services.settings.deepseek_model", "deepseek-v4-pro")
    now = datetime(2026, 6, 12, tzinfo=UTC)
    local_search = StrategyOptimizationRun(
        id=uuid.uuid4(),
        status="success",
        model="local-alpha-grid",
        result_json={"summary": "grid ok"},
        created_at=datetime(2026, 6, 11, tzinfo=UTC),
    )
    experiment = StrategyExperiment(id=uuid.uuid4(), name="validated", passed=True, created_at=datetime(2026, 6, 11, tzinfo=UTC))
    health = _strategy_optimization_loop_health(
        local_search,
        experiment,
        {"items": []},
        {"status": "ready", "passed": True},
        now=now,
    )
    assert health["status"] == "degraded"
    assert health["loop"]["llm_suggested"] is False
    assert health["loop"]["local_search_latest"] is True
    assert health["next_action"] == "optimize_strategy"
    assert "缺少 DeepSeek 大模型优化记录" in health["reasons"]

    llm = StrategyOptimizationRun(
        id=uuid.uuid4(),
        status="success",
        model="deepseek-v4-pro",
        result_json={"summary": "llm ok"},
        created_at=datetime(2026, 6, 11, tzinfo=UTC),
    )
    ready = _strategy_optimization_loop_health(
        local_search,
        experiment,
        {"items": []},
        {"status": "ready", "passed": True},
        latest_llm_optimization=llm,
        now=now,
    )
    assert ready["status"] == "ready"
    assert ready["loop"]["llm_suggested"] is True
    assert ready["latest_optimization"]["model"] == "local-alpha-grid"
    assert ready["latest_llm_optimization"]["model"] == "deepseek-v4-pro"


def test_strategy_optimization_loop_health_degrades_without_model_or_records(monkeypatch):
    monkeypatch.setattr("app.services.settings.deepseek_api_key", "")
    health = _strategy_optimization_loop_health(
        None,
        None,
        {"items": []},
        {"status": "rejected", "passed": False},
        now=datetime(2026, 6, 12, tzinfo=UTC),
    )
    assert health["status"] == "degraded"
    assert health["next_action"] == "configure_deepseek"
    assert "DeepSeek 模型配置不完整" in health["reasons"]
    assert "缺少 DeepSeek 大模型优化记录" in health["reasons"]


def test_strategy_next_research_action_plan_observes_ready_strategy():
    plan = strategy_next_research_action_plan(
        {"reason": "active_strategy_ready", "next_action": "paper_observe"},
        {"status": "ready", "passed": True},
    )
    assert plan["action"] == "paper_observe"
    assert plan["executable"] is False


def test_strategy_next_research_action_plan_requires_manual_promotion():
    plan = strategy_next_research_action_plan(
        {"reason": "promotable_candidate_available", "candidate_strategy_ids": ["candidate-1"], "next_action": "promote_after_manual_review"},
        {"status": "rejected", "passed": False},
    )
    assert plan["action"] == "promote_after_manual_review"
    assert plan["executable"] is False
    assert plan["candidate_strategy_ids"] == ["candidate-1"]


def test_strategy_next_research_action_plan_executes_repair_plan_action():
    plan = strategy_next_research_action_plan(
        {"reason": "no_promotable_candidate_for_unhealthy_strategy", "next_action": "remediate_health"},
        {"status": "rejected", "passed": False, "repair_plan": [{"action": "remediate_health", "params": {"days": 900}}]},
    )
    assert plan["action"] == "remediate_health"
    assert plan["executable"] is True
    assert plan["endpoint"] == "/api/strategies/remediate-health"
    assert plan["params"] == {"days": 900}


def test_cron_schedule_matches_common_job_schedules():
    thursday_close = datetime(2026, 6, 11, 16, 0, tzinfo=UTC)
    assert _cron_schedule_matches("0 16 * * 1-5", thursday_close) is True
    assert _cron_schedule_matches("*/5 * * * 1-5", thursday_close) is True
    assert _cron_schedule_matches("0 7 * * 1-5", thursday_close) is False
    sunday = datetime(2026, 6, 14, 16, 0, tzinfo=UTC)
    assert _cron_schedule_matches("0 16 * * 1-5", sunday) is False


def test_data_job_due_skips_manual_running_and_same_minute_runs():
    now = datetime(2026, 6, 11, 16, 0, tzinfo=UTC)
    due = DataJob(name="模拟盘净值快照", job_type="paper_snapshot", schedule="0 16 * * 1-5", status=JobStatus.idle)
    assert data_job_due(due, now) is True
    due.last_run_at = datetime(2026, 6, 11, 15, 59, tzinfo=UTC)
    assert data_job_due(due, now) is True
    due.last_run_at = now
    assert data_job_due(due, now) is False
    manual = DataJob(name="手动任务", job_type="real_data_bootstrap", schedule="manual", status=JobStatus.idle)
    assert data_job_due(manual, now) is False
    running = DataJob(name="运行中", job_type="factor_refresh", schedule="0 16 * * 1-5", status=JobStatus.running)
    assert data_job_due(running, now) is False
    failed = DataJob(name="失败计划任务", job_type="quote", schedule="0 16 * * 1-5", status=JobStatus.failed)
    failed.last_run_at = datetime(2026, 6, 11, 15, 0, tzinfo=UTC)
    assert data_job_due(failed, now) is True


def test_data_job_recent_missed_due_detects_overdue_scheduled_job():
    now = datetime(2026, 6, 11, 16, 6, tzinfo=UTC)
    job = DataJob(id=uuid.uuid4(), name="实时行情刷新", job_type="quote", schedule="*/5 * * * 1-5", status=JobStatus.idle, last_run_at=datetime(2026, 6, 11, 15, 55, tzinfo=UTC))
    missed = data_job_recent_missed_due(job, now=now)
    assert missed["due_at"] == "2026-06-11T16:05:00+00:00"
    assert missed["age_minutes"] == 1
    assert missed["last_run_at"] == "2026-06-11T15:55:00+00:00"
    job.last_run_at = datetime(2026, 6, 11, 16, 5, tzinfo=UTC)
    assert data_job_recent_missed_due(job, now=now) is None
    job.schedule = "manual"
    assert data_job_recent_missed_due(job, now=now) is None


def test_data_job_due_or_recent_missed_catches_up_overdue_schedules():
    now = datetime(2026, 6, 11, 16, 6, tzinfo=UTC)
    missed = DataJob(name="实时行情刷新", job_type="quote", schedule="*/5 * * * 1-5", status=JobStatus.idle, last_run_at=datetime(2026, 6, 11, 15, 55, tzinfo=UTC))
    assert data_job_due(missed, now=now) is False
    assert data_job_due_or_recent_missed(missed, now=now) is True

    same_minute = DataJob(name="实时行情刷新", job_type="quote", schedule="*/5 * * * 1-5", status=JobStatus.idle, last_run_at=datetime(2026, 6, 11, 16, 5, tzinfo=UTC))
    assert data_job_due_or_recent_missed(same_minute, now=now) is False

    manual = DataJob(name="手动任务", job_type="real_data_bootstrap", schedule="manual", status=JobStatus.idle)
    running = DataJob(name="运行中", job_type="factor_refresh", schedule="*/5 * * * 1-5", status=JobStatus.running)
    assert data_job_due_or_recent_missed(manual, now=now) is False
    assert data_job_due_or_recent_missed(running, now=now) is False


def test_data_job_payload_exposes_ops_fields_and_blocker():
    now = datetime(2026, 6, 11, 16, 6, tzinfo=UTC)
    job = DataJob(
        id=uuid.uuid4(),
        name="实时行情刷新",
        job_type="quote",
        schedule="*/5 * * * 1-5",
        status=JobStatus.running,
        last_run_at=datetime(2026, 6, 11, 15, 55, tzinfo=UTC),
        payload={"source": "qveris"},
    )
    payload = _data_job_payload(job, now=now)
    assert payload["id"] == str(job.id)
    assert payload["type"] == "quote"
    assert payload["job_type"] == "quote"
    assert payload["manual"] is False
    assert payload["payload"] == {"source": "qveris"}
    assert payload["missed_due"] is None
    assert payload["start_blocker"]["reason"] == "job_already_running"

    manual = DataJob(id=uuid.uuid4(), name="真实数据引导", job_type="real_data_bootstrap", schedule="manual", status=JobStatus.idle)
    assert _data_job_payload(manual, now=now)["manual"] is True


def test_stock_universe_job_params_preserve_public_pool_by_default():
    assert _stock_universe_job_params({}) == {"limit": 500, "reset_public_pool": False}
    assert _stock_universe_job_params({"limit": 2000, "reset_public_pool": True}) == {"limit": 1000, "reset_public_pool": True}


def test_data_job_start_blocker_rejects_duplicate_running_job():
    job = DataJob(id=uuid.uuid4(), name="策略研究", job_type="strategy_research", schedule="30 19 * * 1-5", status=JobStatus.running, last_run_at=datetime(2026, 6, 11, 19, 30, tzinfo=UTC))
    blocked = _data_job_start_blocker(job)
    assert blocked["started"] is False
    assert blocked["reason"] == "job_already_running"
    assert blocked["job_type"] == "strategy_research"
    assert blocked["last_run_at"] == "2026-06-11T19:30:00+00:00"
    job.status = JobStatus.idle
    assert _data_job_start_blocker(job) is None


def test_feishu_signal_job_params_default_to_dry_run_and_clamp_limit(monkeypatch):
    monkeypatch.setattr(services_module.settings, "lark_signal_default_dry_run", True)
    params = _feishu_signal_job_params({"dry_run": False, "limit": 999, "chat_id": "oc_test"})

    assert params == {"chat_id": "oc_test", "limit": 20, "dry_run": False}
    assert _feishu_signal_job_params({})["dry_run"] is True


def test_feishu_signal_job_params_can_follow_live_default(monkeypatch):
    monkeypatch.setattr(services_module.settings, "lark_signal_default_dry_run", False)

    assert _feishu_signal_job_params({})["dry_run"] is False
    assert _feishu_signal_job_params({"dry_run": True})["dry_run"] is True


def test_feishu_live_send_preflight_requires_explicit_gate_chat_and_cli(monkeypatch):
    monkeypatch.setattr(services_module, "_lark_cli_available", lambda binary=None: True)
    monkeypatch.setattr(services_module.settings, "lark_signal_live_enabled", False)

    disabled = _feishu_live_send_preflight("oc_test")
    assert disabled["allowed"] is False
    assert disabled["reasons"] == ["live_send_disabled"]

    monkeypatch.setattr(services_module.settings, "lark_signal_live_enabled", True)
    missing_chat = _feishu_live_send_preflight("")
    assert missing_chat["allowed"] is False
    assert missing_chat["reasons"] == ["missing_chat_id"]

    monkeypatch.setattr(services_module, "_lark_cli_available", lambda binary=None: False)
    missing_cli = _feishu_live_send_preflight("oc_test")
    assert missing_cli["allowed"] is False
    assert missing_cli["reasons"] == ["lark_cli_unavailable"]

    monkeypatch.setattr(services_module, "_lark_cli_available", lambda binary=None: True)
    ready = _feishu_live_send_preflight("oc_test")
    assert ready["allowed"] is True
    assert ready["reasons"] == []


def test_paper_equity_snapshot_payload_and_performance():
    portfolio = PaperPortfolio(name="paper", cash=105000, config_json={"initial_cash": 100000})
    first = PaperEquitySnapshot(portfolio_id=portfolio.id, snapshot_at=datetime(2026, 6, 10, tzinfo=UTC), cash=100000, market_value=0, total_equity=100000, unrealized_pnl=0, realized_pnl=0, source="portfolio_create")
    second = PaperEquitySnapshot(portfolio_id=portfolio.id, snapshot_at=datetime(2026, 6, 11, tzinfo=UTC), cash=50000, market_value=55000, total_equity=105000, unrealized_pnl=5000, realized_pnl=0, daily_return=0.05, total_return=0.05, max_drawdown=0, source="manual_order")
    payload = paper_equity_snapshot_payload(second)
    performance = _portfolio_performance_from_snapshots([first, second], 100000)
    assert payload["total_equity"] == 105000
    assert payload["source"] == "manual_order"
    assert performance["snapshot_count"] == 2
    assert performance["total_return"] == 0.05
    assert performance["daily_return"] == 0.05


def test_user_payload_exposes_role_and_active_state():
    user = User(email="admin@example.com", display_name="Admin", role=UserRole.admin, is_active=True)
    payload = user_payload(user)
    assert payload["email"] == "admin@example.com"
    assert payload["name"] == "Admin"
    assert payload["role"] == "admin"
    assert payload["active"] is True


def test_strategy_experiment_payload_exposes_decision_and_deltas():
    experiment = StrategyExperiment(
        name="候选策略验证",
        status="passed",
        passed=True,
        decision="通过",
        metrics={"total_return": 0.2},
        baseline_metrics={"total_return": 0.1},
        comparison={"deltas": {"total_return": 0.1}},
        params={"days": 900},
    )
    payload = strategy_experiment_payload(experiment)
    assert payload["name"] == "候选策略验证"
    assert payload["passed"] is True
    assert payload["comparison"]["deltas"]["total_return"] == 0.1


def test_markdown_market_rows_normalize_to_bars():
    markdown = """
| 股票代码 | 交易日期 | 当日收盘价 | 成交量 |
| --- | --- | ---: | ---: |
| 600519.SH | 20260601 | 10.3 | 1000 |
"""
    rows = _extract_qveris_rows({"result": {"data": {"result": markdown}}})
    bars = _normalize_bar_rows("600519.SH", rows, date(2026, 1, 1), date(2026, 12, 31), "qveris")
    assert len(bars) == 1
    assert bars[0]["trade_date"] == date(2026, 6, 1)
    assert bars[0]["close"] == 10.3
    assert bars[0]["open"] == 10.3
    assert bars[0]["source"] == "qveris"


def test_eastmoney_stock_rows_normalize_to_a_share_symbols():
    rows = _normalize_eastmoney_stock_rows(
        [
            {"f12": "300894", "f13": 0, "f14": "火星人", "f100": "厨卫电器"},
            {"f12": "688010", "f13": 1, "f14": "福光股份", "f100": "光学光电子"},
            {"f12": "600001", "f13": 1, "f14": "退市测试", "f100": "其他"},
            {"f12": "000001", "f13": 0, "f14": "ST测试", "f100": "其他"},
            {"f12": "-", "f13": 1, "f14": "-", "f100": "-"},
        ],
        limit=500,
    )
    assert rows == [
        {"symbol": "300894.SZ", "name": "火星人", "sector": "厨卫电器", "market": "SZ", "lot_size": 100, "metadata_json": {"source": "eastmoney_public", "raw": {"f12": "300894", "f13": 0, "f14": "火星人", "f100": "厨卫电器"}}},
        {"symbol": "688010.SH", "name": "福光股份", "sector": "光学光电子", "market": "SH", "lot_size": 100, "metadata_json": {"source": "eastmoney_public", "raw": {"f12": "688010", "f13": 1, "f14": "福光股份", "f100": "光学光电子"}}},
    ]


def test_eastmoney_kline_rows_normalize_to_market_bars():
    assert _eastmoney_secid("600519.SH") == "1.600519"
    assert _eastmoney_secid("300750.SZ") == "0.300750"
    payload = {"data": {"klines": ["2024-01-02,1608.68,1578.69,1611.87,1571.78,32156,5440082548.00,2.48,-2.53,-40.99,0.26"]}}
    bars = _normalize_eastmoney_kline_rows("600519.SH", payload, date(2024, 1, 1), date(2024, 1, 31))
    assert bars == [
        {
            "symbol": "600519.SH",
            "trade_date": date(2024, 1, 2),
            "frequency": "1d",
            "open": 1608.68,
            "high": 1611.87,
            "low": 1571.78,
            "close": 1578.69,
            "volume": 3215600.0,
            "amount": 5440082548.0,
            "source": "eastmoney",
            "payload": {"raw": "2024-01-02,1608.68,1578.69,1611.87,1571.78,32156,5440082548.00,2.48,-2.53,-40.99,0.26", "fq": "qfq", "raw_volume": 32156.0, "volume_unit": "shares"},
        }
    ]


def test_market_bar_volume_shares_keeps_new_rows_and_converts_legacy_eastmoney_lots():
    legacy = MarketBar(symbol="600519.SH", trade_date=date(2024, 1, 2), open=10, high=11, low=9, close=10, volume=32156, source="eastmoney", payload={"fq": "qfq"})
    normalized = MarketBar(symbol="600519.SH", trade_date=date(2024, 1, 2), open=10, high=11, low=9, close=10, volume=3215600, source="eastmoney", payload={"volume_unit": "shares"})
    qveris = MarketBar(symbol="600519.SH", trade_date=date(2024, 1, 2), open=10, high=11, low=9, close=10, volume=3215600, source="qveris", payload={})
    assert _market_bar_volume_shares(legacy) == 3215600
    assert _market_bar_volume_shares(normalized) == 3215600
    assert _market_bar_volume_shares(qveris) == 3215600


def test_markdown_financial_rows_normalize_to_reports():
    markdown = """
| 股票代码 | 报告期 | 营业收入 | 归母净利润 | 净资产收益率 |
| --- | --- | ---: | ---: | ---: |
| 600519.SH | 2025-12-31 | 1500000000 | 600000000 | 28.5 |
"""
    rows = _extract_qveris_rows({"result": {"data": {"result": markdown}}})
    reports = _normalize_financial_rows("600519.SH", rows, "qveris")
    assert len(reports) == 1
    assert reports[0]["report_date"] == date(2025, 12, 31)
    assert reports[0]["revenue"] == 1500000000
    assert reports[0]["net_profit"] == 600000000
    assert reports[0]["roe"] == 28.5
    assert reports[0]["source"] == "qveris"


def test_qveris_financial_long_chinese_headers_normalize():
    markdown = """
| 股票代码 | 股票名称 | 交易日期 | 营业收入(累计值，合并报表)（元） | 归母净利润(累计值，合并报表)（元） |
| --- | --- | --- | ---: | ---: |
| 300750.SZ | 宁德时代 | 20260331 | 129131041000.0000 | 20737710000.0000 |
"""
    rows = _extract_qveris_rows({"data": {"result": {"data": {"result": markdown}}}})
    reports = _normalize_financial_rows("300750.SZ", rows, "qveris")
    assert len(reports) == 1
    assert reports[0]["report_date"] == date(2026, 3, 31)
    assert reports[0]["revenue"] == 129131041000
    assert reports[0]["net_profit"] == 20737710000


def test_synthetic_bars_mark_source_as_fallback():
    bars = synthetic_bars("600519.SH", date(2026, 6, 1), date(2026, 6, 7))
    assert bars
    assert {bar["source"] for bar in bars} == {"simulated_fallback"}


def test_market_factor_uses_bar_history():
    class S:
        symbol = "600519.SH"
        name = "贵州茅台"
        sector = "白酒食品"

    class B:
        def __init__(self, i):
            self.trade_date = date(2026, 1, i + 1)
            self.close = 10 + i * 0.1

    row = _market_factor_from_bars(S(), [B(i) for i in range(25)])
    assert row is not None
    assert row.price == 12.4
    assert row.momentum_20d > 0


def test_market_factor_rejects_price_discontinuity():
    class S:
        symbol = "600519.SH"
        name = "贵州茅台"
        sector = "白酒食品"

    class B:
        def __init__(self, i, close):
            self.trade_date = date(2026, 1, i + 1)
            self.close = close

    bars = [B(i, 10 + i * 0.1) for i in range(24)] + [B(24, 30)]
    assert _market_factor_from_bars(S(), bars) is None


def test_financial_quality_adjusts_factor_row_from_real_reports():
    class S:
        symbol = "600519.SH"
        name = "贵州茅台"
        sector = "白酒食品"

    base = compute_factor(S())
    adjusted = _apply_financial_quality(
        base,
        [
            FinancialReport(symbol="600519.SH", report_date=date(2026, 3, 31), report_type="income", revenue=1000, net_profit=420, roe=None, source="qveris"),
            FinancialReport(symbol="600519.SH", report_date=date(2025, 12, 31), report_type="income", revenue=3000, net_profit=1200, roe=None, source="qveris"),
            FinancialReport(symbol="600519.SH", report_date=date(2025, 3, 31), report_type="income", revenue=900, net_profit=360, roe=None, source="qveris"),
        ],
    )
    assert adjusted.quality_source == "financial_report:qveris"
    assert adjusted.net_margin == 0.42
    assert adjusted.revenue_growth == 0.1111
    assert adjusted.quality != base.quality
    assert adjusted.score != base.score


def test_portfolio_risk_config_defaults_and_overrides():
    default = _portfolio_risk_config(PaperPortfolio(name="p"))
    assert default["max_single_position_pct"] == 0.2
    custom = _portfolio_risk_config(PaperPortfolio(name="p", config_json={"risk": {"max_order_pct": 0.05}}))
    assert custom["max_order_pct"] == 0.05
    assert custom["min_cash_pct"] == 0.01
    assert custom["max_drawdown_pct"] == 0.15


def test_paper_risk_events_for_portfolio_flags_reviewable_events():
    portfolio = PaperPortfolio(
        id=uuid.uuid4(),
        name="公共模拟盘",
        visibility=Visibility.public,
        cash=500,
        config_json={"risk": {"max_single_position_pct": 0.2, "min_cash_pct": 0.02, "max_drawdown_pct": 0.12, "daily_loss_pct": 0.03}},
    )
    strategy = Strategy(
        id=uuid.uuid4(),
        name="风控策略",
        rule_json={"risk": {"stop_loss": 0.08, "take_profit": 0.3}},
    )
    valuation = {
        "cash": 500,
        "total_equity": 100000,
        "positions": [
            {"symbol": "000001.SZ", "name": "平安银行", "avg_cost": 10, "last_price": 9.1, "market_value": 45500, "price_source": "qveris"},
            {"symbol": "600519.SH", "name": "贵州茅台", "avg_cost": 1000, "last_price": 1350, "market_value": 27000, "price_source": "synthetic_fallback"},
        ],
    }
    events = _paper_risk_events_for_portfolio(
        portfolio,
        valuation,
        {"max_drawdown": 0.18, "daily_return": -0.04},
        strategy,
    )
    event_types = {event["event_type"] for event in events}
    assert {
        "portfolio_drawdown",
        "daily_loss",
        "low_cash",
        "position_stop_loss",
        "position_take_profit",
        "position_concentration",
        "fallback_price",
    } <= event_types
    assert all(event["paper_only"] is True for event in events)
    assert next(event for event in events if event["event_type"] == "position_stop_loss")["severity"] == "high"


def test_paper_order_audit_payload_keeps_risk_evidence_and_paper_flag():
    payload = _paper_order_audit_payload(
        "600519.SH",
        "buy",
        100,
        1234.5,
        {"source": "qveris", "trade_date": "2026-06-11"},
        123450.0,
        42.04,
        76507.96,
        {
            "accepted": True,
            "equity": 200000.0,
            "config": {"max_order_pct": 0.7},
            "checks": [{"name": "max_order_pct", "passed": True, "value": 0.6173, "limit": 0.7}],
        },
    )
    assert payload["paper_only"] is True
    assert payload["price_source"] == "qveris"
    assert payload["trade_date"] == "2026-06-11"
    assert payload["risk"]["accepted"] is True
    assert payload["risk"]["equity_before_order"] == 200000.0
    assert payload["risk"]["checks"][0]["name"] == "max_order_pct"


def test_paper_order_model_can_persist_risk_payload_for_portfolio_detail():
    payload = _paper_order_audit_payload(
        "300750.SZ",
        "sell",
        200,
        222.2,
        {"source": "eastmoney", "trade_date": "2026-06-11"},
        44440.0,
        72.33,
        144367.67,
        {"accepted": True, "checks": [{"name": "min_cash_pct", "passed": True, "value": 0.7, "limit": 0.01}], "config": {"min_cash_pct": 0.01}, "equity": 200000.0},
    )
    order = PaperOrder(symbol="300750.SZ", side="sell", price=222.2, shares=200, fee=72.33, payload=payload)
    row = {
        "price_source": (order.payload or {}).get("price_source"),
        "amount": (order.payload or {}).get("amount"),
        "risk": (order.payload or {}).get("risk") or {},
        "paper_only": bool((order.payload or {}).get("paper_only")),
    }
    assert row["price_source"] == "eastmoney"
    assert row["amount"] == 44440.0
    assert row["risk"]["checks"][0]["name"] == "min_cash_pct"
    assert row["paper_only"] is True


def test_apply_parameter_changes_routes_risk_and_params():
    rule = {"risk": {"max_position_pct": 0.1}, "buy": ["score_top_30"]}
    updated = _apply_parameter_changes(rule, [{"name": "stop_loss", "to": 0.06}, {"name": "rebalance", "to": "weekly"}])
    assert updated["risk"]["max_position_pct"] == 0.1
    assert updated["risk"]["stop_loss"] == 0.06
    assert updated["params"]["rebalance"] == "weekly"


def test_merge_strategy_rule_config_preserves_signal_and_validation_fields():
    rule = {"buy": ["macd_golden_cross"], "latest_validation": {"passed": True}, "risk": {"max_position_pct": 0.1}, "params": {"max_positions": 10}}
    updated = _merge_strategy_rule_config(rule, risk={"stop_loss": 0.06}, params={"slippage_bps": 12})
    assert updated["buy"] == ["macd_golden_cross"]
    assert updated["latest_validation"]["passed"] is True
    assert updated["risk"]["max_position_pct"] == 0.1
    assert updated["risk"]["stop_loss"] == 0.06
    assert updated["params"]["max_positions"] == 10
    assert updated["params"]["slippage_bps"] == 12


def test_candidate_base_rule_removes_source_validation_state():
    base = _candidate_base_rule({"buy": ["macd_golden_cross"], "latest_validation": {"passed": True}, "promoted_from_validation": {"source": "old"}, "params": {"max_positions": 10}})
    assert base["buy"] == ["macd_golden_cross"]
    assert base["params"]["max_positions"] == 10
    assert "latest_validation" not in base
    assert "promoted_from_validation" not in base


def test_normalize_optimization_result_falls_back_to_metric_changes():
    result = _normalize_optimization_result(
        {"summary": "回撤偏高", "risk_findings": "1. 最大回撤过高\n2. 换手偏高", "parameter_changes": "建议降低仓位", "next_experiments": "测试周度调仓"},
        {"risk": {"max_position_pct": 0.1, "stop_loss": 0.08}, "params": {"max_positions": 10, "candidate_top_n": 5}},
        {"max_drawdown": 0.31, "sharpe": 0.72, "trade_count": 1500, "alpha_return": -0.12, "benchmark_return": 0.4},
    )
    changes = {change["name"]: change["to"] for change in result["parameter_changes"]}
    assert changes["entry_mode"] == "relative_strength_rotation"
    assert changes["max_sector_pct"] == 0.25
    assert changes["min_momentum"] == 0.05
    assert changes["min_quality"] == 0.6
    assert changes["min_relative_strength"] == 0.75
    assert changes["relative_strength_window"] == 40
    assert changes["max_position_pct"] == 0.065
    assert changes["stop_loss"] == 0.06
    assert changes["candidate_top_n"] == 4
    assert changes["rebalance"] == "weekly"
    assert result["raw_parameter_changes"] == "建议降低仓位"


def test_normalize_optimization_result_allows_execution_parameters():
    result = _normalize_optimization_result(
        {"parameter_changes": [{"name": "entry_mode", "to": "relative_strength_rotation"}, {"name": "max_sector_pct", "to": 0.25}, {"name": "volume_participation", "to": 0.03}, {"name": "min_momentum", "to": 0.05}, {"name": "min_quality", "to": 0.65}, {"name": "min_relative_strength", "to": 0.8}, {"name": "relative_strength_window", "to": 20}, {"name": "min_market_breadth", "to": 0.55}, {"name": "unknown", "to": 1}]},
        {},
        {},
    )
    changes = {change["name"]: change["to"] for change in result["parameter_changes"]}
    assert changes == {"entry_mode": "relative_strength_rotation", "max_sector_pct": 0.25, "volume_participation": 0.03, "min_momentum": 0.05, "min_quality": 0.65, "min_relative_strength": 0.8, "relative_strength_window": 20, "min_market_breadth": 0.55}


def test_metric_driven_changes_target_out_of_sample_alpha_failure():
    changes = _metric_driven_parameter_changes(
        {"risk": {"max_position_pct": 0.1}, "params": {"candidate_top_n": 5, "min_momentum": 0.02, "min_quality": 0.3, "max_sector_pct": 0.35}},
        {"alpha_return": 0.01, "benchmark_return": 0.1, "out_of_sample": {"alpha_return": -0.09}, "max_drawdown": 0.12, "sharpe": 1.4, "trade_count": 60},
    )
    by_name = {change["name"]: change for change in changes}
    assert by_name["candidate_top_n"]["to"] == 3
    assert by_name["entry_mode"]["to"] == "relative_strength_rotation"
    assert by_name["min_momentum"]["to"] == 0.08
    assert by_name["min_quality"]["to"] == 0.65
    assert by_name["min_relative_strength"]["to"] == 0.8
    assert by_name["relative_strength_window"]["to"] == 40
    assert by_name["min_market_breadth"]["to"] == 0.55
    assert by_name["max_sector_pct"]["to"] == 0.25
    assert "样本外" in by_name["min_momentum"]["reason"]


def test_alpha_grid_candidates_cover_alpha_sensitive_parameters():
    candidates = _alpha_grid_candidates({"candidate_top_n": 5, "max_positions": 10, "max_sector_pct": 0.35, "max_position_pct": 0.095, "rebalance": "daily"}, max_trials=8)
    assert len(candidates) == 8
    names = {change["name"] for candidate in candidates for change in candidate}
    assert {"entry_mode", "candidate_top_n", "max_positions", "rebalance", "max_sector_pct", "max_position_pct", "min_momentum", "min_quality", "min_relative_strength", "relative_strength_window", "min_market_breadth"}.issubset(names)
    momentum_values = {change["to"] for candidate in candidates for change in candidate if change["name"] == "min_momentum"}
    quality_values = {change["to"] for candidate in candidates for change in candidate if change["name"] == "min_quality"}
    max_positions_values = {change["to"] for candidate in candidates for change in candidate if change["name"] == "max_positions"}
    rebalance_values = {change["to"] for candidate in candidates for change in candidate if change["name"] == "rebalance"}
    relative_strength_values = {change["to"] for candidate in candidates for change in candidate if change["name"] == "min_relative_strength"}
    relative_strength_windows = {change["to"] for candidate in candidates for change in candidate if change["name"] == "relative_strength_window"}
    market_breadth_values = {change["to"] for candidate in candidates for change in candidate if change["name"] == "min_market_breadth"}
    entry_modes = {change["to"] for candidate in candidates for change in candidate if change["name"] == "entry_mode"}
    position_values = {change["to"] for candidate in candidates for change in candidate if change["name"] == "max_position_pct"}
    top_n_values = {change["to"] for candidate in candidates for change in candidate if change["name"] == "candidate_top_n"}
    assert {0.08, 0.1, 0.12}.issubset(momentum_values)
    assert {0.75, 0.85}.issubset(quality_values)
    assert 4 in max_positions_values
    assert {"weekly", "monthly", "daily"}.issubset(rebalance_values)
    assert {0.7, 0.8, 0.9}.issubset(relative_strength_values)
    assert {20, 40}.issubset(relative_strength_windows)
    assert {0.45, 0.55, 0.65}.intersection(market_breadth_values)
    assert "relative_strength_rotation" in entry_modes
    assert "equal_weight_rotation" in entry_modes
    assert "equal_weight_buy_hold" in entry_modes
    assert "pool_equal_weight_hold" in entry_modes
    assert {0.16, 0.24}.issubset(position_values)
    assert {20, 50}.issubset(top_n_values)
    equal_candidate = next(candidate for candidate in candidates if any(change["name"] == "entry_mode" and change["to"] == "equal_weight_rotation" for change in candidate))
    equal_changes = {change["name"]: change["to"] for change in equal_candidate}
    assert equal_changes["min_quality"] == 0.0
    assert equal_changes["min_momentum"] == 0.0
    assert equal_changes["max_sector_pct"] == 1.0
    assert equal_changes["stop_loss"] == 0.5


def test_alpha_search_score_rewards_alpha_and_stability():
    weak = {"alpha_return": -0.1, "sharpe": 1.0, "max_drawdown": 0.1, "walk_forward_stability": {"passed": False}, "out_of_sample": {"passed": False, "return": -0.08, "alpha_return": -0.12}}
    strong = {"alpha_return": 0.02, "sharpe": 1.0, "max_drawdown": 0.1, "walk_forward_stability": {"passed": True}, "out_of_sample": {"passed": True, "return": 0.03, "alpha_return": 0.02}}
    assert _alpha_search_score(strong) > _alpha_search_score(weak)


def test_strategy_backtest_params_use_llm_candidate_rule():
    strategy = Strategy(
        name="candidate",
        rule_json={
            "risk": {"max_position_pct": 0.07, "stop_loss": 0.05, "take_profit": 0.18},
            "params": {"entry_mode": "relative_strength_rotation", "max_positions": 6, "candidate_top_n": 3, "min_momentum": 0.05, "min_quality": 0.65, "min_relative_strength": 0.75, "relative_strength_window": 90, "min_market_breadth": 0.55, "rebalance": "weekly", "slippage_bps": 12, "volume_participation": 0.08, "limit_up_pct": 0.1, "limit_down_pct": 0.1, "max_sector_pct": 0.4},
        },
    )
    params = _strategy_backtest_params(strategy)
    assert params["entry_mode"] == "relative_strength_rotation"
    assert params["max_position_pct"] == 0.07
    assert params["stop_loss"] == 0.05
    assert params["take_profit"] == 0.18
    assert params["max_positions"] == 6
    assert params["candidate_top_n"] == 3
    assert params["min_momentum"] == 0.05
    assert params["min_quality"] == 0.65
    assert params["min_relative_strength"] == 0.75
    assert params["relative_strength_window"] == 90
    assert params["min_market_breadth"] == 0.55
    assert params["rebalance"] == "weekly"
    assert params["slippage_bps"] == 12
    assert params["volume_participation"] == 0.08
    assert params["limit_up_pct"] == 0.1
    assert params["limit_down_pct"] == 0.1
    assert params["max_sector_pct"] == 0.4


def test_strategy_backtest_params_accept_equal_weight_rotation_mode():
    strategy = Strategy(name="equal", rule_json={"params": {"entry_mode": "equal_weight_rotation", "candidate_top_n": 20, "max_positions": 20}})
    params = _strategy_backtest_params(strategy)
    assert params["entry_mode"] == "equal_weight_rotation"
    assert params["candidate_top_n"] == 20
    assert params["max_positions"] == 20


def test_strategy_backtest_params_accept_equal_weight_buy_hold_mode():
    strategy = Strategy(name="buy hold", rule_json={"params": {"entry_mode": "equal_weight_buy_hold", "candidate_top_n": 20, "max_positions": 20}})
    params = _strategy_backtest_params(strategy)
    assert params["entry_mode"] == "equal_weight_buy_hold"
    assert params["candidate_top_n"] == 20
    assert params["max_positions"] == 20


def test_strategy_backtest_params_accept_pool_equal_weight_hold_mode():
    strategy = Strategy(name="pool hold", rule_json={"params": {"entry_mode": "pool_equal_weight_hold", "candidate_top_n": 50, "max_positions": 50}})
    params = _strategy_backtest_params(strategy)
    assert params["entry_mode"] == "pool_equal_weight_hold"
    assert params["candidate_top_n"] == 50
    assert params["max_positions"] == 50


def test_backtest_execution_constraint_helpers():
    assert _rank_percentiles({"weak": -0.1, "mid": 0.02, "strong": 0.2}) == {"weak": 0.3333, "mid": 0.6667, "strong": 1.0}
    assert _market_breadth({"up": [1, 2, 3], "down": [3, 2, 1], "short": [1]}, 3) == 0.5
    assert _rebalance_due(date(2026, 1, 1), None, "monthly") is True
    assert _rebalance_due(date(2026, 1, 2), date(2026, 1, 1), "daily") is True
    assert _rebalance_due(date(2026, 1, 2), date(2026, 1, 1), "weekly") is False
    assert _rebalance_due(date(2026, 1, 5), date(2026, 1, 2), "weekly") is True
    assert _rebalance_due(date(2026, 2, 2), date(2026, 1, 30), "monthly") is True
    assert _rebalance_due(date(2026, 2, 3), date(2026, 2, 2), "monthly") is False
    assert _slippage_price(10, "buy", 10) == 10.01
    assert _slippage_price(10, "sell", 10) == 9.99
    assert _volume_limited_lot_shares(1000, 5000, 0.05) == 200
    assert _volume_limited_lot_shares(1000, 0, 0.05) == 1000
    assert _buy_rejection_reason(9500, 100, 100000, 0.05)["reason"] == "lot_size_min_notional"
    assert _buy_rejection_reason(12000, 100, 1000, 0.05)["reason"] == "volume_capacity"
    assert _limit_state(10, 11.0, 0.099, 0.099) == "limit_up"
    assert _limit_state(10, 8.9, 0.099, 0.099) == "limit_down"
    assert _limit_state(10, 10.2, 0.099, 0.099) is None


def test_filter_tradable_buy_candidates_replaces_unaffordable_top_signal():
    candidates = [
        (2.0, MarketBar(symbol="600519.SH", trade_date=date(2026, 1, 1), open=1600, high=1600, low=1600, close=1600, volume=1000000)),
        (1.0, MarketBar(symbol="300750.SZ", trade_date=date(2026, 1, 1), open=100, high=100, low=100, close=100, volume=1000000)),
    ]
    tradable, rejections = _filter_tradable_buy_candidates(candidates, max_position_value=24000, participation=0.05, slippage_bps=0, limit=2)
    assert [bar.symbol for _, bar in tradable] == ["300750.SZ"]
    assert rejections[0]["symbol"] == "600519.SH"
    assert rejections[0]["reason"] == "lot_size_min_notional"


def test_equal_weight_rotation_candidates_can_be_tradable_without_history_window():
    bar = MarketBar(symbol="000001.SZ", trade_date=date(2026, 1, 1), open=10, high=10, low=10, close=10, volume=1000000)
    tradable, rejections = _filter_tradable_buy_candidates([(0.0, bar)], max_position_value=6000, participation=0.05, slippage_bps=0, limit=1)
    assert [item[1].symbol for item in tradable] == ["000001.SZ"]
    assert rejections == []


def test_sector_exposure_after_order_uses_existing_positions():
    positions = {"600519.SH": 100, "300750.SZ": 100}
    day_bars = {
        "600519.SH": MarketBar(symbol="600519.SH", trade_date=date(2026, 1, 1), open=100, high=100, low=100, close=100, volume=10000),
        "300750.SZ": MarketBar(symbol="300750.SZ", trade_date=date(2026, 1, 1), open=100, high=100, low=100, close=100, volume=10000),
    }
    symbol_sector = {"600519.SH": "白酒", "000858.SZ": "白酒", "300750.SZ": "新能源"}
    assert _sector_exposure_after_order(positions, day_bars, symbol_sector, "000858.SZ", 5000, 100000) == 0.15


def test_equal_weight_benchmark_uses_same_market_bars():
    dates = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
    by_symbol = {
        "600519.SH": [MarketBar(symbol="600519.SH", trade_date=dates[0], open=100, high=100, low=100, close=100), MarketBar(symbol="600519.SH", trade_date=dates[2], open=120, high=120, low=120, close=120)],
        "300750.SZ": [MarketBar(symbol="300750.SZ", trade_date=dates[0], open=50, high=50, low=50, close=50), MarketBar(symbol="300750.SZ", trade_date=dates[2], open=55, high=55, low=55, close=55)],
    }
    benchmark = _equal_weight_benchmark(by_symbol, dates, 100000)
    assert benchmark["name"] == "tradable_equal_weight_pool"
    assert benchmark["symbol_count"] == 2
    assert benchmark["return"] == 0.15
    assert benchmark["cash_drag"] == 0.0
    assert "out_of_sample" in benchmark
    assert benchmark["equity_curve"][-1] == 115000


def test_equal_weight_benchmark_respects_a_share_lot_cash_constraints():
    dates = [date(2026, 1, 1), date(2026, 1, 2)]
    by_symbol = {
        "600519.SH": [MarketBar(symbol="600519.SH", trade_date=dates[0], open=1600, high=1600, low=1600, close=1600), MarketBar(symbol="600519.SH", trade_date=dates[1], open=1700, high=1700, low=1700, close=1700)],
        "300750.SZ": [MarketBar(symbol="300750.SZ", trade_date=dates[0], open=400, high=400, low=400, close=400), MarketBar(symbol="300750.SZ", trade_date=dates[1], open=440, high=440, low=440, close=440)],
    }
    benchmark = _equal_weight_benchmark(by_symbol, dates, 100000)
    assert benchmark["symbol_count"] == 1
    assert benchmark["cash_drag"] == 0.6
    assert benchmark["return"] == 0.04


def test_equal_weight_benchmark_can_apply_execution_costs_and_volume_capacity():
    dates = [date(2026, 1, 1), date(2026, 1, 2)]
    by_symbol = {
        "600519.SH": [MarketBar(symbol="600519.SH", trade_date=dates[0], open=100, high=100, low=100, close=100, volume=1000), MarketBar(symbol="600519.SH", trade_date=dates[1], open=110, high=110, low=110, close=110, volume=1000)],
        "300750.SZ": [MarketBar(symbol="300750.SZ", trade_date=dates[0], open=50, high=50, low=50, close=50, volume=100000), MarketBar(symbol="300750.SZ", trade_date=dates[1], open=55, high=55, low=55, close=55, volume=100000)],
    }
    no_cost = _equal_weight_benchmark(by_symbol, dates, 100000)
    with_cost = _equal_weight_benchmark(by_symbol, dates, 100000, slippage_bps=10, volume_participation=0.05, apply_fees=True)
    assert no_cost["symbol_count"] == 2
    assert with_cost["symbol_count"] == 1
    assert with_cost["fees_paid"] > 0
    assert with_cost["cost_model"] == {"slippage_bps": 10, "volume_participation": 0.05, "fees_enabled": True}
    assert with_cost["return"] < no_cost["return"]


def test_paper_rebalance_plan_sells_non_target_and_buys_top_candidate():
    portfolio = PaperPortfolio(name="paper", cash=100000)
    positions = [PaperPosition(symbol="600519.SH", shares=100, avg_cost=100)]
    factors = [
        FactorRow(symbol="300750.SZ", name="宁德时代", sector="新能源", price=100, dif=1, dea=0, macd=1, rsi=55, momentum_20d=0.08, volatility_20d=0.2, quality=0.8, score=1.2),
        FactorRow(symbol="600519.SH", name="贵州茅台", sector="白酒食品", price=100, dif=-1, dea=0, macd=-1, rsi=45, momentum_20d=-0.01, volatility_20d=0.2, quality=0.7, score=0.4),
    ]
    price_map = {
        "600519.SH": {"price": 100, "source": "eastmoney", "trade_date": "2026-06-11"},
        "300750.SZ": {"price": 100, "source": "eastmoney", "trade_date": "2026-06-11"},
    }
    plan = _paper_rebalance_order_plan(
        portfolio,
        positions,
        factors,
        price_map,
        {"max_position_pct": 0.1, "stop_loss": 0.08, "take_profit": 0.35, "max_positions": 5, "candidate_top_n": 1, "min_momentum": 0.0, "min_quality": 0.0},
    )
    by_side = {item["side"]: item for item in plan["recommendations"]}
    assert by_side["sell"]["symbol"] == "600519.SH"
    assert by_side["sell"]["shares"] == 100
    assert by_side["buy"]["symbol"] == "300750.SZ"
    assert by_side["buy"]["shares"] == 100
    assert plan["target_symbols"] == ["300750.SZ"]


def test_stock_recommendation_from_factor_explains_buy_watch_signal():
    row = FactorRow(
        symbol="300750.SZ",
        name="宁德时代",
        sector="新能源",
        price=100,
        dif=1.2,
        dea=0.8,
        macd=0.8,
        rsi=62,
        momentum_20d=0.09,
        volatility_20d=0.24,
        quality=0.72,
        score=1.05,
        quality_source="financial_report:qveris",
        revenue_growth=0.18,
        net_margin=0.12,
        roe=14.5,
    )

    rec = _stock_recommendation_from_factor(row, 1, trade_date=date(2026, 6, 11))

    assert rec["action"] == "BUY_WATCH"
    assert rec["confidence"] == "high"
    assert "均线动量" in rec["strategy_tags"]
    assert "质量成长" in rec["strategy_tags"]
    assert rec["risk_control"]["paper_only"] is True
    assert rec["trade_date"] == "2026-06-11"


def test_recommendation_sort_prioritizes_actionable_buy_watch_before_overheated_risk():
    buy = {"action": "BUY_WATCH", "confidence": "medium", "score": 1.0}
    overheated = {"action": "RISK_WATCH", "confidence": "low", "score": 3.0}
    observe = {"action": "OBSERVE", "confidence": "medium", "score": 1.5}

    assert sorted([overheated, observe, buy], key=_recommendation_sort_key) == [buy, observe, overheated]


def test_format_feishu_signal_message_contains_recommendations_and_safety_text():
    recommendations = {
        "trade_date": "2026-06-11",
        "recommendations": [
            {
                "name": "宁德时代",
                "symbol": "300750.SZ",
                "action": "BUY_WATCH",
                "score": 1.05,
                "reason": "趋势、质量和相对强度同时满足",
                "evidence": {"momentum_20d": 0.09, "quality": 0.72},
            }
        ],
    }
    review = {"recommendation_date": "2026-06-10", "review_date": "2026-06-11", "summary": {"hit_count": 1, "reviewed": 1, "hit_rate": 1.0, "avg_next_day_return": 0.02}}

    message = _format_feishu_signal_message(recommendations, review)

    assert "ZiQuant A股策略信号" in message
    assert "宁德时代(300750.SZ)" in message
    assert "昨日推荐复盘" in message
    assert "不会提交真实交易订单" in message
    assert "不是投资建议" in message


def test_paper_rebalance_observation_payload_keeps_reviewable_evidence():
    portfolio = PaperPortfolio(id=uuid.uuid4(), name="公共模拟盘", cash=100000)
    strategy = Strategy(id=uuid.uuid4(), name="金叉质量轮动", status="active")
    execution_guard = {"execution_allowed": False, "execution_blocked": False, "reason": "plan_only"}
    plan = {"target_symbols": ["000001.SZ", "600519.SH"], "equity": 120000.0}
    recommendations = [
        {"symbol": "000001.SZ", "side": "buy", "shares": 100, "price": 10.0, "amount": 1000.0, "reason": "target_allocation_gap", "price_source": "qveris", "risk": {"accepted": True}},
        {"symbol": "600519.SH", "side": "sell", "shares": 100, "price": 120.0, "amount": 12000.0, "reason": "not_in_strategy_targets", "price_source": "eastmoney", "risk": {"accepted": False, "reason": "min_cash_pct"}},
    ]

    payload = paper_rebalance_observation_payload(
        portfolio,
        strategy,
        {"status": "ready", "passed": True},
        execution_guard,
        plan,
        recommendations,
        [],
    )

    assert payload["paper_only"] is True
    assert payload["strategy_health_status"] == "ready"
    assert payload["recommendation_count"] == 2
    assert payload["recommendations_by_side"] == {"buy": 1, "sell": 1}
    assert payload["risk_accepted_count"] == 1
    assert payload["risk_rejected_count"] == 1
    assert payload["sample_recommendations"][1]["risk_reason"] == "min_cash_pct"


def test_paper_rebalance_plan_filters_low_quality_candidates():
    portfolio = PaperPortfolio(name="paper", cash=100000)
    factors = [
        FactorRow(symbol="300750.SZ", name="宁德时代", sector="新能源", price=100, dif=1, dea=0, macd=1, rsi=55, momentum_20d=0.08, volatility_20d=0.2, quality=0.5, score=1.3),
        FactorRow(symbol="600519.SH", name="贵州茅台", sector="白酒食品", price=100, dif=1, dea=0, macd=1, rsi=55, momentum_20d=0.06, volatility_20d=0.2, quality=0.8, score=1.1),
    ]
    price_map = {
        "300750.SZ": {"price": 100, "source": "eastmoney", "trade_date": "2026-06-11"},
        "600519.SH": {"price": 100, "source": "eastmoney", "trade_date": "2026-06-11"},
    }
    plan = _paper_rebalance_order_plan(
        portfolio,
        [],
        factors,
        price_map,
        {"max_position_pct": 0.1, "stop_loss": 0.08, "take_profit": 0.35, "max_positions": 5, "candidate_top_n": 2, "min_momentum": 0.0, "min_quality": 0.65},
    )
    buys = [item for item in plan["recommendations"] if item["side"] == "buy"]
    assert [item["symbol"] for item in buys] == ["600519.SH"]
    assert plan["target_symbols"] == ["600519.SH"]


def test_paper_rebalance_plan_buy_hold_keeps_existing_positions():
    portfolio = PaperPortfolio(name="paper", cash=100000)
    positions = [PaperPosition(symbol="600519.SH", shares=100, avg_cost=120)]
    factors = [
        FactorRow(symbol="300750.SZ", name="宁德时代", sector="新能源", price=100, dif=1, dea=0, macd=1, rsi=55, momentum_20d=0.08, volatility_20d=0.2, quality=0.8, score=1.2),
    ]
    price_map = {
        "600519.SH": {"price": 100, "source": "eastmoney", "trade_date": "2026-06-11"},
        "300750.SZ": {"price": 100, "source": "eastmoney", "trade_date": "2026-06-11"},
    }
    plan = _paper_rebalance_order_plan(
        portfolio,
        positions,
        factors,
        price_map,
        {"entry_mode": "equal_weight_buy_hold", "max_position_pct": 0.24, "stop_loss": 0.08, "take_profit": 0.35, "max_positions": 50, "candidate_top_n": 50, "min_momentum": 0.0, "min_quality": 0.0},
    )
    by_symbol = {item["symbol"]: item for item in plan["recommendations"]}
    assert by_symbol["600519.SH"]["side"] == "hold"
    assert by_symbol["600519.SH"]["reason"] == "buy_hold_strategy_position"
    assert by_symbol["300750.SZ"]["side"] == "buy"
    assert by_symbol["300750.SZ"]["reason"] == "buy_hold_initial_build"
    assert by_symbol["300750.SZ"]["amount"] <= 15000
    assert plan["planning_constraints"]["effective_order_pct"] == 0.15


def test_paper_rebalance_plan_pool_equal_weight_uses_pool_allocation():
    portfolio = PaperPortfolio(name="paper", cash=100000)
    factors = [
        FactorRow(symbol="000001.SZ", name="平安银行", sector="银行", price=100, dif=1, dea=0, macd=1, rsi=55, momentum_20d=0.08, volatility_20d=0.2, quality=0.8, score=1.2),
        FactorRow(symbol="000002.SZ", name="万科A", sector="地产", price=100, dif=1, dea=0, macd=1, rsi=55, momentum_20d=0.08, volatility_20d=0.2, quality=0.8, score=1.1),
        FactorRow(symbol="000063.SZ", name="中兴通讯", sector="通信", price=100, dif=1, dea=0, macd=1, rsi=55, momentum_20d=0.08, volatility_20d=0.2, quality=0.8, score=1.0),
    ]
    price_map = {row.symbol: {"price": 100, "source": "eastmoney", "trade_date": "2026-06-11"} for row in factors}
    plan = _paper_rebalance_order_plan(
        portfolio,
        [],
        factors,
        price_map,
        {"entry_mode": "pool_equal_weight_hold", "max_position_pct": 0.3, "stop_loss": 0.08, "take_profit": 0.35, "max_positions": 3, "candidate_top_n": 3, "min_momentum": 0.0, "min_quality": 0.0},
    )
    buys = [item for item in plan["recommendations"] if item["side"] == "buy"]
    assert len(buys) == 3
    assert {item["shares"] for item in buys} == {300}
    assert all(item["reason"] == "buy_hold_initial_build" for item in buys)


def test_platform_strategy_promotion_becomes_publicly_visible():
    strategy = Strategy(name="candidate", visibility=Visibility.private, owner_id=None)
    assert _visibility_after_promotion(strategy) == Visibility.public


def test_public_source_strategy_promotion_becomes_publicly_visible():
    source = Strategy(name="source", visibility=Visibility.public)
    strategy = Strategy(name="candidate", visibility=Visibility.private, owner_id=object())
    assert _visibility_after_promotion(strategy, source) == Visibility.public


def test_private_strategy_promotion_stays_private():
    class S:
        owner_id = object()
        visibility = Visibility.private

    assert _visibility_after_promotion(S()) == Visibility.private


def test_candidate_source_strategy_id_supports_llm_and_alpha_grid_sources():
    assert _candidate_source_strategy_id({"llm_optimization": {"source_strategy_id": "llm-source"}}) == "llm-source"
    assert _candidate_source_strategy_id({"alpha_grid_search": {"source_strategy_id": "grid-source"}}) == "grid-source"
    assert _candidate_source_strategy_id({"llm_optimization": {"source_strategy_id": "llm-source"}, "alpha_grid_search": {"source_strategy_id": "grid-source"}}) == "llm-source"


def test_backtest_metric_comparison_rejects_degraded_candidate():
    candidate = {"total_return": 0.01, "sharpe": 0.8, "max_drawdown": 0.08, "trade_count": 8}
    baseline = {"total_return": 0.03, "sharpe": 1.2, "max_drawdown": 0.04, "trade_count": 8}
    comparison = _compare_backtest_metrics(candidate, baseline)
    assert comparison["baseline_compared"] is True
    assert comparison["passed"] is False
    assert "Sharpe" in " ".join(comparison["reasons"])


def test_backtest_metric_comparison_accepts_risk_adjusted_improvement():
    candidate = {"total_return": 0.028, "sharpe": 1.45, "max_drawdown": 0.04, "trade_count": 8}
    baseline = {"total_return": 0.03, "sharpe": 1.2, "max_drawdown": 0.05, "trade_count": 8}
    comparison = _compare_backtest_metrics(candidate, baseline)
    assert comparison["passed"] is True
    assert comparison["deltas"]["sharpe"] == 0.25


def test_backtest_metric_comparison_rejects_limited_history():
    candidate = {"total_return": 0.05, "sharpe": 2.0, "max_drawdown": 0.01, "trade_count": 8, "limited_history": True}
    comparison = _compare_backtest_metrics(candidate)
    assert comparison["passed"] is False
    assert "短样本" in " ".join(comparison["reasons"])


def test_walk_forward_stability_accepts_broadly_positive_curve():
    curve = [100000 + i * 180 for i in range(120)]
    stability = _walk_forward_stability(curve)
    assert stability["passed"] is True
    assert stability["positive_segments"] == 4
    assert len(stability["segments"]) == 4


def test_walk_forward_stability_rejects_unstable_curve():
    curve = [100000 + i * 800 for i in range(30)] + [124000 - i * 900 for i in range(30)] + [97000 + i * 100 for i in range(60)]
    stability = _walk_forward_stability(curve)
    assert stability["passed"] is False
    assert "分段" in stability["reason"] or "回撤" in stability["reason"]


def test_out_of_sample_performance_accepts_positive_holdout():
    curve = [100000 + i * 150 for i in range(120)]
    result = _out_of_sample_performance(curve)
    assert result["passed"] is True
    assert result["test_points"] >= 10
    assert result["return"] > 0


def test_out_of_sample_performance_rejects_bad_holdout():
    curve = [100000 + i * 400 for i in range(84)] + [133600 - i * 1200 for i in range(36)]
    result = _out_of_sample_performance(curve)
    assert result["passed"] is False
    assert "样本外" in result["reason"]


def test_out_of_sample_alpha_failure_marks_backtest_metric_failed():
    out_of_sample = _out_of_sample_performance([100000 + i * 120 for i in range(120)])
    benchmark_oos = {"return": out_of_sample["return"] + 0.08}
    alpha_return = round(out_of_sample["return"] - benchmark_oos["return"], 4)
    enriched = {
        **out_of_sample,
        "benchmark_return": benchmark_oos["return"],
        "alpha_return": alpha_return,
        "passed": bool(out_of_sample["passed"]) and alpha_return >= -0.05,
    }
    assert out_of_sample["passed"] is True
    assert enriched["passed"] is False
    assert enriched["alpha_return"] == -0.08


def test_backtest_metric_comparison_rejects_failed_stability():
    candidate = {"total_return": 0.08, "sharpe": 1.4, "max_drawdown": 0.08, "trade_count": 20, "walk_forward_stability": {"passed": False, "reason": "正收益分段不足"}}
    comparison = _compare_backtest_metrics(candidate)
    assert comparison["passed"] is False
    assert "分段稳定性" in " ".join(comparison["reasons"])


def test_backtest_metric_comparison_rejects_failed_out_of_sample():
    candidate = {"total_return": 0.08, "sharpe": 1.4, "max_drawdown": 0.08, "trade_count": 20, "out_of_sample": {"passed": False, "reason": "样本外收益低于 -5%"}}
    comparison = _compare_backtest_metrics(candidate)
    assert comparison["passed"] is False
    assert "样本外" in " ".join(comparison["reasons"])


def test_backtest_metric_comparison_rejects_negative_out_of_sample_alpha():
    candidate = {"total_return": 0.08, "sharpe": 1.4, "max_drawdown": 0.08, "trade_count": 20, "out_of_sample": {"passed": True, "return": 0.02, "benchmark_return": 0.1, "alpha_return": -0.08}}
    comparison = _compare_backtest_metrics(candidate)
    assert comparison["passed"] is False
    assert "样本外 Alpha" in " ".join(comparison["reasons"])


def test_backtest_metric_comparison_rejects_negative_alpha():
    candidate = {"total_return": 0.2, "benchmark_return": 0.45, "alpha_return": -0.25, "sharpe": 1.0, "max_drawdown": 0.08, "trade_count": 20}
    comparison = _compare_backtest_metrics(candidate)
    assert comparison["passed"] is False
    assert "Alpha" in " ".join(comparison["reasons"])


def test_backtest_metric_comparison_rejects_alpha_regression_against_source_strategy():
    candidate = {"total_return": 0.2, "benchmark_return": 0.25, "alpha_return": -0.05, "sharpe": 1.1, "max_drawdown": 0.05, "trade_count": 20}
    baseline = {"total_return": 0.19, "benchmark_return": 0.25, "alpha_return": 0.02, "sharpe": 1.0, "max_drawdown": 0.05, "trade_count": 20}
    comparison = _compare_backtest_metrics(candidate, baseline)
    assert comparison["passed"] is False
    assert "Alpha" in " ".join(comparison["reasons"])


def test_backtest_metric_comparison_rejects_no_baseline_improvement():
    candidate = {"total_return": 0.03, "sharpe": 1.2, "max_drawdown": 0.05, "trade_count": 8}
    baseline = {"total_return": 0.03, "sharpe": 1.2, "max_drawdown": 0.05, "trade_count": 8}
    comparison = _compare_backtest_metrics(candidate, baseline)
    assert comparison["passed"] is False
    assert "实质改善" in " ".join(comparison["reasons"])


def test_backtest_metric_comparison_accepts_baseline_relative_drawdown_improvement():
    candidate = {"total_return": 1.03, "sharpe": 0.98, "max_drawdown": 0.27, "trade_count": 100}
    baseline = {"total_return": 0.64, "sharpe": 0.72, "max_drawdown": 0.31, "trade_count": 100}
    comparison = _compare_backtest_metrics(candidate, baseline)
    assert comparison["passed"] is True
    assert comparison["deltas"]["max_drawdown"] == -0.04


def test_readiness_status_prioritizes_critical_failures():
    checks = [
        {"passed": True, "severity": "critical"},
        {"passed": False, "severity": "warning"},
    ]
    assert _readiness_status(checks) == "degraded"
    checks.append({"passed": False, "severity": "critical"})
    assert _readiness_status(checks) == "blocked"
    assert _readiness_status([{"passed": True, "severity": "critical"}]) == "ready"


def test_production_readiness_audit_groups_required_requirements():
    check_names = [
        "migration_current",
        "deployment_config",
        "stock_pool_size",
        "public_pool_default_quality",
        "real_market_bars",
        "public_pool_real_market_coverage",
        "public_pool_long_history_coverage",
        "market_data_freshness",
        "real_financial_reports",
        "public_pool_real_financial_coverage",
        "financial_data_freshness",
        "enabled_data_source",
        "data_source_capabilities",
        "integration_config",
        "active_admin_user",
        "successful_backtest",
        "active_strategy",
        "strategy_promotion_readiness",
        "recommendation_workflow",
        "strategy_optimization_loop",
        "paper_portfolio_health",
        "fallback_bar_ratio",
    ]
    readiness = {
        "status": "ready",
        "summary": {"stocks": 500},
        "deployment_config": {"mode": "production", "auto_create_schema_enabled": False, "production_safe": True, "reasons": [], "next_action": "none"},
        "checks": [{"name": name, "passed": True, "severity": "warning", "value": "ok", "expected": "ok", "detail": name} for name in check_names],
    }
    audit = production_readiness_audit_payload(readiness, {"status": "ready", "action_items": []})
    assert audit["status"] == "ready"
    assert audit["required_passed"] == audit["required_total"]
    assert audit["required_ratio"] == 1
    assert {item["id"] for item in audit["items"]} >= {"deployment_config", "real_market_data", "effective_strategy", "recommendation_and_signal_workflow", "llm_optimization_loop", "multi_user_access_control"}
    assert audit["coverage"]["requirement_count"] == len(audit["items"])
    assert audit["coverage"]["readiness_passed_count"] == len(check_names)
    assert audit["coverage"]["failed_critical_checks"] == []
    assert {row["category"] for row in audit["coverage"]["category_summary"]} >= {"infrastructure", "real_data", "strategy", "recommendation", "paper_trading", "access_control"}

    readiness["checks"][0]["passed"] = False
    readiness["checks"][0]["severity"] = "critical"
    blocked = production_readiness_audit_payload(readiness, {"status": "degraded", "action_items": [{"severity": "high"}]})
    assert blocked["status"] == "blocked"
    assert blocked["blocked_count"] == 1
    assert blocked["coverage"]["failed_critical_checks"] == ["migration_current"]
    assert blocked["coverage"]["ops_action_severities"]["high"] == 1
    assert blocked["coverage"]["missing_required"] == [{"id": "database_and_schema", "title": "数据库与迁移", "status": "blocked", "next_action": "run_alembic_upgrade"}]
    assert next(item for item in blocked["items"] if item["id"] == "database_and_schema")["next_action"] == "run_alembic_upgrade"


def test_production_acceptance_report_summarizes_decision_and_residual_risks():
    check_names = [
        "migration_current",
        "deployment_config",
        "stock_pool_size",
        "public_pool_default_quality",
        "real_market_bars",
        "public_pool_real_market_coverage",
        "public_pool_long_history_coverage",
        "market_data_freshness",
        "real_financial_reports",
        "public_pool_real_financial_coverage",
        "financial_data_freshness",
        "enabled_data_source",
        "data_source_capabilities",
        "integration_config",
        "active_admin_user",
        "successful_backtest",
        "active_strategy",
        "strategy_promotion_readiness",
        "recommendation_workflow",
        "strategy_optimization_loop",
        "paper_portfolio_health",
        "fallback_bar_ratio",
    ]
    readiness = {
        "status": "ready",
        "summary": {"stocks": 500},
        "deployment_config": {"mode": "production", "auto_create_schema_enabled": False, "production_safe": True, "reasons": [], "next_action": "none"},
        "checks": [{"name": name, "passed": True, "severity": "warning", "value": "ok", "expected": "ok", "detail": name} for name in check_names],
    }
    ops = {
        "status": "ready",
        "action_items": [{"severity": "low", "summary": "继续扩大真实行情覆盖", "action": "increase_real_data_coverage"}],
        "strategy_effectiveness_evidence": {"residual_risks": ["样本外窗口仍需持续滚动观察"]},
        "paper_portfolio_health": {"status": "ready"},
    }
    audit = production_readiness_audit_payload(readiness, ops)
    report = production_acceptance_report_payload(audit, readiness, ops)

    assert report["status"] == "ready"
    assert report["decision"] == "accepted_for_paper_observation"
    assert report["paper_only"] is True
    assert report["strict_production"] is False
    assert report["production_profile"]["production_safe"] is True
    assert report["required_passed"] == report["required_total"]
    assert len(report["checklist"]) == len(audit["items"])
    assert next(item for item in report["checklist"] if item["id"] == "real_market_data")["failed_evidence"] == []
    assert {risk["source"] for risk in report["residual_risks"]} == {"ops_action", "strategy_effectiveness"}
    assert [risk["source"] for risk in report["residual_risks"]].count("ops_action") == 1
    assert all(risk["blocking"] is False for risk in report["residual_risks"])
    assert "不会提交真实交易订单" in report["warning"]
    assert "不构成投资建议" in report["warning"]

    readiness["checks"][0]["passed"] = False
    readiness["checks"][0]["severity"] = "critical"
    blocked_audit = production_readiness_audit_payload(readiness, {"status": "degraded", "action_items": []})
    blocked_report = production_acceptance_report_payload(blocked_audit, readiness, {})
    assert blocked_report["decision"] == "not_accepted"
    assert blocked_report["status"] == "blocked"
    assert next(item for item in blocked_report["checklist"] if item["id"] == "database_and_schema")["failed_evidence"] == ["migration_current"]


def test_production_acceptance_report_blocks_strict_production_profile():
    audit = {
        "status": "ready",
        "required_passed": 1,
        "required_total": 1,
        "required_ratio": 1,
        "coverage": {},
        "items": [{"id": "deployment_config", "title": "上线运行配置", "category": "infrastructure", "required": True, "status": "ready", "passed": True, "evidence": [], "missing_checks": [], "next_action": "none"}],
    }
    readiness = {
        "status": "ready",
        "deployment_config": {
            "mode": "development",
            "auto_create_schema_enabled": True,
            "production_safe": False,
            "reasons": [],
            "next_action": "none",
        },
    }
    report = production_acceptance_report_payload(audit, readiness, {}, strict_production=True)
    assert report["status"] == "degraded"
    assert report["decision"] == "not_accepted"
    assert report["strict_production"] is True
    assert report["production_profile"]["production_safe"] is False
    assert report["production_profile"]["reasons"] == ["deployment_mode_not_production", "auto_create_schema_enabled"]
    assert report["production_profile"]["next_action"] == "set_production_deployment_config"
    assert any(risk["source"] == "deployment_profile" and risk["blocking"] is True for risk in report["residual_risks"])


def test_freshness_status_marks_missing_and_stale_data():
    assert _freshness_status(None, today=date(2026, 6, 11), max_age_days=7)["reason"] == "missing_data"
    fresh = _freshness_status(date(2026, 6, 10), today=date(2026, 6, 11), max_age_days=7)
    assert fresh["fresh"] is True
    assert fresh["age_days"] == 1
    stale = _freshness_status(date(2026, 6, 1), today=date(2026, 6, 11), max_age_days=7)
    assert stale["fresh"] is False
    assert stale["reason"] == "stale"


def test_data_quality_targets_are_ratio_and_floor_based():
    targets = data_quality_targets(500)
    assert targets["real_bar_symbols"] == 90
    assert targets["long_history_symbols"] == 60
    assert targets["financial_symbols"] == 60
    assert targets["max_fallback_bar_ratio"] == 0.05
    empty = data_quality_targets(0)
    assert empty["real_bar_symbols"] == 0
    assert empty["long_history_symbols"] == 0
    assert empty["financial_symbols"] == 0
