"""Requirement discovery sessions and their conversation (Milestone 5).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "requirement_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("category", sa.String(32), nullable=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("status", "category", "updated_at"):
        op.create_index(f"ix_requirement_sessions_{col}", "requirement_sessions", [col])
    op.create_table(
        "requirement_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36),
                  sa.ForeignKey("requirement_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("slot", sa.String(64), nullable=True),
        sa.Column("source", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_requirement_turns_session_id", "requirement_turns", ["session_id"])


def downgrade() -> None:
    op.drop_table("requirement_turns")
    op.drop_table("requirement_sessions")
