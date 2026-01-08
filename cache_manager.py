import redis.asyncio as aioredis
import json
import hashlib
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class CacheManager:
    def __init__(self, redis_url: str = "redis://localhost:6380"):
        self.redis = aioredis.from_url(redis_url, decode_responses=True)
        self.default_ttl = 3600

    async def get(self, key: str) -> Optional[Any]:
        """Получить данные из кэша"""
        try:
            cached = await self.redis.get(key)
            if cached:
                logger.info(f"📦 Redis кэш HIT: {key[:30]}...")
                return json.loads(cached)
            return None
        except Exception as e:
            logger.warning(f"⚠️ Ошибка Redis get: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int = None):
        """ Сохранить данные в кэш """
        try:
            await self.redis.setex(
                key,
                ttl or self.default_ttl,
                json.dumps(value, default=str)
            )
            logger.info(f"💾 Redis кэш SET: {key[:30]}... (TTL: {ttl or self.default_ttl}сек)")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка Redis set: {e}")

    async def delete(self, key: str):
        """ Удалить данные из кэша """
        try:
            await self.redis.delete(key)
        except Exception as e:
            logger.warning(f"⚠️ Ошибка Redis delete: {e}")

    def generate_key(self, prefix: str, *args) -> str:
        """ Сгенерировать ключ для кэша """
        content = ":".join(str(arg) for arg in args)
        return f"{prefix}:{hashlib.md5(content.encode()).hexdigest()}"


cache_manager = CacheManager()