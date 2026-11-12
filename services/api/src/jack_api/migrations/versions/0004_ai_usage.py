"""AI provider usage records (tokens, estimated cost, failures).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_id", sa.String(32), nullable=False),
        sa.Column("billing_kind", sa.String(16), nullable=False),
        sa.Column("model_requested", sa.String(64), nullable=True),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("task_id", sa.String(36),
                  sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(14, 6), nullable=True),
        sa.Column("cost_source", sa.String(16), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
    )
    for col in ("occurred_at", "provider_id", "billing_kind", "model", "task_id", "project_id"):
        op.create_index(f"ix_usage_records_{col}", "usage_records", [col])


def downgrade() -> None:
    op.drop_table("usage_records")
