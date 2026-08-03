"""Тесты: удаление аккаунта, разбор ошибок, дневная цель."""
import uuid
from datetime import date, timedelta

import pytest

from app.game import economy as ec

AUTH = "/api/v1/auth"
GAME = "/api/v1/game"
PW = "nasos-parol-1"


def _ev():
    return "t-" + uuid.uuid4().hex[:12]


# ==================== ДНЕВНАЯ ЦЕЛЬ ====================

def test_daily_progress_accumulates_same_day():
    d = date(2026, 7, 23)
    assert ec.apply_daily_progress(10, d, d, 15) == (25, d)


def test_daily_progress_resets_next_day():
    d = date(2026, 7, 23)
    assert ec.apply_daily_progress(90, d, d + timedelta(days=1), 5) == (5, d + timedelta(days=1))


def test_daily_progress_first_ever():
    d = date(2026, 7, 23)
    assert ec.apply_daily_progress(0, None, d, 12) == (12, d)


def test_daily_state_hides_yesterday():
    """Вчерашние 90 очков не должны показываться как сегодняшний прогресс."""
    d = date(2026, 7, 23)
    cur, goal, met = ec.daily_state(90, d, 20, d + timedelta(days=1))
    assert (cur, met) == (0, False)


def test_daily_state_goal_met():
    d = date(2026, 7, 23)
    cur, goal, met = ec.daily_state(25, d, 20, d)
    assert cur == 25 and goal == 20 and met is True


def test_daily_state_falls_back_on_broken_goal():
    d = date(2026, 7, 23)
    _, goal, _ = ec.daily_state(0, d, 0, d)
    assert goal == ec.DEFAULT_DAILY_GOAL_XP


@pytest.mark.asyncio
async def test_state_exposes_daily_goal(auth_client, seeded):
    s = (await auth_client.get(f"{GAME}/state")).json()
    assert s["daily_xp"] == 0
    assert s["daily_goal_xp"] == ec.DEFAULT_DAILY_GOAL_XP
    assert s["daily_goal_met"] is False


@pytest.mark.asyncio
async def test_lesson_fills_daily_goal(auth_client, seeded):
    r = await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete",
                               json={"client_event_id": _ev(), "correct": 2, "total": 2})
    st = r.json()["state"]
    assert st["daily_xp"] == r.json()["xp_awarded"]
    assert st["daily_goal_met"] is (st["daily_xp"] >= st["daily_goal_xp"])


@pytest.mark.asyncio
async def test_change_daily_goal(auth_client, seeded):
    r = await auth_client.put(f"{GAME}/daily-goal", json={"daily_goal_xp": 70})
    assert r.status_code == 200
    assert r.json()["daily_goal_xp"] == 70
    # значение сохраняется
    assert (await auth_client.get(f"{GAME}/state")).json()["daily_goal_xp"] == 70


@pytest.mark.asyncio
async def test_daily_goal_validation(auth_client, seeded):
    assert (await auth_client.put(f"{GAME}/daily-goal", json={"daily_goal_xp": 0})).status_code == 400
    assert (await auth_client.put(f"{GAME}/daily-goal", json={"daily_goal_xp": 9999})).status_code == 400


# ==================== РАЗБОР ОШИБОК ====================

@pytest.mark.asyncio
async def test_review_empty_initially(auth_client, seeded):
    r = await auth_client.get(f"{GAME}/review")
    assert r.status_code == 200
    assert r.json()["total_pending"] == 0
    assert r.json()["questions"] == []


@pytest.mark.asyncio
async def test_wrong_answers_go_to_review(auth_client, seeded):
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 1, "total": 2, "mistakes": 1,
        "answers": [{"question_id": "q1", "correct": True},
                    {"question_id": "q2", "correct": False}]})

    r = (await auth_client.get(f"{GAME}/review")).json()
    assert r["total_pending"] == 1
    assert r["questions"][0]["question_id"] == "q2"
    assert r["questions"][0]["question"]["id"] == "q2"      # сам вопрос приложен


