from __future__ import annotations

import uuid
import secrets

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, init_schema
from app.models import DataJob, DataSourceConfig, FactorDefinition, PaperPortfolio, Stock, StockPool, Strategy, User, UserRole, Visibility, table_names
from app.services import (
    alpha_grid_search_strategy,
    apply_strategy_optimization,
    active_strategy_health,
    analyze_stock_symbol,
    bootstrap_real_data,
    create_paper_portfolio,
    create_stock_pool,
    data_quality_summary,
    data_provenance_report,
    data_source_capability_matrix,
    dashboard_snapshot,
    evaluate_portfolio_risk,
    financial_report_coverage,
    get_backtest_detail,
    get_portfolio_detail,
    get_stock_pool_detail,
    list_admin_audit_logs,
    list_data_source_configs,
    list_data_jobs,
    list_data_job_runs,
    list_financial_reports,
    list_users,
    list_backtests,
    list_optimizations,
    list_paper_risk_events,
    list_strategy_repair_timeline,
    list_strategy_promotion_candidates,
    list_strategy_experiments,
    market_coverage,
    optimize_strategy,
    operations_status,
    paper_rebalance_plan,
    place_paper_order,
    prepare_qveris_data_source,
    production_acceptance_report,
    production_readiness_audit,
    promote_validated_strategy,
    record_portfolio_snapshot,
    rebuild_public_pool,
    reset_failed_data_jobs,
    remediate_strategy_health,
    realtime_stock_recommendations,
    reset_stale_data_job_runs,
    refresh_factor_values,
    run_backtest,
    run_data_job,
    run_due_data_jobs,
    run_next_strategy_research_action,
    seed_database,
    set_data_source_enabled,
    set_user_active,
    send_feishu_signal,
    strategy_optimization_loop_health,
    sync_financial_reports,
    sync_market_bars,
    sync_stock_universe,
    system_readiness,
    update_strategy_config,
    upsert_data_source_config,
    upsert_user,
    validate_strategy_candidate,
    visible_resource_filter,
    yesterday_recommendation_review,
)
from app.settings import settings

app = FastAPI(title="ZiQuant Platform", version="0.1.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


class PoolCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = ""
    symbols: list[str] = Field(default_factory=list)
    visibility: Visibility = Visibility.private


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    visibility: Visibility = Visibility.private
    strategy_id: str | None = None
    initial_cash: float = Field(default=100000.0, gt=1000)
    risk: dict = Field(default_factory=dict)


class PaperOrderRequest(BaseModel):
    portfolio_id: str
    symbol: str
    side: str = Field(pattern="^(buy|sell)$")
    shares: int = Field(gt=0)


class PaperRebalanceRequest(BaseModel):
    execute: bool = False
    allow_unhealthy_strategy: bool = False


class PaperSnapshotRequest(BaseModel):
    source: str = Field(default="manual", min_length=2, max_length=40)


class RiskCheckRequest(BaseModel):
    symbol: str | None = None
    side: str | None = Field(default=None, pattern="^(buy|sell)$")
    shares: int = 0


class DataSyncRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    days: int = Field(default=180, ge=20, le=1200)
    allow_fallback: bool = True


class FinancialSyncRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    limit: int = Field(default=30, ge=1, le=200)
    allow_fallback: bool = False


class RealDataBootstrapRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    days: int = Field(default=180, ge=20, le=1200)
    limit: int = Field(default=10, ge=1, le=50)


class CoverageRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=500)


class StockUniverseSyncRequest(BaseModel):
    limit: int = Field(default=500, ge=100, le=1000)
    reset_public_pool: bool = True


class DataSourcePrepareRequest(BaseModel):
    query: str | None = None


class DataSourceConfigRequest(BaseModel):
    id: str | None = None
    name: str = Field(min_length=2, max_length=80)
    adapter: str = Field(min_length=2, max_length=40)
    enabled: bool = True
    priority: int = Field(default=100, ge=1, le=999)
    config: dict = Field(default_factory=dict)
    secret_ref: str | None = None


class DataSourceEnabledRequest(BaseModel):
    enabled: bool


class UserSaveRequest(BaseModel):
    id: str | None = None
    email: str = Field(min_length=5, max_length=255)
    name: str = Field(min_length=1, max_length=80)
    role: UserRole = UserRole.researcher
    active: bool = True


class UserActiveRequest(BaseModel):
    active: bool


