"""add paper portfolio equity snapshots

Revision ID: 20260611_0004
Revises: 20260611_0003
Create Date: 2026-06-11 00:00:03 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260611_0004"
down_revision = "20260611_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("zi_quant_paper_equity_snapshots"):
        op.create_table(
            "zi_quant_paper_equity_snapshots",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("portfolio_id", sa.UUID(), nullable=False),
            sa.Column("snapshot_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("cash", sa.Float(), nullable=False),
            sa.Column("market_value", sa.Float(), nullable=False),
            sa.Column("total_equity", sa.Float(), nullable=False),
            sa.Column("unrealized_pnl", sa.Float(), nullable=False),
            sa.Column("realized_pnl", sa.Float(), nullable=False),
            sa.Column("daily_return", sa.Float(), nullable=True),
            sa.Column("total_return", sa.Float(), nullable=True),
            sa.Column("max_drawdown", sa.Float(), nullable=True),
            sa.Column("source", sa.String(length=40), nullable=False),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.ForeignKeyConstraint(["portfolio_id"], ["zi_quant_paper_portfolios.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    existing_indexes = {index["name"] for index in inspector.get_indexes("zi_quant_paper_equity_snapshots")}
    for name, columns in {
        op.f("ix_zi_quant_paper_equity_snapshots_portfolio_id"): ["portfolio_id"],
        op.f("ix_zi_quant_paper_equity_snapshots_snapshot_at"): ["snapshot_at"],
        op.f("ix_zi_quant_paper_equity_snapshots_source"): ["source"],
    }.items():
        if name not in existing_indexes:
            op.create_index(name, "zi_quant_paper_equity_snapshots", columns, unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_zi_quant_paper_equity_snapshots_source"), table_name="zi_quant_paper_equity_snapshots")
    op.drop_index(op.f("ix_zi_quant_paper_equity_snapshots_snapshot_at"), table_name="zi_quant_paper_equity_snapshots")
    op.drop_index(op.f("ix_zi_quant_paper_equity_snapshots_portfolio_id"), table_name="zi_quant_paper_equity_snapshots")
    op.drop_table("zi_quant_paper_equity_snapshots")