@pytest.mark.asyncio
async def test_correct_answers_do_not_go_to_review(auth_client, seeded):
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 2, "total": 2,
        "answers": [{"question_id": "q1", "correct": True},
                    {"question_id": "q2", "correct": True}]})
    assert (await auth_client.get(f"{GAME}/review")).json()["total_pending"] == 0


@pytest.mark.asyncio
async def test_state_shows_review_pending(auth_client, seeded):
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 1, "total": 2, "mistakes": 1,
        "answers": [{"question_id": "q2", "correct": False}]})
    assert (await auth_client.get(f"{GAME}/state")).json()["review_pending"] == 1


@pytest.mark.asyncio
async def test_retaking_lesson_correctly_clears_review(auth_client, seeded):
    """Пересдал урок верно — вопрос уходит из очереди повторения."""
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 1, "total": 2, "mistakes": 1,
        "answers": [{"question_id": "q2", "correct": False}]})
    assert (await auth_client.get(f"{GAME}/review")).json()["total_pending"] == 1

    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 2, "total": 2,
        "answers": [{"question_id": "q2", "correct": True}]})
    assert (await auth_client.get(f"{GAME}/review")).json()["total_pending"] == 0


@pytest.mark.asyncio
async def test_review_completion_resolves_and_awards_xp(auth_client, seeded):
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 0, "total": 2, "mistakes": 2,
        "answers": [{"question_id": "q1", "correct": False},
                    {"question_id": "q2", "correct": False}]})

    r = await auth_client.post(f"{GAME}/review/complete", json={
        "client_event_id": _ev(),
        "answers": [{"question_id": "q1", "correct": True},
                    {"question_id": "q2", "correct": True}]})
    assert r.status_code == 200
    body = r.json()
    assert body["resolved"] == 2
    assert body["still_pending"] == 0
    assert body["xp_awarded"] == 2 * ec.XP_PER_REVIEW_CORRECT


@pytest.mark.asyncio
async def test_review_wrong_again_stays_pending(auth_client, seeded):
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 1, "total": 2, "mistakes": 1,
        "answers": [{"question_id": "q2", "correct": False}]})

    r = await auth_client.post(f"{GAME}/review/complete", json={
        "client_event_id": _ev(),
        "answers": [{"question_id": "q2", "correct": False}]})
    assert r.json()["resolved"] == 0
    assert r.json()["still_pending"] == 1        # остался на повторение


@pytest.mark.asyncio
async def test_review_is_idempotent(auth_client, seeded):
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 1, "total": 2, "mistakes": 1,
        "answers": [{"question_id": "q2", "correct": False}]})

    ev = _ev()
    payload = {"client_event_id": ev, "answers": [{"question_id": "q2", "correct": True}]}
    first = await auth_client.post(f"{GAME}/review/complete", json=payload)
    second = await auth_client.post(f"{GAME}/review/complete", json=payload)

    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert second.json()["state"]["xp"] == first.json()["state"]["xp"]


@pytest.mark.asyncio
async def test_review_supports_streak_and_daily_goal(auth_client, seeded):
    """Разбор — полноценное занятие: держит поток и наполняет дневную цель."""
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 1, "total": 2, "mistakes": 1,
        "answers": [{"question_id": "q2", "correct": False}]})
    before = (await auth_client.get(f"{GAME}/state")).json()

    r = await auth_client.post(f"{GAME}/review/complete", json={
        "client_event_id": _ev(), "answers": [{"question_id": "q2", "correct": True}]})
    st = r.json()["state"]
    assert st["streak_count"] >= 1
    assert st["daily_xp"] > before["daily_xp"]


@pytest.mark.asyncio
async def test_old_client_without_answers_still_works(auth_client, seeded):
    """Совместимость: клиент, не присылающий answers, не должен падать."""
    r = await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete",
                               json={"client_event_id": _ev(), "correct": 2, "total": 2})
    assert r.status_code == 200
    assert (await auth_client.get(f"{GAME}/review")).json()["total_pending"] == 0


@pytest.mark.asyncio
async def test_review_requires_auth(client, seeded):
    assert (await client.get(f"{GAME}/review")).status_code == 401


