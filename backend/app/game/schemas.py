import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class StateOut(BaseModel):
    xp: int
    level: int
    xp_to_next_level: int | None
    lives: int
    max_lives: int
    seconds_to_next_life: int | None
    streak_count: int
    # дневная цель
    daily_xp: int = 0
    daily_goal_xp: int = 20
    daily_goal_met: bool = False
    # сколько вопросов ждёт разбора
    review_pending: int = 0
    # заморозки потока
    streak_freezes: int = 0


class LessonNode(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    order: int
    version: int
    question_count: int
    status: str                       # locked | available | done
    completions: int
    best_correct: int
    best_total: int


class UnitNode(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    order: int
    lessons: list[LessonNode]


class CourseNode(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    order: int
    units: list[UnitNode]


class CourseTreeOut(BaseModel):
    courses: list[CourseNode]
    state: StateOut


class LessonContentOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    version: int
    question_count: int
    content: dict


class AnswerIn(BaseModel):
    """Результат по одному вопросу — нужен, чтобы помнить, что человек завалил."""
    question_id: str = Field(min_length=1, max_length=64)
    correct: bool


class CompleteIn(BaseModel):
    """Результат прохождения урока, присланный клиентом.

    client_event_id — ключ идемпотентности: повторная отправка того же
    события не начислит опыт дважды.
    """
    client_event_id: str = Field(min_length=8, max_length=64)
    correct: int = Field(ge=0, le=1000)
    total: int = Field(ge=1, le=1000)
    mistakes: int = Field(default=0, ge=0, le=1000)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    client_ts: datetime | None = None
    # Необязательно ради совместимости со старыми клиентами, но без этого
    # не работает разбор ошибок — вопросы для повторения взять неоткуда.
    answers: list[AnswerIn] = Field(default_factory=list, max_length=200)


class EarnedAchievement(BaseModel):
    id: str
    title: str
    desc: str
    icon: str


class CompleteOut(BaseModel):
    xp_awarded: int
    duplicate: bool                   # true — событие уже было учтено раньше
    lesson_status: str
    state: StateOut
    new_achievements: list[EarnedAchievement] = Field(default_factory=list)
    streak_saved: bool = False        # заморозка спасла поток на этом заходе


class SyncIn(BaseModel):
    events: list["SyncEvent"] = Field(max_length=100)


class SyncEvent(CompleteIn):
    lesson_id: uuid.UUID


class SyncResultItem(BaseModel):
    client_event_id: str
    accepted: bool
    duplicate: bool
    xp_awarded: int
    error: str | None = None


class SyncOut(BaseModel):
    results: list[SyncResultItem]
    state: StateOut


SyncIn.model_rebuild()


# ---------- разбор ошибок ----------

class ReviewQuestion(BaseModel):
    lesson_id: uuid.UUID
    lesson_title: str
    question_id: str
    wrong_attempts: int
    question: dict                 # сам вопрос из контента урока


class ReviewOut(BaseModel):
    total_pending: int
    questions: list[ReviewQuestion]


class ReviewCompleteIn(BaseModel):
    client_event_id: str = Field(min_length=8, max_length=64)
    answers: list[AnswerIn] = Field(min_length=1, max_length=200)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)


class ReviewCompleteOut(BaseModel):
    xp_awarded: int
    duplicate: bool
    resolved: int                  # сколько вопросов ушло из очереди повторения
    still_pending: int
    state: StateOut
    new_achievements: list[EarnedAchievement] = Field(default_factory=list)
    streak_saved: bool = False


# ---------- дневная цель ----------

class DailyGoalIn(BaseModel):
    daily_goal_xp: int = Field(ge=5, le=200)


class AchievementOut(BaseModel):
    id: str
    title: str
    desc: str
    icon: str
    earned: bool


class AchievementsOut(BaseModel):
    earned_count: int
    total: int
    achievements: list[AchievementOut]
