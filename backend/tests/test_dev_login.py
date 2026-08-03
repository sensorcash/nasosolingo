"""Тесты входа по короткому логину (username) и dev-аккаунта."""
import uuid

import pytest

from app.models import User, UserState
from app.security.passwords import hash_password

AUTH = "/api/v1/auth"


async def _make_admin(session_factory, password="12345"):
    """Создаём dev-аккаунт напрямую, как это делает seed_dev.py."""
    async with session_factory() as s:
        user = User(
            id=uuid.uuid4(), username="admin", email="admin@local.dev",
            password_hash=hash_password(password), email_verified=True,
            timezone="Europe/Moscow",
        )
        s.add(user)
        await s.flush()
        s.add(UserState(user_id=user.id, xp=0, level=1, lives=5, streak_count=0))
        await s.commit()
        return user.id


@pytest.mark.asyncio
async def test_login_by_username(client, session_factory):
    await _make_admin(session_factory)
    resp = await client.post(f"{AUTH}/login", json={"login": "admin", "password": "12345"})
    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "admin"


@pytest.mark.asyncio
async def test_login_by_email_still_works(client, session_factory):
    """Тот же аккаунт пускает и по e-mail."""
    await _make_admin(session_factory)
    resp = await client.post(f"{AUTH}/login",
                             json={"login": "admin@local.dev", "password": "12345"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_old_email_field_still_accepted(client):
    """Старые запросы с полем "email" должны продолжать работать."""
    email = f"u-{uuid.uuid4().hex[:8]}@example.ru"
    await client.post(f"{AUTH}/register", json={"email": email, "password": "nasos-parol-1"})
    resp = await client.post(f"{AUTH}/login",
                             json={"email": email, "password": "nasos-parol-1"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_username_login_is_case_insensitive(client, session_factory):
    await _make_admin(session_factory)
    resp = await client.post(f"{AUTH}/login", json={"login": "ADMIN", "password": "12345"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_wrong_password_for_admin(client, session_factory):
    await _make_admin(session_factory)
    resp = await client.post(f"{AUTH}/login", json={"login": "admin", "password": "54321"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_can_play(client, session_factory, seeded):
    """Dev-аккаунт полноценный: с ним работают игровые эндпоинты."""
    await _make_admin(session_factory)
    login = await client.post(f"{AUTH}/login", json={"login": "admin", "password": "12345"})
    token = login.json()["access_token"]

    resp = await client.get("/api/v1/game/courses", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert len(resp.json()["courses"]) == 1


@pytest.mark.asyncio
async def test_weak_password_still_rejected_on_register(client):
    """Слабый пароль разрешён ТОЛЬКО dev-аккаунту, обычная регистрация его не пропустит."""
    resp = await client.post(f"{AUTH}/register",
                             json={"email": f"u-{uuid.uuid4().hex[:8]}@example.ru",
                                   "password": "12345"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "weak_password"


def test_seed_dev_refuses_outside_dev(monkeypatch):
    """Главная защита: скрипт не должен работать нигде, кроме APP_ENV=dev."""
    import seed_dev
    from app.config import settings

    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(SystemExit) as exc:
        seed_dev.guard()
    assert exc.value.code == 1


def test_seed_dev_allows_dev(monkeypatch):
    import seed_dev
    from app.config import settings

    monkeypatch.setattr(settings, "app_env", "dev")
    seed_dev.guard()          # не должно ничего бросить
