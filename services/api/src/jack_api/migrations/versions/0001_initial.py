"""Initial schema: devices, settings, audit_events, tasks, task_events.

Revision ID: 0001
Revises:
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("os_version", sa.String(255), nullable=False),
        sa.Column("app_version", sa.String(32), nullable=False),
        sa.Column("first_seen_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target", sa.String(512), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_events_seq", "audit_events", ["seq"], unique=True)
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("command_text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("resume_status", sa.String(32), nullable=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("completed_at", TS, nullable=True),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_updated_at", "tasks", ["updated_at"])
    op.create_table(
        "task_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36),
                  sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("occurred_at", TS, nullable=False),
        sa.UniqueConstraint("task_id", "seq"),
    )
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"])


def downgrade() -> None:
    op.drop_table("task_events")
    op.drop_table("tasks")
    op.drop_table("audit_events")
    op.drop_table("settings")
    op.drop_table("devices")
