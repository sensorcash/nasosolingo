import uuid

from pydantic import AliasChoices, BaseModel, EmailStr, Field


class DeviceIn(BaseModel):
    platform: str = "ios"
    push_token: str | None = None
    app_version: str | None = None


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)  # полная политика (10..128) — в сервисе
    nickname: str | None = Field(default=None, max_length=40)
    device: DeviceIn | None = None


class LoginIn(BaseModel):
    """Вход по e-mail ИЛИ по короткому логину (username).

    Поле можно прислать как "login", так и как "email" — второе оставлено
    для совместимости, чтобы старые запросы продолжали работать.
    """
    login: str = Field(
        min_length=1, max_length=320,
        validation_alias=AliasChoices("login", "email"),
    )
    password: str = Field(min_length=1)
    device: DeviceIn | None = None


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: str


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetConfirmIn(BaseModel):
    token: str
    new_password: str = Field(min_length=1)


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    username: str | None = None
    nickname: str | None = None
    email_verified: bool


class StateOut(BaseModel):
    xp: int
    level: int
    lives: int
    streak_count: int


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class AccessRefreshOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    user: UserOut
    state: StateOut


class MessageOut(BaseModel):
    message: str


class DeleteAccountIn(BaseModel):
    """Удаление аккаунта требует подтверждения паролем — действие необратимо."""
    password: str = Field(min_length=1)
    confirm: str = Field(description='Должно быть строкой "УДАЛИТЬ"')
