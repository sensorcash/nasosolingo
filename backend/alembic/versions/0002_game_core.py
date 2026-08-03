"""game core: courses, units, lessons, progress, events

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "units",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("course_id", sa.Uuid(),
                  sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "lessons",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("unit_id", sa.Uuid(),
                  sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "user_progress",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.Uuid(),
                  sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("completions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("best_correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("best_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "lesson_id", name="uq_progress_user_lesson"),
    )
    op.create_index("idx_progress_user", "user_progress", ["user_id"])
    op.create_index("idx_progress_lesson", "user_progress", ["lesson_id"])

    op.create_table(
        "game_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_event_id", sa.Text(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), sa.ForeignKey("lessons.id", ondelete="SET NULL")),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("xp_awarded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("client_ts", sa.DateTime(timezone=True)),
        sa.Column("server_ts", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "client_event_id", name="uq_event_user_client"),
    )
    op.create_index("idx_events_user", "game_events", ["user_id"])


def downgrade() -> None:
    for table in ["game_events", "user_progress", "lessons", "units", "courses"]:
        op.drop_table(table)
