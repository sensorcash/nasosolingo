from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import settings
from app.errors import AppError

_ph = PasswordHasher(
    time_cost=settings.argon2_time_cost,
    memory_cost=settings.argon2_memory_kib,
    parallelism=settings.argon2_parallelism,
)

# Хеш-«пустышка» для выравнивания тайминга, когда пользователь не найден
# (защита от энумерации по времени ответа). Считается лениво.
_dummy_hash: str | None = None


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _ph.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(password_hash)
    except Exception:
        return True


def dummy_verify(password: str) -> None:
    """Прогнать argon2 впустую, чтобы неудачный вход занимал столько же времени."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _ph.hash("timing-equalizer")
    try:
        _ph.verify(_dummy_hash, password)
    except Exception:
        pass


def validate_password_policy(password: str) -> None:
    if len(password) < settings.password_min_length:
        raise AppError(
            400, "weak_password",
            f"Пароль должен быть не короче {settings.password_min_length} символов",
            field="password",
        )
    if len(password) > settings.password_max_length:
        raise AppError(
            400, "weak_password",
            f"Пароль должен быть не длиннее {settings.password_max_length} символов",
            field="password",
        )
    # [defer-ok] здесь же — проверка по базе утёкших паролей (HIBP k-anonymity)
