"""add data job run history

Revision ID: 20260611_0002
Revises: 20260611_0001
Create Date: 2026-06-11 00:00:01 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260611_0002"
down_revision = "20260611_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("zi_quant_data_job_runs"):
        op.create_table(
            "zi_quant_data_job_runs",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("job_id", sa.UUID(), nullable=True),
            sa.Column("job_name", sa.String(length=120), nullable=False),
            sa.Column("job_type", sa.String(length=40), nullable=False),
            sa.Column("status", postgresql.ENUM("idle", "running", "success", "failed", name="jobstatus", create_type=False), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["zi_quant_data_jobs.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    existing_indexes = {index["name"] for index in inspector.get_indexes("zi_quant_data_job_runs")}
    for name, columns in {
        op.f("ix_zi_quant_data_job_runs_job_id"): ["job_id"],
        op.f("ix_zi_quant_data_job_runs_job_name"): ["job_name"],
        op.f("ix_zi_quant_data_job_runs_job_type"): ["job_type"],
        op.f("ix_zi_quant_data_job_runs_started_at"): ["started_at"],
        op.f("ix_zi_quant_data_job_runs_status"): ["status"],
    }.items():
        if name not in existing_indexes:
            op.create_index(name, "zi_quant_data_job_runs", columns, unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_zi_quant_data_job_runs_status"), table_name="zi_quant_data_job_runs")
    op.drop_index(op.f("ix_zi_quant_data_job_runs_started_at"), table_name="zi_quant_data_job_runs")
    op.drop_index(op.f("ix_zi_quant_data_job_runs_job_type"), table_name="zi_quant_data_job_runs")
    op.drop_index(op.f("ix_zi_quant_data_job_runs_job_name"), table_name="zi_quant_data_job_runs")
    op.drop_index(op.f("ix_zi_quant_data_job_runs_job_id"), table_name="zi_quant_data_job_runs")
    op.drop_table("zi_quant_data_job_runs")