class BacktestRequest(BaseModel):
    strategy_id: str | None = None
    stock_pool_id: str | None = None
    days: int = Field(default=180, ge=60, le=1600)
    initial_cash: float = Field(default=100000.0, gt=1000)
    max_symbols: int = Field(default=40, ge=5, le=200)


class StrategyOptimizeRequest(BaseModel):
    strategy_id: str | None = None
    backtest_run_id: str | None = None


class StrategyAlphaSearchRequest(BaseModel):
    strategy_id: str | None = None
    days: int = Field(default=900, ge=120, le=1600)
    initial_cash: float = Field(default=100000.0, gt=1000)
    max_symbols: int = Field(default=20, ge=5, le=80)
    max_trials: int = Field(default=6, ge=1, le=12)


class StrategyHealthRemediateRequest(BaseModel):
    strategy_id: str | None = None
    days: int = Field(default=900, ge=120, le=1600)
    initial_cash: float = Field(default=100000.0, gt=1000)
    max_symbols: int = Field(default=40, ge=5, le=120)


class StrategyResearchNextRequest(BaseModel):
    strategy_id: str | None = None
    days: int = Field(default=900, ge=120, le=1600)
    initial_cash: float = Field(default=100000.0, gt=1000)
    max_symbols: int = Field(default=40, ge=5, le=120)
    max_trials: int = Field(default=8, ge=1, le=12)


class StrategyValidateRequest(BaseModel):
    stock_pool_id: str | None = None
    days: int = Field(default=180, ge=60, le=1600)
    initial_cash: float = Field(default=100000.0, gt=1000)
    max_symbols: int = Field(default=40, ge=5, le=200)


class StrategyUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    visibility: Visibility = Visibility.private
    risk: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)


class FeishuSignalRequest(BaseModel):
    chat_id: str | None = None
    limit: int = Field(default=8, ge=1, le=20)
    dry_run: bool = True


def api_token_valid(expected: str, provided: str | None) -> bool:
    if not expected:
        return False
    return bool(provided) and secrets.compare_digest(expected, provided)


async def require_api_token(x_zi_api_token: str | None = Header(default=None)) -> None:
    if not api_token_valid(settings.zi_api_token, x_zi_api_token):
        raise HTTPException(401, {"reason": "invalid_api_token"})


async def current_user(
    session: AsyncSession = Depends(get_session),
    x_zi_user_id: str | None = Header(default=None),
    x_zi_user_email: str | None = Header(default=None),
) -> User:
    user = None
    if x_zi_user_id:
        try:
            user = await session.get(User, x_zi_user_id)
        except Exception:
            user = None
    if not user and x_zi_user_email:
        user = await session.scalar(select(User).where(User.email == x_zi_user_email))
    if not user:
        user = await session.scalar(select(User).where(User.email == "researcher@local.zicode"))
    if not user:
        user = await session.scalar(select(User).where(User.is_active.is_(True)).order_by(User.created_at))
    if not user or not user.is_active:
        raise HTTPException(401, {"reason": "missing_active_user"})
    return user


async def require_admin_user(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(403, {"reason": "admin_required"})
    return user


def require_platform_operator_role(user: User) -> None:
    if user.role not in {UserRole.admin, UserRole.operator}:
        raise HTTPException(403, {"reason": "platform_operator_required"})


def require_admin_for_public_resource(user: User, visibility: Visibility) -> None:
    if visibility == Visibility.public and user.role != UserRole.admin:
        raise HTTPException(403, {"reason": "admin_required_for_public_resource"})


@app.on_event("startup")
async def startup() -> None:
    if settings.auto_create_schema:
        await init_schema()
    async for session in get_session():
        await seed_database(session)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    db_ok = True
    try:
        await session.execute(select(Stock).limit(1))
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "tables": table_names()}


@app.get("/ready")
async def ready(session: AsyncSession = Depends(get_session)) -> JSONResponse:
    out = await system_readiness(session)
    status_code = 503 if out["status"] == "blocked" else 200
    return JSONResponse(out, status_code=status_code)


