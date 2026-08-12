"""Telegram-бот: встречает пользователя кнопкой запуска и шлёт напоминания.

Устроен на long-polling (getUpdates) — нужен только токен бота, без настройки
вебхука и публичного адреса для приёма команд. Рассылка напоминаний — отдельная
фоновая задача. Обе запускаются в main.py при старте, если задан токен.

Сервер работает в один процесс, поэтому задачи не задваиваются. Если добавишь
воркеры (--workers N) — бота стоит выносить в отдельный процесс.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import select

from app.config import settings
from app.redis_client import redis

log = logging.getLogger("bot")

_OFFSET_KEY = "tg:updates_offset"          # последний обработанный update_id (в Redis)
_REMINDED_KEY = "tg:reminded"              # set кому уже напомнили сегодня


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


def _app_url() -> str | None:
    """HTTPS-адрес приложения для кнопки запуска (web_app требует https)."""
    url = (settings.public_base_url or "").rstrip("/")
    if not url.startswith("https://"):
        return None
    return url + "/app"


def _launch_markup():
    """Инлайн-кнопка, открывающая мини-приложение (с автологином)."""
    url = _app_url()
    if not url:
        return None
    return {"inline_keyboard": [[{"text": "▶️ Играть", "web_app": {"url": url}}]]}


async def tg_call(method: str, http_timeout: float = 30, **params) -> dict | None:
    """Вызвать метод Telegram Bot API. Вернуть result или None при ошибке."""
    try:
        async with httpx.AsyncClient(timeout=http_timeout) as client:
            r = await client.post(_api(method), json=params)
        data = r.json()
        if not data.get("ok"):
            log.warning("Telegram API %s: %s", method, data.get("description"))
            return None
        return data.get("result")
    except Exception as e:                 # сеть/таймаут — не роняем приложение
        log.warning("Telegram API %s не удался: %s", method, e)
        return None


async def send_message(chat_id: int, text: str, with_button: bool = True) -> bool:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if with_button and _launch_markup():
        payload["reply_markup"] = _launch_markup()
    return await tg_call("sendMessage", **payload) is not None


WELCOME = (
    "Привет! Это <b>Насосолинго</b> — тренажёр для монтажников.\n\n"
    "Короткие уроки про подбор и установку насосов: напор, обвязка, автоматика, "
    "диагностика. Жми кнопку ниже и поехали 👇"
)
NO_URL_HINT = (
    "Бот запущен, но не задан публичный адрес приложения, поэтому кнопка запуска "
    "недоступна. Открой мини-приложение через кнопку меню бота."
)


async def handle_update(update: dict) -> None:
    """Обработать одно обновление от Telegram. Пока реагируем на /start."""
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    if chat_id is None:
        return
    if text.startswith("/start"):
        if _launch_markup():
            await send_message(chat_id, WELCOME, with_button=True)
        else:
            await send_message(chat_id, NO_URL_HINT, with_button=False)


async def _set_menu_button() -> None:
    """Сделать кнопку меню бота запускающей приложение (если есть https-адрес)."""
    url = _app_url()
    if not url:
        return
    await tg_call("setChatMenuButton",
                  menu_button={"type": "web_app", "text": "Играть",
                               "web_app": {"url": url}})


# ---------------- приём команд (long-polling) ----------------

async def run_polling(stop: asyncio.Event) -> None:
    """Фоновая задача: получать обновления и обрабатывать их."""
    if not settings.telegram_bot_token:
        return
    await _set_menu_button()
    log.info("Telegram-бот: polling запущен")
    try:
        offset = int(await redis.get(_OFFSET_KEY) or 0)
    except Exception:
        offset = 0

    while not stop.is_set():
        try:
            updates = await tg_call("getUpdates", http_timeout=35,
                                    offset=offset + 1, timeout=25,
                                    allowed_updates=["message"])
            if updates:
                for upd in updates:
                    offset = max(offset, upd.get("update_id", offset))
                    try:
                        await handle_update(upd)
                    except Exception as e:
                        log.warning("ошибка обработки обновления: %s", e)
                try:
                    await redis.set(_OFFSET_KEY, offset)
                except Exception:
                    pass
            else:
                # пустой ответ/ошибка — короткая пауза, чтобы не молотить
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning("polling: %s", e)
            await asyncio.sleep(5)
    log.info("Telegram-бот: polling остановлен")


# ---------------- напоминания ----------------

async def _users_to_remind(session, today: date) -> list[tuple[int, int]]:
    """Кому напомнить: есть поток, но сегодня ещё не занимались (поток под угрозой).

    Возвращает список (telegram_id, streak_count). Тех, кто уже занимался сегодня,
    и тех, у кого нет потока, не трогаем — чтобы не спамить.
    """
    from app.models import User, UserState
    yesterday = today - timedelta(days=1)
    rows = await session.execute(
        select(User.telegram_id, UserState.streak_count)
        .join(UserState, UserState.user_id == User.id)
        .where(User.telegram_id.is_not(None))
        .where(UserState.streak_count >= 1)
        .where(UserState.streak_last_active == yesterday))
    return [(int(tg), int(sc)) for tg, sc in rows.all() if tg is not None]


def _reminder_text(streak: int) -> str:
    return (f"🔥 Твой поток — {streak} дн. Не теряй его! "
            f"Пара минут урока сегодня, и серия продолжается 👇")


async def _send_daily_reminders() -> int:
    """Разослать напоминания подходящим пользователям. Вернуть число отправленных."""
    from app.db import SessionLocal
    today = datetime.now().date()
    sent = 0
    async with SessionLocal() as session:
        targets = await _users_to_remind(session, today)
    for tg_id, streak in targets:
        # не напоминаем дважды в один день
        try:
            already = await redis.sismember(_REMINDED_KEY, str(tg_id))
        except Exception:
            already = False
        if already:
            continue
        if await send_message(tg_id, _reminder_text(streak), with_button=True):
            sent += 1
            try:
                await redis.sadd(_REMINDED_KEY, str(tg_id))
                await redis.expire(_REMINDED_KEY, 60 * 60 * 26)   # сбросится к следующему дню
            except Exception:
                pass
    if sent:
        log.info("Telegram-бот: отправлено напоминаний — %d", sent)
    return sent


async def run_reminders(stop: asyncio.Event) -> None:
    """Фоновая задача: раз в день в заданный час рассылать напоминания."""
    if not settings.telegram_bot_token:
        return
    log.info("Telegram-бот: планировщик напоминаний запущен (час=%d)",
             settings.telegram_reminder_hour)
    while not stop.is_set():
        now = datetime.now()
        if now.hour == settings.telegram_reminder_hour:
            # раз в сутки: помечаем день, чтобы не слать повторно при перезапусках
            stamp = now.date().isoformat()
            try:
                fresh = await redis.set("tg:reminder_day", stamp, nx=True, ex=60 * 60 * 20)
            except Exception:
                fresh = True
            if fresh:
                try:
                    await _send_daily_reminders()
                except Exception as e:
                    log.warning("рассылка напоминаний: %s", e)
        # проверяем раз в 15 минут
        try:
            await asyncio.wait_for(stop.wait(), timeout=15 * 60)
        except asyncio.TimeoutError:
            pass
    log.info("Telegram-бот: планировщик напоминаний остановлен")
