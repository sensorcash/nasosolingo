"""Тесты игрового слоя: заморозка потока и достижения."""
import uuid
from datetime import date, timedelta

import pytest

from app.game import economy as ec

GAME = "/api/v1/game"
AUTH = "/api/v1/auth"


def _ev():
    return "g-" + uuid.uuid4().hex[:12]


# ==================== ЗАМОРОЗКА ПОТОКА (чистая логика) ====================

def test_streak_consecutive_no_freeze_spent():
    d = date(2026, 7, 1)
    streak, last, freezes, consumed, earned = ec.apply_streak(3, d, d + timedelta(days=1), 2)
    assert streak == 4 and freezes == 2 and consumed == 0


def test_streak_gap_saved_by_freeze():
    """Пропущен один день, есть заморозка — поток продолжается, заморозка тратится."""
    d = date(2026, 7, 1)
    streak, last, freezes, consumed, earned = ec.apply_streak(5, d, d + timedelta(days=2), 2)
    assert streak == 6 and freezes == 1 and consumed == 1


def test_streak_resets_without_freeze():
    d = date(2026, 7, 1)
    streak, last, freezes, consumed, earned = ec.apply_streak(5, d, d + timedelta(days=3), 0)
    assert streak == 1 and consumed == 0


def test_streak_two_day_gap_needs_two_freezes():
    d = date(2026, 7, 1)
    # пропущено 2 дня, есть только 1 заморозка — не хватило, поток сгорел
    streak, last, freezes, consumed, earned = ec.apply_streak(5, d, d + timedelta(days=3), 1)
    assert streak == 1


def test_streak_earns_freeze_every_seven():
    d = date(2026, 7, 1)
    streak, last, freezes, consumed, earned = ec.apply_streak(6, d, d + timedelta(days=1), 1)
    assert streak == 7 and earned == 1 and freezes == 2


def test_streak_freezes_capped():
    d = date(2026, 7, 1)
    # уже максимум заморозок, милстоун не должен превысить потолок
    streak, last, freezes, consumed, earned = ec.apply_streak(6, d, d + timedelta(days=1),
                                                              ec.STREAK_FREEZE_MAX)
    assert freezes == ec.STREAK_FREEZE_MAX


def test_streak_same_day_noop():
    d = date(2026, 7, 1)
    streak, last, freezes, consumed, earned = ec.apply_streak(4, d, d, 2)
    assert streak == 4 and freezes == 2


# ==================== ДОСТИЖЕНИЯ (чистая логика) ====================

def test_achievements_catalog_has_ten():
    assert len(ec.ACHIEVEMENTS) == 17


def test_achievement_ids_unique():
    ids = [a["id"] for a in ec.ACHIEVEMENTS]
    assert len(ids) == len(set(ids))


def test_every_achievement_icon_known():
    # иконки должны существовать в наборе (совпадать со слотами клиента)
    known = {"streak", "xp", "life", "lifeEmpty", "level", "goal", "accuracy", "time",
             "done", "current", "locked", "ok", "fail", "warn", "close", "back",
             "arrow", "menu", "review", "lesson", "user", "export", "logout", "delete"}
    for a in ec.ACHIEVEMENTS:
        assert a["icon"] in known, a["id"]


def test_earned_ids_beginner():
    stats = {"lessons_done": 1, "perfect_lessons": 0, "daily_goal_met": False,
             "reviews_done": 0, "streak": 1, "level": 1}
    assert ec.earned_achievement_ids(stats) == {"first_lesson"}


def test_earned_ids_veteran():
    stats = {"lessons_done": 30, "perfect_lessons": 5, "daily_goal_met": True,
             "reviews_done": 5, "streak": 7, "level": 5}
    got = ec.earned_achievement_ids(stats)
    assert "all_lessons" in got and "streak_7" in got and "level_5" in got
    assert "streak_30" not in got


# ==================== ИНТЕГРАЦИЯ ====================

@pytest.mark.asyncio
async def test_state_has_freezes(auth_client, seeded):
    st = (await auth_client.get(f"{GAME}/state")).json()
    assert st["streak_freezes"] == 2


@pytest.mark.asyncio
async def test_achievements_endpoint(auth_client, seeded):
    r = await auth_client.get(f"{GAME}/achievements")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 17
    assert d["earned_count"] == 0
    assert all("earned" in a for a in d["achievements"])


@pytest.mark.asyncio
async def test_first_lesson_awards_achievement(auth_client, seeded):
    r = await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 2, "total": 2,
        "answers": [{"question_id": "q1", "correct": True},
                    {"question_id": "q2", "correct": True}]})
    ids = [a["id"] for a in r.json()["new_achievements"]]
    assert "first_lesson" in ids


