"""achievements + streak freezes

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_achievements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("achievement_id", sa.Text(), nullable=False),
        sa.Column("earned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "achievement_id", name="uq_user_achievement"),
    )
    op.create_index("idx_ach_user", "user_achievements", ["user_id"])

    op.add_column("user_state",
                  sa.Column("streak_freezes", sa.Integer(), nullable=False, server_default="2"))


def downgrade() -> None:
    op.drop_column("user_state", "streak_freezes")
    op.drop_index("idx_ach_user", table_name="user_achievements")
    op.drop_table("user_achievements")
