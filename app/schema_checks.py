from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sqlalchemy import MetaData

from app.models import Base


CORE_TABLES = {
    "zi_quant_users",
    "zi_quant_stocks",
    "zi_quant_stock_pools",
    "zi_quant_stock_pool_members",
    "zi_quant_data_source_configs",
    "zi_quant_market_bars",
    "zi_quant_financial_reports",
    "zi_quant_factor_definitions",
    "zi_quant_factor_values",
    "zi_quant_strategies",
    "zi_quant_backtest_runs",
    "zi_quant_backtest_trades",
    "zi_quant_paper_portfolios",
    "zi_quant_paper_positions",
    "zi_quant_paper_orders",
    "zi_quant_data_jobs",
    "zi_quant_data_job_runs",
    "zi_quant_admin_audit_logs",
}


@dataclass(frozen=True)
class TableSummary:
    name: str
    columns: tuple[str, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[str, ...]
    unique_constraints: tuple[str, ...]


def summarize_metadata(metadata: MetaData | None = None) -> list[TableSummary]:
    metadata = metadata or Base.metadata
    summaries: list[TableSummary] = []
    for table in sorted(metadata.tables.values(), key=lambda item: item.name):
        summaries.append(
            TableSummary(
                name=table.name,
                columns=tuple(column.name for column in table.columns),
                primary_key=tuple(column.name for column in table.primary_key.columns),
                foreign_keys=tuple(sorted(f"{fk.parent.name}->{fk.column.table.name}.{fk.column.name}" for fk in table.foreign_keys)),
                unique_constraints=tuple(sorted(constraint.name or "" for constraint in table.constraints if constraint.__class__.__name__ == "UniqueConstraint")),
            )
        )
    return summaries


def schema_readiness(required_tables: Iterable[str] = CORE_TABLES, metadata: MetaData | None = None) -> dict[str, object]:
    summaries = summarize_metadata(metadata)
    present = {summary.name for summary in summaries}
    required = set(required_tables)
    missing = sorted(required - present)
    empty_primary_key = sorted(summary.name for summary in summaries if not summary.primary_key)
    return {
        "status": "ready" if not missing and not empty_primary_key else "degraded",
        "table_count": len(summaries),
        "required_table_count": len(required),
        "missing_tables": missing,
        "tables_without_primary_key": empty_primary_key,
        "tables": [summary.__dict__ for summary in summaries],
    }


def migration_readiness(project_root: Path | str = ".") -> dict[str, object]:
    root = Path(project_root)
    alembic_ini = root / "alembic.ini"
    versions_dir = root / "migrations" / "versions"
    versions = sorted(path.name for path in versions_dir.glob("*.py")) if versions_dir.exists() else []
    missing: list[str] = []
    if not alembic_ini.exists():
        missing.append("alembic.ini")
    if not versions_dir.exists():
        missing.append("migrations/versions")
    if not versions:
        missing.append("migration_versions")
    return {
        "status": "ready" if not missing else "degraded",
        "missing": missing,
        "revision_count": len(versions),
        "latest_revision_file": versions[-1] if versions else None,
    }
