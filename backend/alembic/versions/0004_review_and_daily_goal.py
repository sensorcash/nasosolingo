"""question attempts (mistake review) + daily goal

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- разбор ошибок ---
    op.create_table(
        "question_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.Uuid(),
                  sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.Text(), nullable=False),
        sa.Column("total_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wrong_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "lesson_id", "question_id",
                            name="uq_attempt_user_question"),
    )
    op.create_index("idx_attempt_user", "question_attempts", ["user_id"])
    op.create_index("idx_attempt_lesson", "question_attempts", ["lesson_id"])
    # Основной запрос разбора: «мои вопросы, требующие повторения»
    op.create_index("idx_attempt_review", "question_attempts", ["user_id", "needs_review"])

    # --- дневная цель ---
    op.add_column("user_state",
                  sa.Column("daily_xp", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("user_state", sa.Column("daily_date", sa.Date(), nullable=True))
    op.add_column("user_state",
                  sa.Column("daily_goal_xp", sa.Integer(), nullable=False, server_default="20"))


def downgrade() -> None:
    op.drop_column("user_state", "daily_goal_xp")
    op.drop_column("user_state", "daily_date")
    op.drop_column("user_state", "daily_xp")
    op.drop_index("idx_attempt_review", table_name="question_attempts")
    op.drop_index("idx_attempt_lesson", table_name="question_attempts")
    op.drop_index("idx_attempt_user", table_name="question_attempts")
    op.drop_table("question_attempts")
