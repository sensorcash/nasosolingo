from app.config import settings
from app.errors import AppError
from app.redis_client import redis


async def hit_limit(key: str, limit: int, window: int) -> None:
    """Простой счётчик с фиксированным окном. Бросает 429 при превышении."""
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window)
    if count > limit:
        ttl = await redis.ttl(key)
        raise AppError(429, "rate_limited", "Слишком много запросов, попробуйте позже",
                       retry_after=max(int(ttl), 1))


async def check_login_lock(email: str) -> None:
    ttl = await redis.ttl(f"login:lock:{email}")
    if ttl and ttl > 0:
        raise AppError(423, "account_locked", "Слишком много попыток входа, попробуйте позже",
                       retry_after=int(ttl))


async def register_login_failure(email: str) -> None:
    fail_key = f"login:fail:{email}"
    count = await redis.incr(fail_key)
    if count == 1:
        await redis.expire(fail_key, settings.login_fail_window)
    if count >= settings.login_max_fails:
        # экспоненциальный локаут: base * 5^(n-1), с потолком
        locknum = await redis.incr(f"login:locknum:{email}")
        await redis.expire(f"login:locknum:{email}", 24 * 3600)
        seconds = settings.lockout_base_seconds * (5 ** (locknum - 1))
        seconds = min(seconds, settings.lockout_cap_seconds)
        await redis.set(f"login:lock:{email}", "1", ex=seconds)
        await redis.delete(fail_key)


async def reset_login_failures(email: str) -> None:
    await redis.delete(f"login:fail:{email}")
