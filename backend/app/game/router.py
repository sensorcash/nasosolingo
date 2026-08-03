import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_session
from app.game import schemas as sc
from app.game import service as svc
from app.models import User

router = APIRouter(prefix="/api/v1/game", tags=["game"])


@router.get("/state", response_model=sc.StateOut)
async def get_state(user: User = Depends(get_current_user),
                    session: AsyncSession = Depends(get_session)):
    """Опыт, уровень, жизни (с досчётом регенерации) и поток."""
    return await svc.get_state(session, user.id)


@router.get("/courses", response_model=sc.CourseTreeOut)
async def get_courses(user: User = Depends(get_current_user),
                      session: AsyncSession = Depends(get_session)):
    """Дерево курсов с прогрессом и статусами уроков — это и есть карта пути."""
    tree, state = await svc.get_course_tree(session, user.id)
    return sc.CourseTreeOut(courses=tree, state=state)


@router.get("/lessons/{lesson_id}", response_model=sc.LessonContentOut)
async def get_lesson(lesson_id: uuid.UUID,
                     user: User = Depends(get_current_user),
                     session: AsyncSession = Depends(get_session)):
    """Контент урока в JSON. Клиент кэширует его для офлайна.

    Мягкий лимит: новый урок без капель отдаёт 403 no_lives. Повтор и разбор — всегда.
    """
    await svc.check_can_start(session, user, lesson_id)
    lesson = await svc.get_lesson(session, lesson_id)
    return sc.LessonContentOut(
        id=lesson.id, slug=lesson.slug, title=lesson.title, version=lesson.version,
        question_count=lesson.question_count, content=lesson.content,
    )


@router.post("/lessons/{lesson_id}/complete", response_model=sc.CompleteOut)
async def complete_lesson(lesson_id: uuid.UUID, data: sc.CompleteIn,
                          user: User = Depends(get_current_user),
                          session: AsyncSession = Depends(get_session)):
    """Завершение урока. Идемпотентно по client_event_id."""
    xp, duplicate, status, state, new_ach, saved = await svc.complete_lesson(session, user, lesson_id, data)
    return sc.CompleteOut(xp_awarded=xp, duplicate=duplicate, lesson_status=status, state=state,
                          new_achievements=new_ach, streak_saved=saved)


@router.post("/sync", response_model=sc.SyncOut)
async def sync(data: sc.SyncIn,
               user: User = Depends(get_current_user),
               session: AsyncSession = Depends(get_session)):
    """Пакетная отправка офлайн-очереди (до 100 событий за раз)."""
    results, state = await svc.sync_events(session, user, data.events)
    return sc.SyncOut(results=results, state=state)


@router.get("/review", response_model=sc.ReviewOut)
async def get_review(user: User = Depends(get_current_user),
                     session: AsyncSession = Depends(get_session)):
    """Вопросы, которые игрок завалил и ещё не исправил."""
    total, questions = await svc.get_review(session, user.id)
    return sc.ReviewOut(total_pending=total, questions=questions)


@router.post("/review/complete", response_model=sc.ReviewCompleteOut)
async def complete_review(data: sc.ReviewCompleteIn,
                          user: User = Depends(get_current_user),
                          session: AsyncSession = Depends(get_session)):
    """Завершение разбора ошибок. Идемпотентно по client_event_id."""
    xp, dup, resolved, pending, state, new_ach, saved = await svc.complete_review(session, user, data)
    return sc.ReviewCompleteOut(xp_awarded=xp, duplicate=dup, resolved=resolved,
                                still_pending=pending, state=state,
                                new_achievements=new_ach, streak_saved=saved)


@router.put("/daily-goal", response_model=sc.StateOut)
async def set_daily_goal(data: sc.DailyGoalIn,
                         user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_session)):
    """Изменить дневную цель по опыту."""
    return await svc.set_daily_goal(session, user.id, data.daily_goal_xp)


@router.get("/achievements", response_model=sc.AchievementsOut)
async def get_achievements(user: User = Depends(get_current_user),
                           session: AsyncSession = Depends(get_session)):
    """Все ачивки со статусом (заработана / нет)."""
    earned, items = await svc.get_achievements(session, user.id)
    return sc.AchievementsOut(earned_count=earned, total=len(items), achievements=items)
