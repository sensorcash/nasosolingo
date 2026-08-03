"""Сквозные тесты игрового API: реальные HTTP-запросы к приложению."""
import uuid

import pytest

GAME = "/api/v1/game"


# ---------- доступ ----------

@pytest.mark.asyncio
async def test_game_requires_auth(client, seeded):
    """Без токена игровые данные недоступны."""
    for path in [f"{GAME}/state", f"{GAME}/courses"]:
        resp = await client.get(path)
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_initial_state(auth_client, seeded):
    resp = await auth_client.get(f"{GAME}/state")
    assert resp.status_code == 200
    s = resp.json()
    assert s["xp"] == 0
    assert s["level"] == 1
    assert s["lives"] == 5
    assert s["streak_count"] == 0
    assert s["seconds_to_next_life"] is None      # жизни полные


# ---------- дерево курсов и разблокировка ----------

@pytest.mark.asyncio
async def test_course_tree_unlocking(auth_client, seeded):
    resp = await auth_client.get(f"{GAME}/courses")
    assert resp.status_code == 200
    lessons = resp.json()["courses"][0]["units"][0]["lessons"]
    assert lessons[0]["status"] == "available"    # первый открыт
    assert lessons[1]["status"] == "locked"       # второй закрыт


@pytest.mark.asyncio
async def test_lesson_unlocks_after_previous(auth_client, seeded):
    await auth_client.post(
        f"{GAME}/lessons/{seeded['l1']}/complete",
        json={"client_event_id": uuid.uuid4().hex, "correct": 2, "total": 2},
    )
    resp = await auth_client.get(f"{GAME}/courses")
    lessons = resp.json()["courses"][0]["units"][0]["lessons"]
    assert lessons[0]["status"] == "done"
    assert lessons[1]["status"] == "available"    # разблокировался


