import json
import logging
from typing import Any
import redis.asyncio as redis
from app.config import settings

logger = logging.getLogger(__name__)

pool: redis.Redis | None = None


async def init_redis():
    global pool
    pool = redis.from_url(settings.REDIS_URL, decode_responses=True)
    logger.info(f"Redis 연결: {settings.REDIS_URL}")


async def close_redis():
    global pool
    if pool:
        await pool.close()


async def get(key: str) -> Any | None:
    if not pool:
        return None
    raw = await pool.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def set(key: str, value: Any, ttl: int = 600):
    if not pool:
        return
    await pool.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
