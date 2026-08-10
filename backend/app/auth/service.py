"""Бизнес-логика авторизации. Роутер — тонкий, вся работа здесь."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.email import send_email_verification, send_password_reset
from app.errors import AppError
from app.models import Device, EmailToken, RefreshToken, User, UserState
from app.redis_client import redis
from app.security.passwords import (
    dummy_verify,
    hash_password,
    needs_rehash,
    validate_password_policy,
    verify_password,
)
from app.security.ratelimit import (
    check_login_lock,
    hit_limit,
    register_login_failure,
    reset_login_failures,
)
from app.security.tokens import (
    create_access_token,
    generate_opaque_token,
    hash_token,
    refresh_expiry,
)
from app.auth.schemas import DeviceIn


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """Разные драйверы отдают время с поясом и без. Приводим к единому виду,
    иначе сравнение дат падает с TypeError."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def _create_device(session: AsyncSession, user: User, device_in: DeviceIn | None) -> Device | None:
    if device_in is None:
        return None
    device = Device(
        user_id=user.id,
        platform=device_in.platform,
        push_token=device_in.push_token,
        app_version=device_in.app_version,
        last_seen_at=_now(),
    )
    session.add(device)
    await session.flush()
    return device


async def _issue_tokens(session: AsyncSession, user: User, device_id: uuid.UUID | None,
                        family_id: uuid.UUID | None = None) -> tuple[str, str]:
    if family_id is None:
        family_id = uuid.uuid4()
    refresh_plain = generate_opaque_token()
    session.add(RefreshToken(
        user_id=user.id,
        device_id=device_id,
        token_hash=hash_token(refresh_plain),
        family_id=family_id,
        expires_at=refresh_expiry(),
    ))
    access = create_access_token(user.id)
    return access, refresh_plain


async def _issue_email_verification(session: AsyncSession, user: User) -> None:
    token = generate_opaque_token()
    session.add(EmailToken(
        user_id=user.id,
        kind="verify",
        token_hash=hash_token(token),
        expires_at=_now() + timedelta(seconds=settings.verify_token_ttl),
    ))
    # В проде — ставить в очередь ПОСЛЕ commit. Здесь заглушка (лог).
    send_email_verification(user.email, token)


async def revoke_all_user_tokens(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


# ---------- публичные операции ----------

async def register_user(session: AsyncSession, data, ip: str) -> tuple[User, str, str]:
    await hit_limit(f"reg:ip:{ip}", settings.register_ip_limit, settings.register_window)
    email = normalize_email(data.email)
    validate_password_policy(data.password)

    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        # Прагматично для игры. Строгий антиэнумерационный режим — см. auth-spec 4.1.
        raise AppError(409, "email_taken", "Такой e-mail уже зарегистрирован", field="email")

    user = User(email=email, password_hash=hash_password(data.password), nickname=data.nickname)
    session.add(user)
    await session.flush()  # получить user.id

    session.add(UserState(user_id=user.id, streak_freezes=2))
    device = await _create_device(session, user, data.device)
    access, refresh = await _issue_tokens(session, user, device.id if device else None)
    await _issue_email_verification(session, user)

    await session.commit()
    return user, access, refresh


async def authenticate(session: AsyncSession, data, ip: str) -> tuple[User, str, str]:
    """Вход по e-mail или короткому логину (username)."""
    login = normalize_email(data.login)          # trim + lower подходит обоим
    await hit_limit(f"login:ip:{ip}", settings.login_ip_limit, settings.login_fail_window)
    await check_login_lock(login)

    # Сначала пробуем username, затем e-mail — оба уникальны, пересечься не могут.
    user = await session.scalar(select(User).where(User.username == login))
    if user is None:
        user = await session.scalar(select(User).where(User.email == login))
    if user is None:
        dummy_verify(data.password)  # выровнять тайминг
        await register_login_failure(login)
        raise AppError(401, "invalid_credentials", "Неверный логин или пароль")

    if not verify_password(user.password_hash, data.password):
        await register_login_failure(login)
        raise AppError(401, "invalid_credentials", "Неверный логин или пароль")

    if user.status == "blocked":
        raise AppError(403, "account_blocked", "Аккаунт заблокирован")

    await reset_login_failures(login)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
    user.last_login_at = _now()

    device = await _create_device(session, user, data.device)
    access, refresh = await _issue_tokens(session, user, device.id if device else None)
    await session.commit()
    return user, access, refresh


async def rotate_refresh(session: AsyncSession, refresh_plain: str) -> tuple[str, str]:
    th = hash_token(refresh_plain)
    rt = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == th))
    if rt is None:
        raise AppError(401, "token_invalid", "Недействительный токен")
    if _aware(rt.expires_at) <= _now():
        raise AppError(401, "token_expired", "Сессия истекла")

    if rt.revoked_at is not None:
        # Повторное использование отозванного токена => вероятный угон.
        # Отзываем всю семью и требуем полноценный вход.
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == rt.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        await session.commit()
        raise AppError(401, "token_invalid", "Токен скомпрометирован, войдите заново")

    rt.revoked_at = _now()
    user = await session.get(User, rt.user_id)
    access, new_refresh = await _issue_tokens(session, user, rt.device_id, family_id=rt.family_id)
    await session.commit()
    return access, new_refresh