@app.get("/api/dashboard")
async def dashboard(session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await dashboard_snapshot(session, owner_id=user.id)


@app.get("/api/users/me")
async def user_me(user: User = Depends(current_user)) -> dict:
    return {"id": str(user.id), "email": user.email, "name": user.display_name, "role": user.role.value, "active": user.is_active}


@app.get("/api/stocks")
async def stocks(limit: int = 100, sector: str | None = None, session: AsyncSession = Depends(get_session)) -> dict:
    stmt = select(Stock)
    if sector:
        stmt = stmt.where(Stock.sector == sector)
    rows = (await session.scalars(stmt.limit(min(limit, 1000)))).all()
    return {"count": len(rows), "items": [{"symbol": s.symbol, "name": s.name, "market": s.market, "sector": s.sector, "lot_size": s.lot_size} for s in rows]}


@app.get("/api/stocks/analyze")
async def stock_analyze(symbol: str, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    out = await analyze_stock_symbol(session, symbol)
    if not out.get("found"):
        raise HTTPException(404, out)
    return out


@app.get("/api/recommendations/realtime")
async def recommendations_realtime(limit: int = 10, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await realtime_stock_recommendations(session, limit=limit)


@app.get("/api/recommendations/yesterday-review")
async def recommendations_yesterday_review(limit: int = 10, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await yesterday_recommendation_review(session, limit=limit)


@app.post("/api/signals/feishu", dependencies=[Depends(require_api_token)])
async def feishu_signal(req: FeishuSignalRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await send_feishu_signal(session, chat_id=req.chat_id, limit=req.limit, dry_run=req.dry_run, actor_id=user.id)


@app.post("/api/stocks/sync", dependencies=[Depends(require_api_token)])
async def stocks_sync(req: StockUniverseSyncRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_platform_operator_role(user)
    out = await sync_stock_universe(session, limit=req.limit, reset_public_pool=req.reset_public_pool)
    if not out.get("synced"):
        raise HTTPException(424, out)
    return out


@app.get("/api/pools")
async def pools(session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    rows = (await session.scalars(select(StockPool).where(visible_resource_filter(StockPool, user.id)))).all()
    return {"items": [{"id": str(p.id), "name": p.name, "visibility": p.visibility.value, "owner_id": str(p.owner_id) if p.owner_id else None, "description": p.description} for p in rows]}


@app.post("/api/pools", dependencies=[Depends(require_api_token)])
async def create_pool(req: PoolCreate, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_admin_for_public_resource(user, req.visibility)
    out = await create_stock_pool(session, name=req.name, description=req.description, symbols=req.symbols, owner_id=None if req.visibility == Visibility.public else user.id, visibility=req.visibility)
    if not out.get("created"):
        raise HTTPException(400, out)
    return out


@app.get("/api/pools/{pool_id}")
async def pool_detail(pool_id: str, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    out = await get_stock_pool_detail(session, pool_id)
    if not out.get("found"):
        raise HTTPException(404, out)
    if out.get("visibility") != Visibility.public.value:
        pool = await session.get(StockPool, uuid.UUID(pool_id))
        if not pool or pool.owner_id != user.id:
            raise HTTPException(403, {"reason": "forbidden"})
    return out


@app.post("/api/pools/rebuild", dependencies=[Depends(require_api_token)])
async def rebuild_pool(limit: int = 500, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_platform_operator_role(user)
    return await rebuild_public_pool(session, limit=min(max(limit, 10), 500))


@app.get("/api/strategies")
async def strategies(session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    rows = (await session.scalars(select(Strategy).where(visible_resource_filter(Strategy, user.id)))).all()
    return {"items": [{"id": str(s.id), "name": s.name, "visibility": s.visibility.value, "owner_id": str(s.owner_id) if s.owner_id else None, "status": s.status, "rule": s.rule_json} for s in rows]}


@app.get("/api/strategies/health")
async def strategy_health(session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await active_strategy_health(session, owner_id=user.id)


@app.put("/api/strategies/{strategy_id}", dependencies=[Depends(require_api_token)])
async def strategy_update(strategy_id: str, req: StrategyUpdateRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    strategy = await session.get(Strategy, uuid.UUID(strategy_id))
    if not strategy:
        raise HTTPException(404, {"reason": "missing_strategy"})
    platform_or_public = strategy.owner_id is None or strategy.visibility == Visibility.public or req.visibility == Visibility.public
    if strategy.owner_id != user.id and (not platform_or_public or user.role != UserRole.admin):
        raise HTTPException(403, {"reason": "forbidden"})
    if platform_or_public and user.role != UserRole.admin:
        raise HTTPException(403, {"reason": "admin_required_for_public_strategy"})
    out = await update_strategy_config(session, strategy_id, name=req.name, visibility=req.visibility, risk=req.risk, params=req.params, actor_id=user.id)
    if not out.get("updated"):
        raise HTTPException(400, out)
    return out


@app.get("/api/factors")
async def factors(session: AsyncSession = Depends(get_session)) -> dict:
    rows = (await session.scalars(select(FactorDefinition))).all()
    return {"items": [{"id": str(f.id), "name": f.name, "visibility": f.visibility.value, "expression": f.expression, "version": f.version} for f in rows]}


@app.post("/api/factors/refresh", dependencies=[Depends(require_api_token)])
async def refresh_factors(limit: int = 500, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_platform_operator_role(user)
    return await refresh_factor_values(session, limit=min(max(limit, 10), 500))


@app.get("/api/data-sources")
async def data_sources(session: AsyncSession = Depends(get_session)) -> dict:
    return await list_data_source_configs(session)


@app.get("/api/data-sources/capabilities")
async def data_source_capabilities(session: AsyncSession = Depends(get_session)) -> dict:
    return await data_source_capability_matrix(session)


@app.put("/api/data-sources", dependencies=[Depends(require_api_token)])
async def data_source_save(req: DataSourceConfigRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_platform_operator_role(user)
    out = await upsert_data_source_config(session, name=req.name, adapter=req.adapter, enabled=req.enabled, priority=req.priority, config=req.config, secret_ref=req.secret_ref, source_id=req.id, actor_id=user.id)
    if not out.get("saved"):
        raise HTTPException(400, out)
    return out


@app.patch("/api/data-sources/{source_id}/enabled", dependencies=[Depends(require_api_token)])
async def data_source_enabled(source_id: str, req: DataSourceEnabledRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_platform_operator_role(user)
    out = await set_data_source_enabled(session, source_id, enabled=req.enabled, actor_id=user.id)
    if not out.get("updated"):
        raise HTTPException(404, out)
    return out


@app.post("/api/data/sync", dependencies=[Depends(require_api_token)])
async def data_sync(req: DataSyncRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_platform_operator_role(user)
    out = await sync_market_bars(session, symbols=req.symbols or None, days=req.days, allow_fallback=req.allow_fallback)
    if not out.get("stored_rows") and not req.allow_fallback:
        raise HTTPException(424, out)
    return out


@app.post("/api/data/coverage", dependencies=[Depends(require_api_token)])
async def data_coverage(req: CoverageRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_platform_operator_role(user)
    return await market_coverage(session, symbols=req.symbols or None, limit=req.limit)


@app.get("/api/data/quality")
async def data_quality(session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await data_quality_summary(session)


@app.get("/api/data/provenance")
async def data_provenance(session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await data_provenance_report(session)


@app.get("/api/admin/ops-status", dependencies=[Depends(require_api_token)])
async def admin_ops_status(session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    return await operations_status(session, owner_id=None)


@app.get("/api/admin/production-audit", dependencies=[Depends(require_api_token)])
async def admin_production_audit(session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    return await production_readiness_audit(session)


@app.get("/api/admin/production-acceptance", dependencies=[Depends(require_api_token)])
async def admin_production_acceptance(strict_production: bool = False, session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    return await production_acceptance_report(session, strict_production=strict_production)


@app.post("/api/admin/jobs/reset-stale", dependencies=[Depends(require_api_token)])
async def admin_reset_stale_jobs(hours: int = 2, session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    return await reset_stale_data_job_runs(session, hours=hours, actor_id=user.id)


@app.post("/api/admin/jobs/reset-failed", dependencies=[Depends(require_api_token)])
async def admin_reset_failed_jobs(scheduled_only: bool = True, session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    return await reset_failed_data_jobs(session, scheduled_only=scheduled_only, actor_id=user.id)


@app.post("/api/admin/jobs/run-due", dependencies=[Depends(require_api_token)])
async def admin_run_due_jobs(limit: int = 5, session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    return await run_due_data_jobs(session, limit=limit)


@app.post("/api/financials/sync", dependencies=[Depends(require_api_token)])
async def financials_sync(req: FinancialSyncRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_platform_operator_role(user)
    out = await sync_financial_reports(session, symbols=req.symbols or None, limit=req.limit, allow_fallback=req.allow_fallback)
    if not out.get("stored_rows") and not req.allow_fallback:
        raise HTTPException(424, out)
    return out


@app.post("/api/financials/coverage", dependencies=[Depends(require_api_token)])
async def financials_coverage(req: CoverageRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_platform_operator_role(user)
    return await financial_report_coverage(session, symbols=req.symbols or None, limit=req.limit)


@app.post("/api/data/bootstrap-real", dependencies=[Depends(require_api_token)])
async def data_bootstrap_real(req: RealDataBootstrapRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_platform_operator_role(user)
    out = await bootstrap_real_data(session, symbols=req.symbols or None, days=req.days, limit=req.limit)
    if not out.get("bootstrapped"):
        raise HTTPException(400, out)
    return out


@app.get("/api/financials")
async def financials(symbol: str | None = None, limit: int = 100, session: AsyncSession = Depends(get_session)) -> dict:
    return await list_financial_reports(session, symbol=symbol, limit=limit)


@app.post("/api/data-sources/qveris/prepare", dependencies=[Depends(require_api_token)])
async def data_source_prepare(req: DataSourcePrepareRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_platform_operator_role(user)
    out = await prepare_qveris_data_source(session, query=req.query)
    if not out.get("prepared"):
        raise HTTPException(424, out)
    return out


@app.get("/api/backtests")
async def backtests(session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await list_backtests(session, owner_id=user.id)


@app.get("/api/backtests/{run_id}")
async def backtest_detail(run_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    out = await get_backtest_detail(session, run_id)
    if not out.get("found"):
        raise HTTPException(404, out)
    return out


@app.post("/api/backtests/run", dependencies=[Depends(require_api_token)])
async def backtest_run(req: BacktestRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    out = await run_backtest(session, strategy_id=req.strategy_id, stock_pool_id=req.stock_pool_id, days=req.days, initial_cash=req.initial_cash, max_symbols=req.max_symbols, owner_id=user.id)
    if not out.get("created"):
        raise HTTPException(400, out)
    return out


@app.get("/api/optimizations")
async def optimizations(session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await list_optimizations(session, owner_id=user.id)


@app.get("/api/strategy-experiments")
async def strategy_experiments(limit: int = 30, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await list_strategy_experiments(session, limit=limit, owner_id=user.id)


@app.get("/api/strategies/repair-timeline")
async def strategy_repair_timeline(limit: int = 30, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await list_strategy_repair_timeline(session, limit=limit, owner_id=user.id)


@app.get("/api/strategies/promotion-candidates")
async def strategy_promotion_candidates(limit: int = 20, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await list_strategy_promotion_candidates(session, limit=limit, owner_id=user.id)


@app.get("/api/strategies/optimization-health")
async def strategy_optimization_health(session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await strategy_optimization_loop_health(session, owner_id=user.id)


@app.post("/api/optimizations/{optimization_id}/apply", dependencies=[Depends(require_api_token)])
async def optimization_apply(optimization_id: str, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    out = await apply_strategy_optimization(session, optimization_id, owner_id=user.id)
    if not out.get("applied"):
        raise HTTPException(404, out)
    return out


@app.post("/api/strategies/optimize", dependencies=[Depends(require_api_token)])
async def strategy_optimize(req: StrategyOptimizeRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await optimize_strategy(session, strategy_id=req.strategy_id, backtest_run_id=req.backtest_run_id, owner_id=user.id)


@app.post("/api/strategies/alpha-search", dependencies=[Depends(require_api_token)])
async def strategy_alpha_search(req: StrategyAlphaSearchRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    out = await alpha_grid_search_strategy(session, strategy_id=req.strategy_id, days=req.days, initial_cash=req.initial_cash, max_symbols=req.max_symbols, max_trials=req.max_trials, owner_id=user.id)
    if not out.get("searched"):
        raise HTTPException(400, out)
    return out


@app.post("/api/strategies/remediate-health", dependencies=[Depends(require_api_token)])
async def strategy_health_remediate(req: StrategyHealthRemediateRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    out = await remediate_strategy_health(session, strategy_id=req.strategy_id, days=req.days, initial_cash=req.initial_cash, max_symbols=req.max_symbols, owner_id=user.id)
    if not out.get("remediated") and out.get("reason") != "strategy_health_ready":
        raise HTTPException(400, out)
    return out


@app.post("/api/strategies/research-next", dependencies=[Depends(require_api_token)])
async def strategy_research_next(req: StrategyResearchNextRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await run_next_strategy_research_action(
        session,
        strategy_id=req.strategy_id,
        days=req.days,
        initial_cash=req.initial_cash,
        max_symbols=req.max_symbols,
        max_trials=req.max_trials,
        owner_id=user.id,
    )


@app.post("/api/strategies/{strategy_id}/validate", dependencies=[Depends(require_api_token)])
async def strategy_validate(strategy_id: str, req: StrategyValidateRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    strategy = await session.get(Strategy, uuid.UUID(strategy_id))
    if not strategy:
        raise HTTPException(404, {"reason": "missing_strategy"})
    if strategy.visibility != Visibility.public and strategy.owner_id != user.id:
        raise HTTPException(403, {"reason": "forbidden"})
    return await validate_strategy_candidate(session, strategy_id, stock_pool_id=req.stock_pool_id, days=req.days, initial_cash=req.initial_cash, max_symbols=req.max_symbols, owner_id=user.id)


@app.post("/api/strategies/{strategy_id}/promote", dependencies=[Depends(require_api_token)])
async def strategy_promote(strategy_id: str, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    strategy = await session.get(Strategy, uuid.UUID(strategy_id))
    if not strategy:
        raise HTTPException(404, {"reason": "missing_strategy"})
    if strategy.visibility != Visibility.public and strategy.owner_id != user.id:
        raise HTTPException(403, {"reason": "forbidden"})
    out = await promote_validated_strategy(session, strategy_id, owner_id=user.id)
    if not out.get("promoted"):
        raise HTTPException(400, out)
    return out


@app.get("/api/portfolios")
async def portfolios(session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    rows = (await session.scalars(select(PaperPortfolio).where(visible_resource_filter(PaperPortfolio, user.id)))).all()
    return {"items": [{"id": str(p.id), "name": p.name, "visibility": p.visibility.value, "owner_id": str(p.owner_id) if p.owner_id else None, "cash": p.cash} for p in rows]}


@app.post("/api/portfolios", dependencies=[Depends(require_api_token)])
async def portfolio_create(req: PortfolioCreate, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    require_admin_for_public_resource(user, req.visibility)
    out = await create_paper_portfolio(session, name=req.name, owner_id=None if req.visibility == Visibility.public else user.id, visibility=req.visibility, strategy_id=req.strategy_id, initial_cash=req.initial_cash, risk=req.risk)
    if not out.get("created"):
        raise HTTPException(400, out)
    return out


@app.get("/api/portfolios/{portfolio_id}")
async def portfolio_detail(portfolio_id: str, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    portfolio = await session.get(PaperPortfolio, uuid.UUID(portfolio_id))
    if portfolio and portfolio.visibility != Visibility.public and portfolio.owner_id != user.id:
        raise HTTPException(403, {"reason": "forbidden"})
    out = await get_portfolio_detail(session, portfolio_id)
    if not out.get("found"):
        raise HTTPException(404, out)
    return out


@app.post("/api/portfolios/{portfolio_id}/snapshot", dependencies=[Depends(require_api_token)])
async def portfolio_snapshot(portfolio_id: str, req: PaperSnapshotRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    portfolio = await session.get(PaperPortfolio, uuid.UUID(portfolio_id))
    if portfolio and portfolio.visibility != Visibility.public and portfolio.owner_id != user.id:
        raise HTTPException(403, {"reason": "forbidden"})
    out = await record_portfolio_snapshot(session, portfolio_id, source=req.source)
    if not out.get("recorded"):
        raise HTTPException(404, out)
    return out


@app.post("/api/risk/portfolio/{portfolio_id}", dependencies=[Depends(require_api_token)])
async def portfolio_risk(portfolio_id: str, req: RiskCheckRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    portfolio = await session.get(PaperPortfolio, uuid.UUID(portfolio_id))
    if portfolio and portfolio.visibility != Visibility.public and portfolio.owner_id != user.id:
        raise HTTPException(403, {"reason": "forbidden"})
    out = await evaluate_portfolio_risk(session, portfolio_id, symbol=req.symbol, side=req.side, shares=req.shares)
    if out.get("reason") == "missing_portfolio":
        raise HTTPException(404, out)
    return out


@app.get("/api/risk/events")
async def paper_risk_events(limit: int = 100, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return await list_paper_risk_events(session, owner_id=user.id, limit=limit)


@app.post("/api/portfolios/order", dependencies=[Depends(require_api_token)])
async def paper_order(req: PaperOrderRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    portfolio = await session.get(PaperPortfolio, uuid.UUID(req.portfolio_id))
    if portfolio and portfolio.visibility != Visibility.public and portfolio.owner_id != user.id:
        raise HTTPException(403, {"reason": "forbidden"})
    out = await place_paper_order(session, req.portfolio_id, req.symbol, req.side, req.shares)
    if not out.get("accepted"):
        raise HTTPException(400, out)
    return out


@app.post("/api/portfolios/{portfolio_id}/rebalance", dependencies=[Depends(require_api_token)])
async def paper_rebalance(portfolio_id: str, req: PaperRebalanceRequest, session: AsyncSession = Depends(get_session), user: User = Depends(current_user)) -> dict:
    portfolio = await session.get(PaperPortfolio, uuid.UUID(portfolio_id))
    if portfolio and portfolio.visibility != Visibility.public and portfolio.owner_id != user.id:
        raise HTTPException(403, {"reason": "forbidden"})
    out = await paper_rebalance_plan(session, portfolio_id, execute=req.execute, allow_unhealthy_strategy=req.allow_unhealthy_strategy)
    if not out.get("planned"):
        raise HTTPException(404, out)
    return out


@app.get("/api/admin", dependencies=[Depends(require_api_token)])
async def admin(session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    users = (await session.scalars(select(User))).all()
    jobs = (await session.scalars(select(DataJob))).all()
    sources = (await session.scalars(select(DataSourceConfig))).all()
    return {
        "users": [{"email": u.email, "name": u.display_name, "role": u.role.value, "active": u.is_active} for u in users],
        "jobs": [{"id": str(j.id), "name": j.name, "type": j.job_type, "status": j.status.value, "schedule": j.schedule, "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None, "payload": j.payload} for j in jobs],
        "data_sources": [{"name": s.name, "adapter": s.adapter, "enabled": s.enabled, "priority": s.priority} for s in sources],
        "config": {"database_url": settings.database_url.replace(settings.database_url.split("@")[0] + "@", "***@") if "@" in settings.database_url else settings.database_url},
    }


@app.get("/api/admin/users", dependencies=[Depends(require_api_token)])
async def admin_users(session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    return await list_users(session)


@app.put("/api/admin/users", dependencies=[Depends(require_api_token)])
async def admin_user_save(req: UserSaveRequest, session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    out = await upsert_user(session, email=req.email, display_name=req.name, role=req.role.value, is_active=req.active, user_id=req.id, actor_id=user.id)
    if not out.get("saved"):
        raise HTTPException(400, out)
    return out


@app.patch("/api/admin/users/{user_id}/active", dependencies=[Depends(require_api_token)])
async def admin_user_active(user_id: str, req: UserActiveRequest, session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    out = await set_user_active(session, user_id, active=req.active, actor_id=user.id)
    if not out.get("updated"):
        raise HTTPException(400 if out.get("reason") == "cannot_disable_last_active_admin" else 404, out)
    return out


@app.get("/api/admin/readiness", dependencies=[Depends(require_api_token)])
async def admin_readiness(session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    return await system_readiness(session)


@app.get("/api/admin/jobs", dependencies=[Depends(require_api_token)])
async def admin_jobs(limit: int = 200, job_type: str | None = None, session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    return await list_data_jobs(session, limit=limit, job_type=job_type)


@app.post("/api/admin/jobs/{job_id}/run", dependencies=[Depends(require_api_token)])
async def admin_run_job(job_id: str, session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    out = await run_data_job(session, job_id)
    if not out.get("started"):
        raise HTTPException(404, out)
    return out


@app.get("/api/admin/job-runs", dependencies=[Depends(require_api_token)])
async def admin_job_runs(limit: int = 50, job_id: str | None = None, session: AsyncSession = Depends(get_session), user: User = Depends(require_admin_user)) -> dict:
    return await list_data_job_runs(session, limit=limit, job_id=job_id)


@app.get("/api/admin/audit-logs", dependencies=[Depends(require_api_token)])
async def admin_audit_logs(
    limit: int = 50,
    action: str | None = None,
    target: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin_user),
) -> dict:
    return await list_admin_audit_logs(session, limit=limit, action=action, target=target)


def run() -> None:
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)


if __name__ == "__main__":
    run()
