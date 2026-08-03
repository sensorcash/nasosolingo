import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Integer, Text, DateTime, ForeignKey, Uuid, UniqueConstraint, JSON, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("units.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Контент урока целиком в JSON — новые вопросы добавляются БЕЗ релиза приложения.
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserProgress(Base):
    __tablename__ = "user_progress"
    __table_args__ = (UniqueConstraint("user_id", "lesson_id", name="uq_progress_user_lesson"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    completions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    best_correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    best_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GameEvent(Base):
    """Лог событий + защита от двойного начисления при офлайн-синхронизации.

    client_event_id генерирует клиент. Повторная отправка того же события
    не начислит опыт второй раз — это делает синхронизацию безопасной.
    """
    __tablename__ = "game_events"
    __table_args__ = (UniqueConstraint("user_id", "client_event_id", name="uq_event_user_client"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lessons.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)      # lesson_complete
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    client_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    server_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionAttempt(Base):
    """Память о том, как игрок отвечал на каждый конкретный вопрос.

    Это основа «разбора ошибок»: без неё заваленные вопросы исчезают
    вместе с экраном результата, и повторить их невозможно.
    """
    __tablename__ = "question_attempts"
    __table_args__ = (
        UniqueConstraint("user_id", "lesson_id", "question_id", name="uq_attempt_user_question"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[str] = mapped_column(Text, nullable=False)
    total_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wrong_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # needs_review = последний ответ был неверным. Снимается, когда вопрос
    # успешно закрыт в разборе — тогда он уходит из очереди повторения.
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserAchievement(Base):
    """Заработанные ачивки. Одна строка — одна ачивка у игрока."""
    __tablename__ = "user_achievements"
    __table_args__ = (
        UniqueConstraint("user_id", "achievement_id", name="uq_user_achievement"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    achievement_id: Mapped[str] = mapped_column(Text, nullable=False)
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