async def revoke_refresh(session: AsyncSession, refresh_plain: str) -> None:
    th = hash_token(refresh_plain)
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == th, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await session.commit()


async def request_password_reset(session: AsyncSession, email_raw: str, ip: str) -> None:
    await hit_limit(f"reset:ip:{ip}", settings.reset_ip_limit, settings.reset_window)
    email = normalize_email(email_raw)
    await hit_limit(f"reset:email:{email}", settings.reset_email_limit, settings.reset_window)

    user = await session.scalar(select(User).where(User.email == email))
    if user is not None:
        token = generate_opaque_token()
        await redis.set(f"pwreset:{hash_token(token)}", str(user.id), ex=settings.reset_token_ttl)
        send_password_reset(email, token)
    # Всегда возвращаем успех (не палим наличие адреса).


async def confirm_password_reset(session: AsyncSession, token: str, new_password: str) -> None:
    validate_password_policy(new_password)
    key = f"pwreset:{hash_token(token)}"
    user_id = await redis.get(key)
    if not user_id:
        raise AppError(410, "token_expired", "Ссылка недействительна или истекла")
    await redis.delete(key)  # одноразовость

    user = await session.get(User, uuid.UUID(user_id))
    if user is None:
        raise AppError(410, "token_expired", "Ссылка недействительна")
    user.password_hash = hash_password(new_password)
    await revoke_all_user_tokens(session, user.id)  # разлогин везде
    await session.commit()


async def verify_email(session: AsyncSession, token: str) -> None:
    th = hash_token(token)
    et = await session.scalar(
        select(EmailToken).where(EmailToken.token_hash == th, EmailToken.kind == "verify")
    )
    if et is None or et.used_at is not None or _aware(et.expires_at) <= _now():
        raise AppError(410, "token_expired", "Ссылка недействительна или истекла")
    et.used_at = _now()
    user = await session.get(User, et.user_id)
    if user is not None:
        user.email_verified = True
    await session.commit()


# ---------- удаление аккаунта и выгрузка данных (152-ФЗ + требование Apple) ----------

CONFIRM_WORD = "УДАЛИТЬ"


