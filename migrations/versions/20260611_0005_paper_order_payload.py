"""add paper order payload

Revision ID: 20260611_0005
Revises: 20260611_0004
Create Date: 2026-06-11 00:00:04 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260611_0005"
down_revision = "20260611_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("zi_quant_paper_orders")}
    if "payload" not in columns:
        op.add_column(
            "zi_quant_paper_orders",
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        )
        op.alter_column("zi_quant_paper_orders", "payload", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("zi_quant_paper_orders")}
    if "payload" in columns:
        op.drop_column("zi_quant_paper_orders", "payload")