@pytest.mark.asyncio
async def test_get_lesson_content(auth_client, seeded):
    resp = await auth_client.get(f"{GAME}/lessons/{seeded['l2']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["question_count"] == 5
    assert len(body["content"]["questions"]) == 5


@pytest.mark.asyncio
async def test_missing_lesson_404(auth_client, seeded):
    resp = await auth_client.get(f"{GAME}/lessons/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "lesson_not_found"


# ---------- завершение урока ----------

@pytest.mark.asyncio
async def test_complete_awards_xp_and_streak(auth_client, seeded):
    resp = await auth_client.post(
        f"{GAME}/lessons/{seeded['l1']}/complete",
        json={"client_event_id": uuid.uuid4().hex, "correct": 2, "total": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["duplicate"] is False
    assert body["xp_awarded"] == 15 + 2 * 4 + 10          # база + ответы + идеал
    assert body["state"]["xp"] == body["xp_awarded"]
    assert body["state"]["streak_count"] == 1             # поток стартовал


@pytest.mark.asyncio
async def test_mistakes_cost_lives(auth_client, seeded):
    resp = await auth_client.post(
        f"{GAME}/lessons/{seeded['l1']}/complete",
        json={"client_event_id": uuid.uuid4().hex, "correct": 1, "total": 2, "mistakes": 2},
    )
    s = resp.json()["state"]
    assert s["lives"] == 3
    assert s["seconds_to_next_life"] is not None          # таймер пошёл


@pytest.mark.asyncio
async def test_repeat_gives_less_xp(auth_client, seeded):
    first = await auth_client.post(
        f"{GAME}/lessons/{seeded['l1']}/complete",
        json={"client_event_id": uuid.uuid4().hex, "correct": 2, "total": 2},
    )
    second = await auth_client.post(
        f"{GAME}/lessons/{seeded['l1']}/complete",
        json={"client_event_id": uuid.uuid4().hex, "correct": 2, "total": 2},
    )
    assert second.json()["xp_awarded"] < first.json()["xp_awarded"]


@pytest.mark.asyncio
async def test_streak_not_double_counted_same_day(auth_client, seeded):
    for _ in range(3):
        resp = await auth_client.post(
            f"{GAME}/lessons/{seeded['l1']}/complete",
            json={"client_event_id": uuid.uuid4().hex, "correct": 2, "total": 2},
        )
    assert resp.json()["state"]["streak_count"] == 1      # один день = один поток


# ---------- идемпотентность (сердце офлайн-режима) ----------

@pytest.mark.asyncio
async def test_same_event_id_does_not_double_xp(auth_client, seeded):
    event_id = uuid.uuid4().hex
    payload = {"client_event_id": event_id, "correct": 2, "total": 2}

    first = await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json=payload)
    second = await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json=payload)

    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    # опыт начислен ровно один раз
    assert second.json()["state"]["xp"] == first.json()["state"]["xp"]


# ---------- защита от мусорных данных ----------

@pytest.mark.asyncio
async def test_correct_cannot_exceed_total(auth_client, seeded):
    resp = await auth_client.post(
        f"{GAME}/lessons/{seeded['l1']}/complete",
        json={"client_event_id": uuid.uuid4().hex, "correct": 99, "total": 2},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_result"


@pytest.mark.asyncio
async def test_total_must_match_lesson(auth_client, seeded):
    """Урок из 2 вопросов, а клиент прислал 5 — отклоняем."""
    resp = await auth_client.post(
        f"{GAME}/lessons/{seeded['l1']}/complete",
        json={"client_event_id": uuid.uuid4().hex, "correct": 5, "total": 5},
    )
    assert resp.status_code == 400


# ---------- офлайн-синхронизация ----------

@pytest.mark.asyncio
async def test_sync_batch(auth_client, seeded):
    events = [
        {"client_event_id": uuid.uuid4().hex, "lesson_id": str(seeded["l1"]),
         "correct": 2, "total": 2},
        {"client_event_id": uuid.uuid4().hex, "lesson_id": str(seeded["l2"]),
         "correct": 4, "total": 5},
    ]
    resp = await auth_client.post(f"{GAME}/sync", json={"events": events})
    assert resp.status_code == 200
    body = resp.json()
    assert all(r["accepted"] for r in body["results"])
    assert body["state"]["xp"] > 0


@pytest.mark.asyncio
async def test_sync_is_idempotent(auth_client, seeded):
    """Очередь отправилась дважды (связь моргнула) — опыт не удваивается."""
    events = [{"client_event_id": uuid.uuid4().hex, "lesson_id": str(seeded["l1"]),
               "correct": 2, "total": 2}]

    first = await auth_client.post(f"{GAME}/sync", json={"events": events})
    second = await auth_client.post(f"{GAME}/sync", json={"events": events})

    assert second.json()["results"][0]["duplicate"] is True
    assert second.json()["state"]["xp"] == first.json()["state"]["xp"]


@pytest.mark.asyncio
async def test_sync_bad_event_does_not_break_others(auth_client, seeded):
    """Одно битое событие не должно отменять остальные."""
    events = [
        {"client_event_id": uuid.uuid4().hex, "lesson_id": str(seeded["l1"]),
         "correct": 2, "total": 2},                                  # хорошее
        {"client_event_id": uuid.uuid4().hex, "lesson_id": str(uuid.uuid4()),
         "correct": 1, "total": 2},                                  # урока не существует
    ]
    resp = await auth_client.post(f"{GAME}/sync", json={"events": events})
    results = resp.json()["results"]
    assert results[0]["accepted"] is True
    assert results[1]["accepted"] is False
    assert results[1]["error"] == "lesson_not_found"
    assert resp.json()["state"]["xp"] > 0        # хорошее событие всё равно учтено


# ---------- изоляция пользователей ----------

@pytest.mark.asyncio
async def test_progress_is_per_user(client, seeded):
    async def make_user():
        email = f"u-{uuid.uuid4().hex[:8]}@example.ru"
        r = await client.post("/api/v1/auth/register",
                              json={"email": email, "password": "nasos-parol-1"})
        return r.json()["access_token"]

    token_a = await make_user()
    token_b = await make_user()

    await client.post(
        f"{GAME}/lessons/{seeded['l1']}/complete",
        json={"client_event_id": uuid.uuid4().hex, "correct": 2, "total": 2},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    state_b = await client.get(f"{GAME}/state", headers={"Authorization": f"Bearer {token_b}"})
    assert state_b.json()["xp"] == 0             # прогресс А не протёк к Б