async def export_user_data(session: AsyncSession, user: User) -> dict:
    """Все данные пользователя одним документом — право на доступ к своим ПД."""
    from app.game.models import GameEvent, QuestionAttempt, UserAchievement, UserProgress

    progress = (await session.scalars(
        select(UserProgress).where(UserProgress.user_id == user.id))).all()
    events = (await session.scalars(
        select(GameEvent).where(GameEvent.user_id == user.id))).all()
    attempts = (await session.scalars(
        select(QuestionAttempt).where(QuestionAttempt.user_id == user.id))).all()
    state = await session.get(UserState, user.id)
    devices = (await session.scalars(
        select(Device).where(Device.user_id == user.id))).all()

    return {
        "exported_at": _now().isoformat(),
        "profile": {
            "id": str(user.id), "email": user.email, "username": user.username,
            "nickname": user.nickname, "region": user.region, "timezone": user.timezone,
            "email_verified": user.email_verified,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        },
        "state": None if state is None else {
            "xp": state.xp, "level": state.level, "lives": state.lives,
            "streak_count": state.streak_count,
            "daily_xp": state.daily_xp, "daily_goal_xp": state.daily_goal_xp,
        },
        "progress": [
            {"lesson_id": str(p.lesson_id), "completions": p.completions,
             "best_correct": p.best_correct, "best_total": p.best_total,
             "completed_at": p.completed_at.isoformat() if p.completed_at else None}
            for p in progress
        ],
        "question_attempts": [
            {"lesson_id": str(a.lesson_id), "question_id": a.question_id,
             "total_attempts": a.total_attempts, "wrong_attempts": a.wrong_attempts,
             "needs_review": a.needs_review}
            for a in attempts
        ],
        "events": [
            {"type": e.type, "payload": e.payload, "xp_awarded": e.xp_awarded,
             "server_ts": e.server_ts.isoformat() if e.server_ts else None}
            for e in events
        ],
        "devices": [
            {"platform": d.platform, "app_version": d.app_version,
             "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None}
            for d in devices
        ],
    }


async def delete_account(session: AsyncSession, user: User, password: str, confirm: str) -> None:
    """Необратимое удаление аккаунта и всех связанных данных.

    Требует пароль и слово-подтверждение: действие нельзя откатить.
    Связанные строки удаляются явно, а не только каскадом БД — так поведение
    одинаково независимо от того, включены ли внешние ключи в конкретной СУБД.
    """
    if confirm.strip().upper() != CONFIRM_WORD:
        raise AppError(400, "confirm_required",
                       f'Для удаления пришлите confirm = "{CONFIRM_WORD}"', field="confirm")

    if not verify_password(user.password_hash, password):
        raise AppError(401, "invalid_credentials", "Неверный пароль")

    from app.game.models import GameEvent, QuestionAttempt, UserAchievement, UserProgress

    user_id = user.id
    for model in (QuestionAttempt, UserAchievement, UserProgress, GameEvent,
                  RefreshToken, EmailToken, Device):
        await session.execute(delete(model).where(model.user_id == user_id))
    await session.execute(delete(UserState).where(UserState.user_id == user_id))
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()


async def telegram_login(session: AsyncSession, init_data: str, ip: str) -> tuple[User, str, str, bool]:
    """Вход через Telegram Mini App.

    Проверяем подпись Telegram, находим пользователя по telegram_id, а если его
    ещё нет — заводим (без пароля: e-mail синтетический, пароль случайный и
    неиспользуемый — такой аккаунт входит только через Telegram). Возвращаем те же
    токены, что и обычный вход, поэтому дальше всё приложение работает как всегда.
    """
    import secrets as _secrets

    from app.auth.telegram import validate_init_data

    info = validate_init_data(init_data)
    tg_id = info["telegram_id"]

    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    is_new = user is None
    if user is None:
        user = User(
            email=f"tg{tg_id}@telegram.bot",
            password_hash=hash_password(_secrets.token_urlsafe(32)),
            nickname=info["first_name"] or f"tg{tg_id}",
            username=None,
            telegram_id=tg_id,
            email_verified=True,          # личность подтверждена Telegram, письма не шлём
        )
        session.add(user)
        await session.flush()
        session.add(UserState(user_id=user.id, streak_freezes=2))
    else:
        # подтянуть свежее имя из Telegram, если оно поменялось
        if info["first_name"] and user.nickname != info["first_name"]:
            user.nickname = info["first_name"]

    user.last_login_at = datetime.now(timezone.utc)
    access, refresh = await _issue_tokens(session, user, None)
    await session.commit()
    return user, access, refresh, is_new
