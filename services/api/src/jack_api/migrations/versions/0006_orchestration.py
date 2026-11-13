"""Durable orchestration: task steps, approvals, artifacts, workflow runs (Milestone 6).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.add_column(sa.Column("summary", sa.Text(), nullable=True))
    op.create_table(
        "task_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("agent_role", sa.String(64), nullable=False),
        sa.Column("idempotent", sa.Boolean(), nullable=False),
        sa.Column("needs_approval", sa.Boolean(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("approval_id", sa.String(36), nullable=True),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint("task_id", "key"),
    )
    op.create_index("ix_task_steps_task_id", "task_steps", ["task_id"])
    op.create_index("ix_task_steps_status", "task_steps", ["status"])
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("step_id", sa.String(36),
                  sa.ForeignKey("task_steps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(512), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("risk", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("requested_by", sa.String(64), nullable=False),
        sa.Column("requested_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("decided_via", sa.String(16), nullable=True),
        sa.Column("decided_at", TS, nullable=True),
    )
    op.create_index("ix_approvals_task_id", "approvals", ["task_id"])
    op.create_index("ix_approvals_status", "approvals", ["status"])
    op.create_table(
        "task_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("step_id", sa.String(36),
                  sa.ForeignKey("task_steps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_task_artifacts_task_id", "task_artifacts", ["task_id"])
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("workflow_id", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("ended_at", TS, nullable=True),
    )
    op.create_index("ix_workflow_runs_task_id", "workflow_runs", ["task_id"])


def downgrade() -> None:
    for t in ("workflow_runs", "task_artifacts", "approvals", "task_steps"):
        op.drop_table(t)
    with op.batch_alter_table("tasks") as b:
        b.drop_column("summary")
