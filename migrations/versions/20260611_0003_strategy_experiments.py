"""add strategy experiment records

Revision ID: 20260611_0003
Revises: 20260611_0002
Create Date: 2026-06-11 00:00:02 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260611_0003"
down_revision = "20260611_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("zi_quant_strategy_experiments"):
        op.create_table(
            "zi_quant_strategy_experiments",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("owner_id", sa.UUID(), nullable=True),
            sa.Column("strategy_id", sa.UUID(), nullable=True),
            sa.Column("source_strategy_id", sa.UUID(), nullable=True),
            sa.Column("optimization_id", sa.UUID(), nullable=True),
            sa.Column("backtest_run_id", sa.UUID(), nullable=True),
            sa.Column("baseline_run_id", sa.UUID(), nullable=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("passed", sa.Boolean(), nullable=False),
            sa.Column("decision", sa.Text(), nullable=False),
            sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("baseline_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("comparison", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["backtest_run_id"], ["zi_quant_backtest_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["baseline_run_id"], ["zi_quant_backtest_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["optimization_id"], ["zi_quant_strategy_optimization_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["owner_id"], ["zi_quant_users.id"]),
            sa.ForeignKeyConstraint(["source_strategy_id"], ["zi_quant_strategies.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["strategy_id"], ["zi_quant_strategies.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    existing_indexes = {index["name"] for index in inspector.get_indexes("zi_quant_strategy_experiments")}
    for name, columns in {
        op.f("ix_zi_quant_strategy_experiments_backtest_run_id"): ["backtest_run_id"],
        op.f("ix_zi_quant_strategy_experiments_baseline_run_id"): ["baseline_run_id"],
        op.f("ix_zi_quant_strategy_experiments_created_at"): ["created_at"],
        op.f("ix_zi_quant_strategy_experiments_name"): ["name"],
        op.f("ix_zi_quant_strategy_experiments_optimization_id"): ["optimization_id"],
        op.f("ix_zi_quant_strategy_experiments_passed"): ["passed"],
        op.f("ix_zi_quant_strategy_experiments_source_strategy_id"): ["source_strategy_id"],
        op.f("ix_zi_quant_strategy_experiments_status"): ["status"],
        op.f("ix_zi_quant_strategy_experiments_strategy_id"): ["strategy_id"],
    }.items():
        if name not in existing_indexes:
            op.create_index(name, "zi_quant_strategy_experiments", columns, unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_zi_quant_strategy_experiments_strategy_id"), table_name="zi_quant_strategy_experiments")
    op.drop_index(op.f("ix_zi_quant_strategy_experiments_status"), table_name="zi_quant_strategy_experiments")
    op.drop_index(op.f("ix_zi_quant_strategy_experiments_source_strategy_id"), table_name="zi_quant_strategy_experiments")
    op.drop_index(op.f("ix_zi_quant_strategy_experiments_passed"), table_name="zi_quant_strategy_experiments")
    op.drop_index(op.f("ix_zi_quant_strategy_experiments_optimization_id"), table_name="zi_quant_strategy_experiments")
    op.drop_index(op.f("ix_zi_quant_strategy_experiments_name"), table_name="zi_quant_strategy_experiments")
    op.drop_index(op.f("ix_zi_quant_strategy_experiments_created_at"), table_name="zi_quant_strategy_experiments")
    op.drop_index(op.f("ix_zi_quant_strategy_experiments_baseline_run_id"), table_name="zi_quant_strategy_experiments")
    op.drop_index(op.f("ix_zi_quant_strategy_experiments_backtest_run_id"), table_name="zi_quant_strategy_experiments")
    op.drop_table("zi_quant_strategy_experiments")
