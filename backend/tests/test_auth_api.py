"""Сквозные тесты авторизации — настоящие HTTP-запросы к приложению."""
import uuid

import pytest

AUTH = "/api/v1/auth"
PW = "nasos-parol-1"


def _email() -> str:
    return f"u-{uuid.uuid4().hex[:8]}@example.ru"


@pytest.mark.asyncio
async def test_register_returns_tokens(client):
    resp = await client.post(f"{AUTH}/register", json={"email": _email(), "password": PW})
    assert resp.status_code == 201
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["email_verified"] is False


@pytest.mark.asyncio
async def test_duplicate_email_rejected(client):
    email = _email()
    await client.post(f"{AUTH}/register", json={"email": email, "password": PW})
    resp = await client.post(f"{AUTH}/register", json={"email": email, "password": PW})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "email_taken"


@pytest.mark.asyncio
async def test_short_password_rejected(client):
    resp = await client.post(f"{AUTH}/register", json={"email": _email(), "password": "123"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "weak_password"


@pytest.mark.asyncio
async def test_email_is_case_insensitive(client):
    email = _email()
    await client.post(f"{AUTH}/register", json={"email": email, "password": PW})
    resp = await client.post(f"{AUTH}/login", json={"email": email.upper(), "password": PW})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    email = _email()
    await client.post(f"{AUTH}/register", json={"email": email, "password": PW})
    resp = await client.post(f"{AUTH}/login", json={"email": email, "password": "wrong-password"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_unknown_email_same_error(client):
    """Ответ не должен выдавать, существует ли адрес."""
    resp = await client.post(f"{AUTH}/login", json={"email": _email(), "password": PW})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_lockout_after_repeated_failures(client):
    email = _email()
    await client.post(f"{AUTH}/register", json={"email": email, "password": PW})
    codes = []
    for _ in range(7):
        r = await client.post(f"{AUTH}/login", json={"email": email, "password": "nope-nope-nope"})
        codes.append(r.status_code)
    assert 423 in codes                      # сработала защита от подбора


@pytest.mark.asyncio
async def test_me_requires_token(client):
    assert (await client.get(f"{AUTH}/me")).status_code == 401


@pytest.mark.asyncio
async def test_me_returns_state(client):
    email = _email()
    reg = await client.post(f"{AUTH}/register", json={"email": email, "password": PW})
    token = reg.json()["access_token"]
    resp = await client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["state"]["lives"] == 5


@pytest.mark.asyncio
async def test_garbage_token_rejected(client):
    resp = await client.get(f"{AUTH}/me", headers={"Authorization": "Bearer not-a-token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_token(client):
    reg = await client.post(f"{AUTH}/register", json={"email": _email(), "password": PW})
    old_refresh = reg.json()["refresh_token"]

    resp = await client.post(f"{AUTH}/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200
    assert resp.json()["refresh_token"] != old_refresh    # выдан новый


@pytest.mark.asyncio
async def test_reused_refresh_triggers_family_revoke(client):
    """Повтор старого refresh = признак угона → гасим всю цепочку сессий."""
    reg = await client.post(f"{AUTH}/register", json={"email": _email(), "password": PW})
    first = reg.json()["refresh_token"]

    rotated = await client.post(f"{AUTH}/refresh", json={"refresh_token": first})
    new_refresh = rotated.json()["refresh_token"]

    # злоумышленник пробует старый токен
    reuse = await client.post(f"{AUTH}/refresh", json={"refresh_token": first})
    assert reuse.status_code == 401

    # честный токен тоже больше не работает — цепочка отозвана
    after = await client.post(f"{AUTH}/refresh", json={"refresh_token": new_refresh})
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh(client):
    reg = await client.post(f"{AUTH}/register", json={"email": _email(), "password": PW})
    refresh = reg.json()["refresh_token"]

    assert (await client.post(f"{AUTH}/logout", json={"refresh_token": refresh})).status_code == 204
    assert (await client.post(f"{AUTH}/refresh", json={"refresh_token": refresh})).status_code == 401


@pytest.mark.asyncio
async def test_reset_request_never_reveals_existence(client):
    known = _email()
    await client.post(f"{AUTH}/register", json={"email": known, "password": PW})

    a = await client.post(f"{AUTH}/password/reset-request", json={"email": known})
    b = await client.post(f"{AUTH}/password/reset-request", json={"email": _email()})
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()              # ответы неотличимы


@pytest.mark.asyncio
async def test_full_password_reset_flow(client, fake_redis, monkeypatch):
    email = _email()
    await client.post(f"{AUTH}/register", json={"email": email, "password": PW})

    # перехватываем токен, который ушёл бы письмом
    captured = {}
    import app.auth.service as auth_service
    monkeypatch.setattr(auth_service, "send_password_reset",
                        lambda to, token: captured.update(token=token))

    await client.post(f"{AUTH}/password/reset-request", json={"email": email})
    assert "token" in captured

    new_pw = "novyj-parol-2026"
    resp = await client.post(f"{AUTH}/password/reset-confirm",
                             json={"token": captured["token"], "new_password": new_pw})
    assert resp.status_code == 200

    # старый пароль больше не работает, новый — работает
    assert (await client.post(f"{AUTH}/login",
                              json={"email": email, "password": PW})).status_code == 401
    assert (await client.post(f"{AUTH}/login",
                              json={"email": email, "password": new_pw})).status_code == 200


@pytest.mark.asyncio
async def test_reset_token_is_single_use(client, monkeypatch):
    email = _email()
    await client.post(f"{AUTH}/register", json={"email": email, "password": PW})

    captured = {}
    import app.auth.service as auth_service
    monkeypatch.setattr(auth_service, "send_password_reset",
                        lambda to, token: captured.update(token=token))
    await client.post(f"{AUTH}/password/reset-request", json={"email": email})

    body = {"token": captured["token"], "new_password": "novyj-parol-2026"}
    assert (await client.post(f"{AUTH}/password/reset-confirm", json=body)).status_code == 200
    second = await client.post(f"{AUTH}/password/reset-confirm", json=body)
    assert second.status_code == 410         # повторно использовать нельзя


@pytest.mark.asyncio
async def test_invalid_reset_token(client):
    resp = await client.post(f"{AUTH}/password/reset-confirm",
                             json={"token": "podelka", "new_password": "novyj-parol-2026"})
    assert resp.status_code == 410
