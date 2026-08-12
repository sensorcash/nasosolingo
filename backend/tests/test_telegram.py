"""Тесты входа через Telegram Mini App: проверка подписи и эндпоинт."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.config import settings

AUTH = "/api/v1/auth"
TEST_BOT = "123456:TEST-BOT-TOKEN-xyz"


def make_init_data(user, bot_token=TEST_BOT, auth_date=None):
    """Собрать подписанную initData — как её присылает Telegram."""
    auth_date = auth_date or int(time.time())
    fields = {"query_id": "AAHtest", "user": json.dumps(user, separators=(",", ":")),
              "auth_date": str(auth_date)}
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


USER = {"id": 777001, "first_name": "Пётр", "username": "petr_m"}


# ---------- проверка подписи (чистая логика) ----------

def test_validate_accepts_genuine(monkeypatch):
    from app.auth.telegram import validate_init_data
    monkeypatch.setattr(settings, "telegram_bot_token", TEST_BOT)
    res = validate_init_data(make_init_data(USER))
    assert res["telegram_id"] == 777001 and res["first_name"] == "Пётр"


def test_validate_rejects_tampered(monkeypatch):
    from app.auth.telegram import validate_init_data
    from app.errors import AppError
    monkeypatch.setattr(settings, "telegram_bot_token", TEST_BOT)
    bad = make_init_data(USER).replace("777001", "999999")
    with pytest.raises(AppError):
        validate_init_data(bad)


def test_validate_rejects_wrong_bot(monkeypatch):
    from app.auth.telegram import validate_init_data
    from app.errors import AppError
    monkeypatch.setattr(settings, "telegram_bot_token", "999:OTHER")
    with pytest.raises(AppError):
        validate_init_data(make_init_data(USER, bot_token=TEST_BOT))


def test_validate_rejects_expired(monkeypatch):
    from app.auth.telegram import validate_init_data
    from app.errors import AppError
    monkeypatch.setattr(settings, "telegram_bot_token", TEST_BOT)
    old = make_init_data(USER, auth_date=int(time.time()) - 200000)
    with pytest.raises(AppError):
        validate_init_data(old, max_age_seconds=86400)


def test_validate_disabled_without_token(monkeypatch):
    from app.auth.telegram import validate_init_data
    from app.errors import AppError
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    with pytest.raises(AppError):
        validate_init_data(make_init_data(USER))


# ---------- эндпоинт ----------

@pytest.mark.asyncio
async def test_telegram_login_creates_user_and_tokens(client, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", TEST_BOT)
    r = await client.post(f"{AUTH}/telegram", json={"init_data": make_init_data(USER)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] and body["refresh_token"]


@pytest.mark.asyncio
async def test_telegram_login_is_idempotent_same_user(client, monkeypatch):
    """Повторный вход того же Telegram-юзера не плодит новых аккаунтов."""
    monkeypatch.setattr(settings, "telegram_bot_token", TEST_BOT)
    u = {"id": 777002, "first_name": "Анна"}
    r1 = await client.post(f"{AUTH}/telegram", json={"init_data": make_init_data(u)})
    r2 = await client.post(f"{AUTH}/telegram", json={"init_data": make_init_data(u)})
    assert r1.status_code == 200 and r2.status_code == 200
    # оба токена валидны и ведут к одному профилю
    me1 = await client.get("/api/v1/auth/me",
                           headers={"Authorization": "Bearer " + r1.json()["access_token"]})
    me2 = await client.get("/api/v1/auth/me",
                           headers={"Authorization": "Bearer " + r2.json()["access_token"]})
    assert me1.status_code == 200 and me1.json() == me2.json()


@pytest.mark.asyncio
async def test_telegram_login_rejects_tampered(client, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", TEST_BOT)
    bad = make_init_data(USER).replace("777001", "888888")
    r = await client.post(f"{AUTH}/telegram", json={"init_data": bad})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_telegram_disabled_returns_503(client, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    r = await client.post(f"{AUTH}/telegram", json={"init_data": make_init_data(USER)})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_web_registration_still_works(client, monkeypatch):
    """Веб-вход не сломан: обычная регистрация по-прежнему работает."""
    import uuid
    monkeypatch.setattr(settings, "telegram_bot_token", TEST_BOT)
    email = f"web-{uuid.uuid4().hex[:8]}@example.ru"
    r = await client.post(f"{AUTH}/register", json={"email": email, "password": "parol12345678"})
    assert r.status_code == 201 and r.json()["access_token"]
