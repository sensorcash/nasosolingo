"""Фикстуры для интеграционных тестов.

Приложение поднимается целиком, но вместо PostgreSQL — SQLite в памяти,
а вместо Redis — fakeredis. Логика приложения при этом настоящая.
"""
import uuid

import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, get_session
from app.main import app
from app import models  # noqa: F401  регистрирует таблицы
from app.game import models as game_models  # noqa: F401


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def fake_redis(monkeypatch):
    """Подменяем Redis во всех модулях, где он уже импортирован по имени."""
    r = fake_aioredis.FakeRedis(decode_responses=True)
    import app.redis_client
    import app.security.ratelimit
    import app.auth.service

    monkeypatch.setattr(app.redis_client, "redis", r)
    monkeypatch.setattr(app.security.ratelimit, "redis", r)
    monkeypatch.setattr(app.auth.service, "redis", r)
    yield r
    await r.flushall()


@pytest_asyncio.fixture
async def client(session_factory):
    async def _get_session():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(client):
    """Зарегистрированный пользователь + клиент с проставленным токеном."""
    email = f"master-{uuid.uuid4().hex[:8]}@example.ru"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "nasos-parol-1"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    client.email = email
    return client


@pytest_asyncio.fixture
async def seeded(session_factory):
    """Курс + юнит + два урока (2 и 5 вопросов)."""
    from app.game.models import Course, Lesson, Unit

    async with session_factory() as s:
        course = Course(slug="water-supply", title="Водоснабжение", order=1)
        s.add(course)
        await s.flush()

        unit = Unit(course_id=course.id, slug="install", title="Монтаж", order=1)
        s.add(unit)
        await s.flush()

        l1 = Lesson(
            unit_id=unit.id, slug="l1", title="Урок 1", order=1, question_count=2,
            content={"questions": [{"id": "q1", "type": "mc"}, {"id": "q2", "type": "mc"}]},
        )
        l2 = Lesson(
            unit_id=unit.id, slug="l2", title="Урок 2", order=2, question_count=5,
            content={"questions": [{"id": f"q{i}", "type": "mc"} for i in range(5)]},
        )
        s.add_all([l1, l2])
        await s.commit()
        return {"course": course.id, "unit": unit.id, "l1": l1.id, "l2": l2.id}
