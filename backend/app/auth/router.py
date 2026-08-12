from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import schemas as sc
from app.auth import service as svc
from app.auth.deps import get_current_user
from app.db import get_session
from app.models import User, UserState

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    # За обратным прокси — брать первый адрес из X-Forwarded-For.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _user_out(user: User) -> sc.UserOut:
    return sc.UserOut(
        id=user.id, email=user.email, username=user.username,
        nickname=user.nickname, email_verified=user.email_verified,
    )


@router.post("/register", response_model=sc.TokenPairOut, status_code=201)
async def register(data: sc.RegisterIn, request: Request,
                   session: AsyncSession = Depends(get_session)):
    user, access, refresh = await svc.register_user(session, data, _client_ip(request))
    return sc.TokenPairOut(access_token=access, refresh_token=refresh, user=_user_out(user))


@router.post("/telegram", response_model=sc.TokenPairOut)
async def telegram_login(data: sc.TelegramLoginIn, request: Request,
                         session: AsyncSession = Depends(get_session)):
    """Вход из Telegram Mini App по подписанным данным. Веб-вход не затрагивает."""
    user, access, refresh, is_new = await svc.telegram_login(
        session, data.init_data, _client_ip(request))
    return sc.TokenPairOut(access_token=access, refresh_token=refresh,
                           user=_user_out(user), is_new=is_new)


@router.post("/login", response_model=sc.TokenPairOut)
async def login(data: sc.LoginIn, request: Request,
                session: AsyncSession = Depends(get_session)):
    user, access, refresh = await svc.authenticate(session, data, _client_ip(request))
    return sc.TokenPairOut(access_token=access, refresh_token=refresh, user=_user_out(user))


@router.post("/refresh", response_model=sc.AccessRefreshOut)
async def refresh(data: sc.RefreshIn, session: AsyncSession = Depends(get_session)):
    access, new_refresh = await svc.rotate_refresh(session, data.refresh_token)
    return sc.AccessRefreshOut(access_token=access, refresh_token=new_refresh)


@router.post("/logout", status_code=204)
async def logout(data: sc.LogoutIn, session: AsyncSession = Depends(get_session)):
    await svc.revoke_refresh(session, data.refresh_token)
    return Response(status_code=204)


@router.post("/password/reset-request", response_model=sc.MessageOut)
async def reset_request(data: sc.ResetRequestIn, request: Request,
                        session: AsyncSession = Depends(get_session)):
    await svc.request_password_reset(session, data.email, _client_ip(request))
    return sc.MessageOut(message="Если адрес зарегистрирован, мы отправили письмо со ссылкой")


@router.post("/password/reset-confirm", response_model=sc.MessageOut)
async def reset_confirm(data: sc.ResetConfirmIn, session: AsyncSession = Depends(get_session)):
    await svc.confirm_password_reset(session, data.token, data.new_password)
    return sc.MessageOut(message="Пароль обновлён")


@router.get("/verify-email", response_model=sc.MessageOut)
async def verify_email(token: str, session: AsyncSession = Depends(get_session)):
    await svc.verify_email(session, token)
    return sc.MessageOut(message="E-mail подтверждён")


@router.get("/me", response_model=sc.MeOut)
async def me(user: User = Depends(get_current_user),
             session: AsyncSession = Depends(get_session)):
    state = await session.get(UserState, user.id)
    return sc.MeOut(
        user=_user_out(user),
        state=sc.StateOut(
            xp=state.xp, level=state.level, lives=state.lives, streak_count=state.streak_count
        ),
    )


@router.get("/me/export", tags=["auth"])
async def export_me(user: User = Depends(get_current_user),
                    session: AsyncSession = Depends(get_session)):
    """Выгрузка всех своих данных одним JSON (право на доступ к ПД)."""
    return await svc.export_user_data(session, user)


@router.delete("/me", status_code=204)
async def delete_me(data: sc.DeleteAccountIn,
                    user: User = Depends(get_current_user),
                    session: AsyncSession = Depends(get_session)):
    """Необратимое удаление аккаунта.

    Требование 152-ФЗ и обязательное условие публикации в App Store для
    приложений с регистрацией.
    """
    await svc.delete_account(session, user, data.password, data.confirm)
    return Response(status_code=204)
