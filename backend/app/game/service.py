"""Игровая логика: состояние, прогресс, завершение урока, синхронизация."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.game import economy as ec
from app.game.models import (
    Course, GameEvent, Lesson, QuestionAttempt, Unit, UserAchievement, UserProgress,
)
from app.game.schemas import StateOut
from app.models import User, UserState


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """SQLite отдаёт наивные datetime — приводим к UTC, чтобы арифметика не падала."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def _get_state_row(session: AsyncSession, user_id: uuid.UUID) -> UserState:
    state = await session.get(UserState, user_id)
    if state is None:                       # страховка для аккаунтов до появления модуля
        state = UserState(
            user_id=user_id, xp=0, level=1, lives=ec.MAX_LIVES,
            lives_updated_at=_now(), streak_count=0,
            streak_freezes=ec.STREAK_FREEZE_START,
        )
        session.add(state)
        await session.flush()
    return state


def _local_hour(dt: datetime, tz: str) -> int:
    """Час (0-23) в поясе игрока — для ачивок про время суток."""
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo(tz)).hour
    except Exception:
        return dt.hour


async def _count_units_done(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Сколько юнитов пройдено целиком (все уроки юнита завершены)."""
    totals = dict((await session.execute(
        select(Lesson.unit_id, func.count()).group_by(Lesson.unit_id))).all())
    done = dict((await session.execute(
        select(Lesson.unit_id, func.count())
        .join(UserProgress, UserProgress.lesson_id == Lesson.id)
        .where(UserProgress.user_id == user_id, UserProgress.best_total > 0)
        .group_by(Lesson.unit_id))).all())
    return sum(1 for uid, tot in totals.items() if tot > 0 and done.get(uid, 0) >= tot)


async def _gather_stats(session: AsyncSession, user_id: uuid.UUID,
                        state: UserState, context: dict) -> dict:
    """Статистика игрока для проверки ачивок.

    Накопленное считается из существующих таблиц (счётчиков не заводим),
    сигналы текущего события (быстрый урок, спасение потока, час) приходят
    в context. Идеальный урок = лучший результат без ошибок.
    """
    lessons_done = int(await session.scalar(
        select(func.count()).select_from(UserProgress).where(
            UserProgress.user_id == user_id, UserProgress.best_total > 0)) or 0)
    perfect = int(await session.scalar(
        select(func.count()).select_from(UserProgress).where(
            UserProgress.user_id == user_id,
            UserProgress.best_total > 0,
            UserProgress.best_correct == UserProgress.best_total)) or 0)
    reviews = int(await session.scalar(
        select(func.count()).select_from(GameEvent).where(
            GameEvent.user_id == user_id, GameEvent.type == "review_complete")) or 0)
    stats = {
        "lessons_done": lessons_done,
        "perfect_lessons": perfect,
        "reviews_done": reviews,
        "streak": state.streak_count,
        "level": ec.level_for_xp(state.xp),
        "xp": state.xp,
        "freezes": state.streak_freezes or 0,
        "units_done": await _count_units_done(session, user_id),
    }
    stats.update(context)      # daily_goal_met, streak_saved, fast_lesson, hour
    return stats


async def _award_achievements(session: AsyncSession, user_id: uuid.UUID, stats: dict):
    """Начислить новые ачивки. Возвращает список только что заработанных."""
    deserved = ec.earned_achievement_ids(stats)
    if not deserved:
        return []
    have = set((await session.scalars(
        select(UserAchievement.achievement_id).where(
            UserAchievement.user_id == user_id))).all())
    fresh = deserved - have
    new_list = []
    for aid in fresh:
        a = ec.ACHIEVEMENT_BY_ID.get(aid)
        if not a:
            continue
        session.add(UserAchievement(user_id=user_id, achievement_id=aid))
        new_list.append({"id": a["id"], "title": a["title"],
                         "desc": a["desc"], "icon": a["icon"]})
    return new_list


def _state_out(state: UserState, lives_res: ec.LivesResult,
               tz: str = "UTC", review_pending: int = 0) -> StateOut:
    today = ec.local_date(_now(), tz)
    daily_xp, goal, met = ec.daily_state(
        state.daily_xp or 0, state.daily_date, state.daily_goal_xp or ec.DEFAULT_DAILY_GOAL_XP, today
    )
    return StateOut(
        xp=state.xp,
        level=ec.level_for_xp(state.xp),
        xp_to_next_level=ec.xp_to_next_level(state.xp),
        lives=lives_res.lives,
        max_lives=ec.MAX_LIVES,
        seconds_to_next_life=lives_res.seconds_to_next,
        streak_count=state.streak_count,
        daily_xp=daily_xp,
        daily_goal_xp=goal,
        daily_goal_met=met,
        review_pending=review_pending,
        streak_freezes=state.streak_freezes if state.streak_freezes is not None else ec.STREAK_FREEZE_START,
    )


async def count_review_pending(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(QuestionAttempt).where(
            QuestionAttempt.user_id == user_id, QuestionAttempt.needs_review.is_(True)
        )
    ) or 0)


async def _record_answers(session: AsyncSession, user_id: uuid.UUID,
                          lesson_id: uuid.UUID, answers, now: datetime) -> None:
    """Запомнить результат по каждому вопросу.

    needs_review ставится по ПОСЛЕДНЕМУ ответу: ошибся — вопрос попадает
    в очередь повторения, ответил верно — уходит из неё.
    """
    for a in answers:
        row = await session.scalar(
            select(QuestionAttempt).where(
                QuestionAttempt.user_id == user_id,
                QuestionAttempt.lesson_id == lesson_id,
                QuestionAttempt.question_id == a.question_id,
            )
        )
        if row is None:
            row = QuestionAttempt(
                user_id=user_id, lesson_id=lesson_id, question_id=a.question_id,
                total_attempts=0, wrong_attempts=0, needs_review=False,
            )
            session.add(row)
        row.total_attempts += 1
        if not a.correct:
            row.wrong_attempts += 1
        row.needs_review = not a.correct
        row.last_seen_at = now


async def get_state(session: AsyncSession, user_id: uuid.UUID, commit: bool = True) -> StateOut:
    """Текущее состояние. Жизни досчитываются на лету по серверному времени."""
    state = await _get_state_row(session, user_id)
    res = ec.regen_lives(state.lives, _aware(state.lives_updated_at), _now())
    if res.lives != state.lives:
        state.lives = res.lives
        state.lives_updated_at = res.updated_at
        if commit:
            await session.commit()
    user = await session.get(User, user_id)
    tz = (user.timezone if user else None) or "UTC"
    pending = await count_review_pending(session, user_id)
    return _state_out(state, res, tz, pending)


async def get_course_tree(session: AsyncSession, user_id: uuid.UUID) -> tuple[list[dict], StateOut]:
    """Дерево курсов с прогрессом и статусами разблокировки.

    Правило: урок доступен, если пройден предыдущий в юните (первый — всегда).
    """
    courses = (await session.scalars(select(Course).order_by(Course.order))).all()
    units = (await session.scalars(select(Unit).order_by(Unit.order))).all()
    lessons = (await session.scalars(select(Lesson).order_by(Lesson.order))).all()
    progress_rows = (
        await session.scalars(select(UserProgress).where(UserProgress.user_id == user_id))
    ).all()
    progress = {p.lesson_id: p for p in progress_rows}

    tree = []
    for course in courses:
        unit_nodes = []
        for unit in [u for u in units if u.course_id == course.id]:
            lesson_nodes = []
            prev_done = True                     # первый урок юнита всегда доступен
            for lesson in [l for l in lessons if l.unit_id == unit.id]:
                p = progress.get(lesson.id)
                done = bool(p and p.completions > 0)
                status = "done" if done else ("available" if prev_done else "locked")
                lesson_nodes.append({
                    "id": lesson.id, "slug": lesson.slug, "title": lesson.title,
                    "order": lesson.order, "version": lesson.version,
                    "question_count": lesson.question_count, "status": status,
                    "completions": p.completions if p else 0,
                    "best_correct": p.best_correct if p else 0,
                    "best_total": p.best_total if p else 0,
                })
                prev_done = done
            unit_nodes.append({
                "id": unit.id, "slug": unit.slug, "title": unit.title,
                "order": unit.order, "lessons": lesson_nodes,
            })
        tree.append({
            "id": course.id, "slug": course.slug, "title": course.title,
            "order": course.order, "units": unit_nodes,
        })

    state = await get_state(session, user_id)
    return tree, state


async def get_lesson(session: AsyncSession, lesson_id: uuid.UUID) -> Lesson:
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise AppError(404, "lesson_not_found", "Урок не найден")
    return lesson


async def check_can_start(session: AsyncSession, user: User, lesson_id: uuid.UUID) -> None:
    """Мягкий лимит капель: НОВЫЙ урок нельзя начать без капель.

    Уже пройденные уроки (повтор) и разбор ошибок доступны всегда — блокируется
    только продвижение по новому материалу. Капли возвращаются со временем
    и за пройденный разбор ошибок.
    """
    state = await _get_state_row(session, user.id)
    lives = ec.regen_lives(state.lives, _aware(state.lives_updated_at), _now()).lives
    if lives > 0:
        return
    done = await session.scalar(
        select(UserProgress).where(
            UserProgress.user_id == user.id,
            UserProgress.lesson_id == lesson_id,
            UserProgress.best_total > 0))
    if done is None:                       # урок ещё не пройден → это новый материал
        raise AppError(403, "no_lives",
                       "Капли кончились. Разбери ошибки, чтобы вернуть каплю, "
                       "или подожди, пока восстановятся.")


async def _apply_completion(
    session: AsyncSession, user: User, lesson: Lesson, data, now: datetime
) -> tuple[int, str]:
    """Начислить результат урока. Возвращает (xp, статус урока)."""
    if data.correct > data.total:
        raise AppError(400, "invalid_result", "Правильных ответов больше, чем вопросов")
    # Мягкая проверка на вменяемость: total должен совпадать с реальным уроком.
    if lesson.question_count and data.total != lesson.question_count:
        raise AppError(400, "invalid_result", "Число вопросов не совпадает с уроком")

    progress = await session.scalar(
        select(UserProgress).where(
            UserProgress.user_id == user.id, UserProgress.lesson_id == lesson.id
        )
    )
    is_repeat = bool(progress and progress.completions > 0)

    if progress is None:
        # Значения указываем явно: server_default срабатывает только при вставке
        # в БД, а нам нужно считать прямо сейчас, до flush.
        progress = UserProgress(
            user_id=user.id, lesson_id=lesson.id,
            completions=0, best_correct=0, best_total=0,
        )
        session.add(progress)
    progress.completions += 1
    if data.correct > progress.best_correct:
        progress.best_correct = data.correct
        progress.best_total = data.total
    progress.completed_at = now
    progress.updated_at = now

    state = await _get_state_row(session, user.id)

    # 1) опыт — считает сервер по присланным ответам
    xp = ec.xp_for_lesson(data.correct, data.total, is_repeat)
    state.xp += xp

    # 2) жизни: сначала досчитать накопленные, потом списать за ошибки
    lives_res = ec.regen_lives(state.lives, _aware(state.lives_updated_at), now)
    lives_res = ec.spend_lives(lives_res.lives, lives_res.updated_at, data.mistakes, now)
    state.lives = lives_res.lives
    state.lives_updated_at = lives_res.updated_at

    # 3) поток с заморозкой — по местной дате игрока
    today = ec.local_date(now, user.timezone or "UTC")
    (state.streak_count, state.streak_last_active,
     state.streak_freezes, consumed, _earned_freeze) = ec.apply_streak(
        state.streak_count, state.streak_last_active, today,
        state.streak_freezes if state.streak_freezes is not None else ec.STREAK_FREEZE_START,
    )
    streak_saved = consumed > 0

    # 4) дневная цель
    state.daily_xp, state.daily_date = ec.apply_daily_progress(
        state.daily_xp or 0, state.daily_date, today, xp
    )

    # 5) память по каждому вопросу — основа разбора ошибок
    if getattr(data, "answers", None):
        await _record_answers(session, user.id, lesson.id, data.answers, now)

    state.updated_at = now

    # 6) ачивки — накопленная статистика + сигналы этого урока
    _, _, goal_met = ec.daily_state(
        state.daily_xp, state.daily_date,
        state.daily_goal_xp or ec.DEFAULT_DAILY_GOAL_XP, today)
    dur = data.duration_seconds
    context = {
        "daily_goal_met": goal_met,
        "streak_saved": streak_saved,
        "fast_lesson": dur is not None and 0 < dur <= ec.FAST_LESSON_SECONDS,
        "hour": _local_hour(now, user.timezone or "UTC"),
    }
    stats = await _gather_stats(session, user.id, state, context)
    new_achievements = await _award_achievements(session, user.id, stats)

    return xp, "done", streak_saved, new_achievements


async def complete_lesson(
    session: AsyncSession, user: User, lesson_id: uuid.UUID, data
) -> tuple[int, bool, str, StateOut, list, bool]:
    """Идемпотентное завершение урока.

    Повторная отправка того же client_event_id вернёт прежний результат
    и НЕ начислит опыт второй раз.
    """
    now = _now()

    existing = await session.scalar(
        select(GameEvent).where(
            GameEvent.user_id == user.id,
            GameEvent.client_event_id == data.client_event_id,
        )
    )
    if existing is not None:
        state = await get_state(session, user.id)
        return existing.xp_awarded, True, "done", state, [], False

    lesson = await get_lesson(session, lesson_id)
    xp, status, streak_saved, new_achievements = await _apply_completion(
        session, user, lesson, data, now)

    session.add(GameEvent(
        user_id=user.id,
        client_event_id=data.client_event_id,
        lesson_id=lesson.id,
        type="lesson_complete",
        payload={
            "correct": data.correct, "total": data.total, "mistakes": data.mistakes,
            "duration_seconds": data.duration_seconds,
        },
        xp_awarded=xp,
        client_ts=data.client_ts,
    ))

    try:
        await session.commit()
    except IntegrityError:
        # Гонка: то же событие прилетело параллельно и успело записаться первым.
        await session.rollback()
        prior = await session.scalar(
            select(GameEvent).where(
                GameEvent.user_id == user.id,
                GameEvent.client_event_id == data.client_event_id,
            )
        )
        state = await get_state(session, user.id)
        return (prior.xp_awarded if prior else 0), True, "done", state, [], False

    state = await get_state(session, user.id, commit=False)
    return xp, False, status, state, new_achievements, streak_saved


async def sync_events(session: AsyncSession, user: User, events: list) -> tuple[list[dict], StateOut]:
    """Пакетная обработка офлайн-очереди.

    Каждое событие обрабатывается независимо: ошибка в одном не роняет остальные.
    """
    user_id = user.id                      # запоминаем до возможных откатов
    results = []
    for ev in events:
        try:
            xp, duplicate, _status, _state, _ach, _saved = await complete_lesson(session, user, ev.lesson_id, ev)
            results.append({
                "client_event_id": ev.client_event_id, "accepted": True,
                "duplicate": duplicate, "xp_awarded": xp, "error": None,
            })
        except AppError as e:
            await session.rollback()
            # rollback «протухает» объекты сессии — перечитываем пользователя,
            # иначе следующая итерация упадёт на ленивой подгрузке.
            user = await session.get(User, user_id)
            results.append({
                "client_event_id": ev.client_event_id, "accepted": False,
                "duplicate": False, "xp_awarded": 0, "error": e.code,
            })

    state = await get_state(session, user_id)
    return results, state


# ===================== РАЗБОР ОШИБОК =====================

async def get_review(session: AsyncSession, user_id: uuid.UUID) -> tuple[int, list[dict]]:
    """Вопросы, которые игрок завалил и ещё не исправил.

    Сначала самые давние ошибки: то, что забыто сильнее всего, важнее повторить.
    """
    total = await count_review_pending(session, user_id)
    rows = (await session.scalars(
        select(QuestionAttempt)
        .where(QuestionAttempt.user_id == user_id, QuestionAttempt.needs_review.is_(True))
        .order_by(QuestionAttempt.last_seen_at.asc())
        .limit(ec.REVIEW_BATCH_SIZE)
    )).all()
    if not rows:
        return total, []

    lessons = {
        l.id: l for l in (await session.scalars(
            select(Lesson).where(Lesson.id.in_({r.lesson_id for r in rows}))
        )).all()
    }

    out = []
    for r in rows:
        lesson = lessons.get(r.lesson_id)
        if lesson is None:
            continue
        question = next(
            (q for q in lesson.content.get("questions", []) if q.get("id") == r.question_id),
            None,
        )
        if question is None:
            # Вопрос исчез из урока при обновлении контента — чистим хвост,
            # иначе он навсегда застрянет в очереди повторения.
            await session.delete(r)
            continue
        out.append({
            "lesson_id": lesson.id, "lesson_title": lesson.title,
            "question_id": r.question_id, "wrong_attempts": r.wrong_attempts,
            "question": question,
        })
    await session.commit()
    return total, out


async def complete_review(
    session: AsyncSession, user: User, data
) -> tuple[int, bool, int, int, StateOut, list, bool]:
    """Завершение разбора. Идемпотентно, как и обычный урок."""
    now = _now()

    existing = await session.scalar(
        select(GameEvent).where(
            GameEvent.user_id == user.id,
            GameEvent.client_event_id == data.client_event_id,
        )
    )
    if existing is not None:
        state = await get_state(session, user.id)
        return existing.xp_awarded, True, 0, state.review_pending, state, [], False

    resolved = 0
    for a in data.answers:
        row = await session.scalar(
            select(QuestionAttempt).where(
                QuestionAttempt.user_id == user.id,
                QuestionAttempt.question_id == a.question_id,
                QuestionAttempt.needs_review.is_(True),
            )
        )
        if row is None:
            continue
        row.total_attempts += 1
        row.last_seen_at = now
        if a.correct:
            row.needs_review = False       # исправил — уходит из очереди
            resolved += 1
        else:
            row.wrong_attempts += 1

    correct_count = sum(1 for a in data.answers if a.correct)
    xp = ec.xp_for_review(correct_count)

    state = await _get_state_row(session, user.id)
    state.xp += xp
    today = ec.local_date(now, user.timezone or "UTC")
    state.daily_xp, state.daily_date = ec.apply_daily_progress(
        state.daily_xp or 0, state.daily_date, today, xp
    )
    # Разбор ошибок тоже поддерживает поток: это полноценное занятие.
    (state.streak_count, state.streak_last_active,
     state.streak_freezes, consumed, _ef) = ec.apply_streak(
        state.streak_count, state.streak_last_active, today,
        state.streak_freezes if state.streak_freezes is not None else ec.STREAK_FREEZE_START,
    )
    streak_saved = consumed > 0

    # Разбор ошибок возвращает каплю — замыкаем петлю мягкого лимита:
    # кончились капли → идёшь в разбор → получаешь каплю обратно и продолжаешь.
    _life = ec.grant_lives(state.lives, _aware(state.lives_updated_at), 1, now)
    state.lives, state.lives_updated_at = _life.lives, _life.updated_at

    state.updated_at = now

    session.add(GameEvent(
        user_id=user.id, client_event_id=data.client_event_id, lesson_id=None,
        type="review_complete",
        payload={"answers": len(data.answers), "correct": correct_count, "resolved": resolved},
        xp_awarded=xp, client_ts=None,
    ))

    # ачивки (событие review_complete добавляется в этой же транзакции ниже,
    # но reviews_done считает уже записанные — новое учтётся при следующем заходе,
    # что нормально: reviewer выдаётся не мгновенно, а закрепляется)
    _, _, goal_met = ec.daily_state(
        state.daily_xp, state.daily_date,
        state.daily_goal_xp or ec.DEFAULT_DAILY_GOAL_XP, today)
    context = {
        "daily_goal_met": goal_met,
        "streak_saved": streak_saved,
        "fast_lesson": False,
        "hour": _local_hour(now, user.timezone or "UTC"),
    }
    stats = await _gather_stats(session, user.id, state, context)
    new_achievements = await _award_achievements(session, user.id, stats)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        state_out = await get_state(session, user.id)
        return 0, True, 0, state_out.review_pending, state_out, [], False

    out = await get_state(session, user.id, commit=False)
    return xp, False, resolved, out.review_pending, out, new_achievements, streak_saved


async def set_daily_goal(session: AsyncSession, user_id: uuid.UUID, goal: int) -> StateOut:
    state = await _get_state_row(session, user_id)
    state.daily_goal_xp = goal
    await session.commit()
    return await get_state(session, user_id, commit=False)


async def get_achievements(session: AsyncSession, user_id: uuid.UUID) -> tuple[int, list[dict]]:
    """Все ачивки со статусом (заработана/нет), в порядке каталога."""
    have = set((await session.scalars(
        select(UserAchievement.achievement_id).where(
            UserAchievement.user_id == user_id))).all())
    out = [{"id": a["id"], "title": a["title"], "desc": a["desc"],
            "icon": a["icon"], "earned": a["id"] in have}
           for a in ec.ACHIEVEMENTS]
    return len(have), out
