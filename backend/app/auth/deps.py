import uuid

import jwt
from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import AppError
from app.models import User
from app.security.tokens import decode_access_token


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "token_invalid", "Требуется авторизация")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise AppError(401, "token_expired", "Сессия истекла")
    except jwt.PyJWTError:
        raise AppError(401, "token_invalid", "Недействительный токен")
    if payload.get("typ") != "access":
        raise AppError(401, "token_invalid", "Недействительный токен")
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None or user.status == "blocked":
        raise AppError(401, "token_invalid", "Пользователь недоступен")
    return user
