"""Тесты Telegram-бота: кнопка запуска, обработка /start, выбор для напоминаний."""
from datetime import date, timedelta

import pytest

from app import bot
from app.config import settings


# ---------- кнопка запуска ----------

def test_launch_button_with_https(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://x.cloudpub.ru")
    mk = bot._launch_markup()
    btn = mk["inline_keyboard"][0][0]
    assert btn["web_app"]["url"] == "https://x.cloudpub.ru/app"


def test_no_launch_button_without_https(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8000")
    assert bot._launch_markup() is None


# ---------- обработка /start ----------

@pytest.mark.asyncio
async def test_start_sends_welcome_with_button(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://x.cloudpub.ru")
    sent = {}

    async def fake_call(method, **params):
        sent["method"] = method
        sent["params"] = params
        return {"ok": True}

    monkeypatch.setattr(bot, "tg_call", fake_call)
    await bot.handle_update({"message": {"chat": {"id": 42}, "text": "/start"}})
    assert sent["method"] == "sendMessage"
    assert sent["params"]["chat_id"] == 42
    assert "reply_markup" in sent["params"]                # кнопка запуска приложена
    assert "Насосолинго" in sent["params"]["text"]


@pytest.mark.asyncio
async def test_non_start_is_ignored(monkeypatch):
    calls = []

    async def fake_call(method, **params):
        calls.append(method); return {"ok": True}

    monkeypatch.setattr(bot, "tg_call", fake_call)
    await bot.handle_update({"message": {"chat": {"id": 42}, "text": "привет"}})
    assert calls == []                                    # на обычный текст не реагируем


@pytest.mark.asyncio
async def test_update_without_chat_is_safe(monkeypatch):
    calls = []

    async def fake_call(method, **params):
        calls.append(method); return {"ok": True}

    monkeypatch.setattr(bot, "tg_call", fake_call)
    await bot.handle_update({"edited_message": {}})       # чужой тип обновления
    assert calls == []


# ---------- выбор кого напоминать ----------

@pytest.mark.asyncio
async def test_reminder_targets_streak_at_risk(session_factory):
    """Напоминаем тем, у кого есть поток, но вчера — последняя активность."""
    import uuid
    from app.models import User, UserState
    today = date(2026, 8, 11)
    yesterday = today - timedelta(days=1)

    async with session_factory() as s:
        # 1) поток под угрозой (вчера занимался) + telegram → ДОЛЖЕН попасть
        u1 = User(email=f"a{uuid.uuid4().hex[:6]}@telegram.bot", password_hash="x",
                  telegram_id=1001, nickname="A")
        # 2) занимался сегодня → НЕ напоминаем
        u2 = User(email=f"b{uuid.uuid4().hex[:6]}@telegram.bot", password_hash="x",
                  telegram_id=1002, nickname="B")
        # 3) нет потока → НЕ напоминаем
        u3 = User(email=f"c{uuid.uuid4().hex[:6]}@telegram.bot", password_hash="x",
                  telegram_id=1003, nickname="C")
        # 4) веб-пользователь без telegram → НЕ напоминаем
        u4 = User(email=f"d{uuid.uuid4().hex[:6]}@example.ru", password_hash="x",
                  telegram_id=None, nickname="D")
        s.add_all([u1, u2, u3, u4]); await s.flush()
        s.add_all([
            UserState(user_id=u1.id, streak_count=5, streak_last_active=yesterday),
            UserState(user_id=u2.id, streak_count=3, streak_last_active=today),
            UserState(user_id=u3.id, streak_count=0, streak_last_active=yesterday),
            UserState(user_id=u4.id, streak_count=7, streak_last_active=yesterday),
        ])
        await s.commit()

    async with session_factory() as s:
        targets = await bot._users_to_remind(s, today)

    ids = {tg for tg, _ in targets}
    assert 1001 in ids                      # поток под угрозой + telegram
    assert 1002 not in ids                  # уже занимался сегодня
    assert 1003 not in ids                  # нет потока
    assert 1004 not in ids                  # нет telegram
    # и текст содержит длину потока
    assert "5" in bot._reminder_text(5)
