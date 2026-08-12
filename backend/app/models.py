import uuid
from datetime import datetime, date

from sqlalchemy import String, Boolean, Integer, BigInteger, Text, Date, DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # E-mail нормализуется в приложении (trim + lower), поэтому обычный unique text
    # достаточно для регистронезависимой уникальности (citext — альтернатива).
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    # Короткий логин — альтернатива e-mail при входе (нужен для dev-аккаунта).
    # Обычные пользователи регистрируются по e-mail, username у них пустой.
    username: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True, index=True)
    # Telegram Mini App: id пользователя Telegram. Пусто у обычных (веб) аккаунтов.
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    nickname: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(Text, default="Europe/Moscow", nullable=False)
    status: Mapped[str] = mapped_column(Text, default="active", nullable=False)  # active | blocked
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserState(Base):
    __tablename__ = "user_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    lives: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    lives_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    streak_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streak_last_active: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Дневная цель: сколько опыта набрано сегодня и какой день считается «сегодня».
    daily_xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    daily_goal_xp: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    # Заморозки потока: пропущенный день не сжигает поток, если есть запас.
    streak_freezes: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(Text, default="ios", nullable=False)
    push_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    push_provider: Mapped[str | None] = mapped_column(Text, default="apns", nullable=True)
    app_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)  # SHA-256
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # 'verify'
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
