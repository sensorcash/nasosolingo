"""Агрегаты для аналитики: где спотыкаются, докуда доходят, кто активен.

Всё считается из уже существующих таблиц. Ключевое — question_attempts:
там для каждого вопроса видно, сколько раз на него отвечали и сколько ошибались,
то есть какие вопросы слишком сложные или сформулированы непонятно.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game.models import GameEvent, Lesson, QuestionAttempt, Unit, UserProgress
from app.models import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def overview(session: AsyncSession) -> dict:
    total_users = int(await session.scalar(select(func.count()).select_from(User)) or 0)
    week_ago = _now() - timedelta(days=7)
    active = int(await session.scalar(
        select(func.count(func.distinct(GameEvent.user_id)))
        .where(GameEvent.server_ts >= week_ago)) or 0)
    completions = int(await session.scalar(
        select(func.count()).select_from(GameEvent)
        .where(GameEvent.type == "lesson_complete")) or 0)
    total_xp = int(await session.scalar(select(func.coalesce(func.sum(GameEvent.xp_awarded), 0))) or 0)
    return {
        "total_users": total_users,
        "active_7d": active,
        "lesson_completions": completions,
        "total_xp_awarded": total_xp,
    }


async def lesson_funnel(session: AsyncSession) -> list[dict]:
    """Сколько РАЗНЫХ игроков дошли до каждого урока (в порядке курса).

    Провал по глубине показывает, где люди бросают.
    """
    rows = (await session.execute(
        select(Lesson.id, Lesson.title, Unit.title, Unit.order, Lesson.order,
               func.count(func.distinct(UserProgress.user_id)))
        .join(Unit, Unit.id == Lesson.unit_id)
        .outerjoin(UserProgress,
                   (UserProgress.lesson_id == Lesson.id) & (UserProgress.best_total > 0))
        .group_by(Lesson.id, Lesson.title, Unit.title, Unit.order, Lesson.order)
        .order_by(Unit.order, Lesson.order))).all()
    return [{"lesson": r[1], "unit": r[2], "players_completed": int(r[5])} for r in rows]


async def hardest_questions(session: AsyncSession, limit: int = 15) -> list[dict]:
    """Вопросы с самой высокой долей ошибок (минимум 2 попытки)."""
    rows = (await session.execute(
        select(QuestionAttempt.lesson_id, QuestionAttempt.question_id,
               func.sum(QuestionAttempt.total_attempts),
               func.sum(QuestionAttempt.wrong_attempts))
        .group_by(QuestionAttempt.lesson_id, QuestionAttempt.question_id))).all()

    # тексты вопросов из контента уроков
    lesson_ids = {r[0] for r in rows}
    lessons = {}
    if lesson_ids:
        for l in (await session.scalars(select(Lesson).where(Lesson.id.in_(lesson_ids)))).all():
            lessons[l.id] = l

    items = []
    for lesson_id, qid, total, wrong in rows:
        total, wrong = int(total or 0), int(wrong or 0)
        if total < 2:
            continue
        lesson = lessons.get(lesson_id)
        prompt = qid
        if lesson:
            q = next((x for x in lesson.content.get("questions", []) if x.get("id") == qid), None)
            if q:
                prompt = q.get("prompt", qid)
        items.append({
            "lesson": lesson.title if lesson else "?",
            "question": prompt,
            "attempts": total,
            "wrong": wrong,
            "wrong_rate": round(wrong / total, 2),
        })
    items.sort(key=lambda x: (x["wrong_rate"], x["attempts"]), reverse=True)
    return items[:limit]


async def daily_activity(session: AsyncSession, days: int = 14) -> list[dict]:
    """Активность по дням за последние N дней (по событиям)."""
    since = _now() - timedelta(days=days)
    rows = (await session.scalars(
        select(GameEvent.server_ts).where(GameEvent.server_ts >= since))).all()
    buckets: dict[str, int] = {}
    for ts in rows:
        if ts is None:
            continue
        key = ts.date().isoformat()
        buckets[key] = buckets.get(key, 0) + 1
    out = []
    for i in range(days - 1, -1, -1):
        day = (_now() - timedelta(days=i)).date().isoformat()
        out.append({"date": day, "events": buckets.get(day, 0)})
    return out


async def full_report(session: AsyncSession) -> dict:
    return {
        "overview": await overview(session),
        "funnel": await lesson_funnel(session),
        "hardest_questions": await hardest_questions(session),
        "daily_activity": await daily_activity(session),
    }
