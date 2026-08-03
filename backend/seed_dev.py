"""Создание аккаунта для разработки: admin / 12345.

Запуск:  .venv\\Scripts\\python seed_dev.py     (Windows)
         .venv/bin/python seed_dev.py          (Mac/Linux)

ВАЖНО: скрипт намеренно отказывается работать, если APP_ENV не равен "dev".
Пароль "12345" короче минимальной политики (10 символов) и создаётся в обход
проверок — такому аккаунту нельзя оказаться на боевом сервере, где лежат
персональные данные пользователей.

Скрипт идемпотентный: повторный запуск просто сбросит пароль обратно на 12345.
"""
import asyncio
import sys
import uuid

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import User, UserState
from app.security.passwords import hash_password

DEV_USERNAME = "admin"
DEV_PASSWORD = "12345"
DEV_EMAIL = "admin@local.dev"


def guard() -> None:
    """Не даём создать слабый аккаунт где-либо, кроме локальной разработки."""
    if settings.app_env != "dev":
        print(
            f"ОТКАЗ: APP_ENV={settings.app_env!r}, а не 'dev'.\n"
            "Аккаунт admin/12345 создаётся только для локальной разработки.\n"
            "Для боевого сервера заведите обычного пользователя через /auth/register."
        )
        sys.exit(1)


async def main() -> None:
    guard()

    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == DEV_USERNAME))

        if user is None:
            user = User(
                id=uuid.uuid4(),
                username=DEV_USERNAME,
                email=DEV_EMAIL,
                # Пароль хешируется напрямую, минуя validate_password_policy:
                # для боевых аккаунтов политика остаётся в силе.
                password_hash=hash_password(DEV_PASSWORD),
                email_verified=True,
                nickname="Админ",
                timezone="Europe/Moscow",
            )
            session.add(user)
            await session.flush()
            session.add(UserState(
                user_id=user.id, xp=0, level=1, lives=5, streak_count=0,
            ))
            action = "создан"
        else:
            user.password_hash = hash_password(DEV_PASSWORD)
            user.status = "active"
            action = "обновлён (пароль сброшен)"

        await session.commit()

    print(f"Dev-аккаунт {action}:")
    print(f"  логин:  {DEV_USERNAME}")
    print(f"  пароль: {DEV_PASSWORD}")
    print()
    print("Входить можно и по логину, и по e-mail (admin@local.dev).")
    print("Только для локальной разработки.")


if __name__ == "__main__":
    asyncio.run(main())
