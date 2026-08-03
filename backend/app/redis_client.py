import redis.asyncio as aioredis

from app.config import settings

# Ленивое подключение: реальный коннект произойдёт при первом запросе.
redis = aioredis.from_url(settings.redis_url, decode_responses=True)
