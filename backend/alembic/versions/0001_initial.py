"""initial auth schema

Revision ID: 0001
Revises:
Create Date: 2026-07-23
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("nickname", sa.Text()),
        sa.Column("region", sa.Text()),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="Europe/Moscow"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_users_email", "users", ["email"])

    op.create_table(
        "user_state",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("lives", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("lives_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("streak_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("streak_last_active", sa.Date()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False, server_default="ios"),
        sa.Column("push_token", sa.Text()),
        sa.Column("push_provider", sa.Text(), server_default="apns"),
        sa.Column("app_version", sa.Text()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("devices.id", ondelete="SET NULL")),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_refresh_hash", "refresh_tokens", ["token_hash"])
    op.create_index("idx_refresh_user", "refresh_tokens", ["user_id"])
    op.create_index("idx_refresh_family", "refresh_tokens", ["family_id"])

    op.create_table(
        "email_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_email_tokens_hash", "email_tokens", ["token_hash"])


def downgrade() -> None:
    for table in ["email_tokens", "refresh_tokens", "devices", "user_state", "users"]:
        op.drop_table(table)
