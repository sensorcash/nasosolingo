"""Проверка подлинности входа из Telegram Mini App.

Telegram присылает строку initData с данными пользователя и подписью (hash).
Сервер ОБЯЗАН проверить подпись ботовым токеном — иначе вход можно подделать.
Алгоритм — из официальной документации Telegram (Web App data validation).
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from app.config import settings
from app.errors import AppError


def validate_init_data(init_data: str, bot_token: str | None = None,
                       max_age_seconds: int | None = None) -> dict:
    """Проверить initData. Вернуть данные пользователя или бросить AppError."""
    bot_token = bot_token if bot_token is not None else settings.telegram_bot_token
    max_age = max_age_seconds if max_age_seconds is not None else settings.telegram_auth_max_age

    if not bot_token:
        raise AppError(503, "telegram_disabled", "Вход через Telegram не настроен")
    if not init_data:
        raise AppError(401, "telegram_auth_failed", "Пустые данные Telegram")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise AppError(401, "telegram_auth_failed", "Нет подписи")

    # data-check-string: пары key=value, отсортированы по ключу, склеены через \n
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))

    # секрет = HMAC-SHA256(ключ="WebAppData", сообщение=токен бота)
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        raise AppError(401, "telegram_auth_failed", "Подпись не совпала")

    auth_date = int(pairs.get("auth_date", "0") or "0")
    if max_age and (time.time() - auth_date) > max_age:
        raise AppError(401, "telegram_auth_failed", "Данные устарели, откройте заново")

    user = json.loads(pairs["user"]) if pairs.get("user") else None
    if not user or "id" not in user:
        raise AppError(401, "telegram_auth_failed", "Нет данных пользователя")

    return {
        "telegram_id": int(user["id"]),
        "first_name": (user.get("first_name") or "").strip(),
        "username": (user.get("username") or "").strip(),
        "auth_date": auth_date,
    }
