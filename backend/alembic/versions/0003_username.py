"""add username for short login

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(40), nullable=True))
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.create_index("idx_users_username", "users", ["username"])


def downgrade() -> None:
    op.drop_index("idx_users_username", table_name="users")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.drop_column("users", "username")