# ==================== УДАЛЕНИЕ АККАУНТА ====================

@pytest.mark.asyncio
async def test_export_returns_own_data(auth_client, seeded):
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete",
                           json={"client_event_id": _ev(), "correct": 2, "total": 2})
    r = await auth_client.get(f"{AUTH}/me/export")
    assert r.status_code == 200
    d = r.json()
    assert "profile" in d and "progress" in d and "events" in d
    assert len(d["progress"]) == 1
    assert d["state"]["xp"] > 0


@pytest.mark.asyncio
async def test_delete_requires_confirm_word(auth_client):
    r = await auth_client.request("DELETE", f"{AUTH}/me",
                                  json={"password": PW, "confirm": "да"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "confirm_required"


@pytest.mark.asyncio
async def test_delete_requires_correct_password(auth_client):
    r = await auth_client.request("DELETE", f"{AUTH}/me",
                                  json={"password": "wrong-password", "confirm": "УДАЛИТЬ"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_requires_auth(client):
    r = await client.request("DELETE", f"{AUTH}/me",
                             json={"password": PW, "confirm": "УДАЛИТЬ"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_account_works(auth_client, seeded):
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete",
                           json={"client_event_id": _ev(), "correct": 2, "total": 2})

    r = await auth_client.request("DELETE", f"{AUTH}/me",
                                  json={"password": PW, "confirm": "УДАЛИТЬ"})
    assert r.status_code == 204

    # токен больше не действует — пользователя нет
    assert (await auth_client.get(f"{AUTH}/me")).status_code == 401


@pytest.mark.asyncio
async def test_deleted_user_cannot_login(client, session_factory):
    email = f"del-{uuid.uuid4().hex[:8]}@example.ru"
    reg = await client.post(f"{AUTH}/register", json={"email": email, "password": PW})
    token = reg.json()["access_token"]

    r = await client.request("DELETE", f"{AUTH}/me",
                             json={"password": PW, "confirm": "УДАЛИТЬ"},
                             headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204

    again = await client.post(f"{AUTH}/login", json={"login": email, "password": PW})
    assert again.status_code == 401


@pytest.mark.asyncio
async def test_delete_removes_all_related_data(auth_client, seeded, session_factory):
    """Ничего не должно остаться: ни прогресса, ни событий, ни попыток, ни сессий."""
    from sqlalchemy import func, select
    from app.game.models import GameEvent, QuestionAttempt, UserProgress
    from app.models import Device, RefreshToken, User, UserState

    me = (await auth_client.get(f"{AUTH}/me")).json()
    uid = uuid.UUID(me["user"]["id"])

    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 1, "total": 2, "mistakes": 1,
        "answers": [{"question_id": "q2", "correct": False}]})

    await auth_client.request("DELETE", f"{AUTH}/me",
                              json={"password": PW, "confirm": "УДАЛИТЬ"})

    async with session_factory() as s:
        for model, col in [(UserProgress, UserProgress.user_id),
                           (GameEvent, GameEvent.user_id),
                           (QuestionAttempt, QuestionAttempt.user_id),
                           (RefreshToken, RefreshToken.user_id),
                           (Device, Device.user_id),
                           (UserState, UserState.user_id)]:
            n = await s.scalar(select(func.count()).select_from(model).where(col == uid))
            assert n == 0, f"осталось {n} строк в {model.__tablename__}"
        assert await s.get(User, uid) is None


@pytest.mark.asyncio
async def test_email_freed_after_deletion(client):
    """После удаления тот же e-mail можно зарегистрировать заново."""
    email = f"reuse-{uuid.uuid4().hex[:8]}@example.ru"
    reg = await client.post(f"{AUTH}/register", json={"email": email, "password": PW})
    token = reg.json()["access_token"]
    await client.request("DELETE", f"{AUTH}/me", json={"password": PW, "confirm": "УДАЛИТЬ"},
                         headers={"Authorization": f"Bearer {token}"})

    again = await client.post(f"{AUTH}/register", json={"email": email, "password": PW})
    assert again.status_code == 201
