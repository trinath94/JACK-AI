"""Notifications table (notification centre).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("task_id", sa.String(36),
                  sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_table("notifications")
