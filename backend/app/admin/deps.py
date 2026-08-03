"""Доступ к админке — по списку e-mail из настроек (admin_emails)."""
from fastapi import Depends

from app.auth.deps import get_current_user
from app.config import settings
from app.errors import AppError
from app.models import User


async def require_admin(user: User = Depends(get_current_user)) -> User:
    admins = settings.admin_email_set
    if not admins or (user.email or "").lower() not in admins:
        raise AppError(403, "forbidden", "Доступ только для администратора")
    return user
