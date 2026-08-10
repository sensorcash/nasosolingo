"""telegram_id for Mini App login

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_id", sa.BigInteger(), nullable=True))
    # уникальный индекс: и уникальность, и быстрый поиск; работает и на SQLite, и на Postgres
    op.create_index("idx_users_telegram_id", "users", ["telegram_id"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_users_telegram_id", table_name="users")
    op.drop_column("users", "telegram_id")
