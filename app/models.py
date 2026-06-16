from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Visibility(str, enum.Enum):
    private = "private"
    public = "public"


class UserRole(str, enum.Enum):
    admin = "admin"
    researcher = "researcher"
    operator = "operator"
    viewer = "viewer"


class JobStatus(str, enum.Enum):
    idle = "idle"
    running = "running"
    failed = "failed"
    success = "success"


class User(Base):
    __tablename__ = "zi_quant_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.researcher)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Stock(Base):
    __tablename__ = "zi_quant_stocks"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    market: Mapped[str] = mapped_column(String(8), index=True)
    sector: Mapped[str] = mapped_column(String(80), index=True)
    lot_size: Mapped[int] = mapped_column(Integer, default=100)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class StockPool(Base):
    __tablename__ = "zi_quant_stock_pools"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    visibility: Mapped[Visibility] = mapped_column(Enum(Visibility), default=Visibility.private)
    refresh_strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockPoolMember(Base):
    __tablename__ = "zi_quant_stock_pool_members"
    __table_args__ = (UniqueConstraint("pool_id", "symbol", name="uq_zi_quant_pool_symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pool_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_stock_pools.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(16), ForeignKey("zi_quant_stocks.symbol"), index=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")


class DataSourceConfig(Base):
    __tablename__ = "zi_quant_data_source_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    adapter: Mapped[str] = mapped_column(String(40), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    secret_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_status: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class MarketBar(Base):
    __tablename__ = "zi_quant_market_bars"
    __table_args__ = (UniqueConstraint("symbol", "trade_date", "frequency", name="uq_zi_quant_bar_symbol_date_freq"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(16), ForeignKey("zi_quant_stocks.symbol"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    frequency: Mapped[str] = mapped_column(String(16), default="1d", index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)
    amount: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FinancialReport(Base):
    __tablename__ = "zi_quant_financial_reports"
    __table_args__ = (UniqueConstraint("symbol", "report_date", "report_type", name="uq_zi_quant_financial_symbol_report"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(16), ForeignKey("zi_quant_stocks.symbol"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    report_type: Mapped[str] = mapped_column(String(40), default="income")
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FactorDefinition(Base):
    __tablename__ = "zi_quant_factor_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    visibility: Mapped[Visibility] = mapped_column(Enum(Visibility), default=Visibility.private)
    expression: Mapped[str] = mapped_column(Text)
    params_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)


class FactorValue(Base):
    __tablename__ = "zi_quant_factor_values"
    __table_args__ = (UniqueConstraint("factor_id", "symbol", "trade_date", name="uq_zi_quant_factor_symbol_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    factor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_factor_definitions.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(16), ForeignKey("zi_quant_stocks.symbol"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Strategy(Base):
    __tablename__ = "zi_quant_strategies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    visibility: Mapped[Visibility] = mapped_column(Enum(Visibility), default=Visibility.private)
    rule_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BacktestRun(Base):
    __tablename__ = "zi_quant_backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_users.id"), nullable=True)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_strategies.id"), nullable=True)
    stock_pool_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_stock_pools.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    initial_cash: Mapped[float] = mapped_column(Float, default=100000.0)
    final_equity: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(24), default="success", index=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BacktestTrade(Base):
    __tablename__ = "zi_quant_backtest_trades"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_backtest_runs.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    shares: Mapped[int] = mapped_column(Integer)
    amount: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class StrategyOptimizationRun(Base):
    __tablename__ = "zi_quant_strategy_optimization_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_users.id"), nullable=True)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_strategies.id"), nullable=True)
    backtest_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_backtest_runs.id", ondelete="SET NULL"), nullable=True)
    model: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(24), default="success", index=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StrategyExperiment(Base):
    __tablename__ = "zi_quant_strategy_experiments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_users.id"), nullable=True)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_strategies.id", ondelete="SET NULL"), nullable=True, index=True)
    source_strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_strategies.id", ondelete="SET NULL"), nullable=True, index=True)
    optimization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_strategy_optimization_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    backtest_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_backtest_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    baseline_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_backtest_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(24), default="candidate", index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    decision: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    baseline_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    comparison: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RadarSignal(Base):
    __tablename__ = "zi_quant_radar_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_users.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperPortfolio(Base):
    __tablename__ = "zi_quant_paper_portfolios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_users.id"), nullable=True)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_strategies.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    visibility: Mapped[Visibility] = mapped_column(Enum(Visibility), default=Visibility.private)
    cash: Mapped[float] = mapped_column(Float, default=100000.0)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class PaperPosition(Base):
    __tablename__ = "zi_quant_paper_positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "symbol", name="uq_zi_quant_paper_position"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_paper_portfolios.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(16), ForeignKey("zi_quant_stocks.symbol"), index=True)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PaperOrder(Base):
    __tablename__ = "zi_quant_paper_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_paper_portfolios.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    shares: Mapped[int] = mapped_column(Integer)
    fee: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(24), default="filled")
    reason: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperEquitySnapshot(Base):
    __tablename__ = "zi_quant_paper_equity_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_paper_portfolios.id", ondelete="CASCADE"), index=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    cash: Mapped[float] = mapped_column(Float, default=0)
    market_value: Mapped[float] = mapped_column(Float, default=0)
    total_equity: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    daily_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class DataJob(Base):
    __tablename__ = "zi_quant_data_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), index=True)
    job_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.idle)
    schedule: Mapped[str] = mapped_column(String(80), default="manual")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class DataJobRun(Base):
    __tablename__ = "zi_quant_data_job_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_data_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    job_name: Mapped[str] = mapped_column(String(120), index=True)
    job_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.running, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class AdminAuditLog(Base):
    __tablename__ = "zi_quant_admin_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zi_quant_users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    target: Mapped[str] = mapped_column(String(200), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def table_names() -> list[str]:
    return sorted(Base.metadata.tables.keys())