@pytest.mark.asyncio
async def test_achievement_not_awarded_twice(auth_client, seeded):
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 2, "total": 2})
    r = await auth_client.post(f"{GAME}/lessons/{seeded['l2']}/complete", json={
        "client_event_id": _ev(), "correct": 1, "total": 5})
    ids = [a["id"] for a in r.json()["new_achievements"]]
    assert "first_lesson" not in ids


@pytest.mark.asyncio
async def test_achievements_require_auth(client, seeded):
    assert (await client.get(f"{GAME}/achievements")).status_code == 401


@pytest.mark.asyncio
async def test_fast_lesson_awards_speed(auth_client, seeded):
    """Урок пройден быстрее порога — ачивка «Быстрая рука»."""
    r = await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 2, "total": 2, "duration_seconds": 8})
    ids = [a["id"] for a in r.json()["new_achievements"]]
    assert "speed" in ids


@pytest.mark.asyncio
async def test_slow_lesson_no_speed(auth_client, seeded):
    r = await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 2, "total": 2, "duration_seconds": 200})
    ids = [a["id"] for a in r.json()["new_achievements"]]
    assert "speed" not in ids


@pytest.mark.asyncio
async def test_completing_all_lessons_awards_unit(auth_client, seeded):
    """Пройдены оба урока единственного юнита — ачивка «Юнит закрыт»."""
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 2, "total": 2, "duration_seconds": 100})
    await auth_client.post(f"{GAME}/lessons/{seeded['l2']}/complete", json={
        "client_event_id": _ev(), "correct": 5, "total": 5, "duration_seconds": 100})

    ach = (await auth_client.get(f"{GAME}/achievements")).json()
    earned = {a["id"] for a in ach["achievements"] if a["earned"]}
    assert "unit_done" in earned


@pytest.mark.asyncio
async def test_partial_unit_no_award(auth_client, seeded):
    """Один урок из двух — юнит ещё не закрыт."""
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 2, "total": 2, "duration_seconds": 100})
    ach = (await auth_client.get(f"{GAME}/achievements")).json()
    earned = {a["id"] for a in ach["achievements"] if a["earned"]}
    assert "unit_done" not in earned


# ==================== МЯГКИЙ ЛИМИТ КАПЕЛЬ ====================

def test_grant_lives_adds_one():
    from datetime import datetime, timezone
    now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert ec.grant_lives(0, now, 1, now).lives == 1


def test_grant_lives_caps_at_max():
    from datetime import datetime, timezone
    now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert ec.grant_lives(ec.MAX_LIVES, now, 1, now).lives == ec.MAX_LIVES


async def _set_lives(session_factory, email, lives):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.models import User, UserState
    async with session_factory() as s:
        u = (await s.scalars(select(User).where(User.email == email))).first()
        st = await s.get(UserState, u.id)
        st.lives = lives
        st.lives_updated_at = datetime.now(timezone.utc)
        await s.commit()


@pytest.mark.asyncio
async def test_new_lesson_blocked_without_lives(auth_client, seeded, session_factory):
    """0 капель → новый (не пройденный) урок отдаёт 403 no_lives."""
    await _set_lives(session_factory, auth_client.email, 0)
    r = await auth_client.get(f"{GAME}/lessons/{seeded['l2']}")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "no_lives"


@pytest.mark.asyncio
async def test_completed_lesson_repeatable_without_lives(auth_client, seeded, session_factory):
    """Пройденный урок можно повторять даже на 0 капель."""
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 2, "total": 2,
        "answers": [{"question_id": "q1", "correct": True},
                    {"question_id": "q2", "correct": True}]})
    await _set_lives(session_factory, auth_client.email, 0)
    r = await auth_client.get(f"{GAME}/lessons/{seeded['l1']}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_lesson_available_with_lives(auth_client, seeded, session_factory):
    """С каплями новый урок открывается нормально."""
    await _set_lives(session_factory, auth_client.email, 3)
    r = await auth_client.get(f"{GAME}/lessons/{seeded['l2']}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_review_restores_life(auth_client, seeded, session_factory):
    """Пройденный разбор ошибок возвращает каплю."""
    # создаём ошибку → попадает в очередь разбора
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 1, "total": 2, "mistakes": 1,
        "answers": [{"question_id": "q1", "correct": False},
                    {"question_id": "q2", "correct": True}]})
    await _set_lives(session_factory, auth_client.email, 0)

    review = (await auth_client.get(f"{GAME}/review")).json()
    assert review["questions"]
    answers = [{"question_id": q["question"].get("id", "q1"), "correct": True}
               for q in review["questions"]]
    r = await auth_client.post(f"{GAME}/review/complete", json={
        "client_event_id": _ev(), "answers": answers})
    assert r.status_code == 200
    assert r.json()["state"]["lives"] >= 1
