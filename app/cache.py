import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)

pool: redis.Redis | None = None
T = TypeVar("T")
MEMORY_CACHE_TTL = 60

_memory_cache: dict[str, tuple[float, Any]] = {}


@dataclass
class _LockEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


_key_locks: dict[str, _LockEntry] = {}
_key_locks_guard = asyncio.Lock()


async def init_redis():
    global pool
    pool = redis.from_url(settings.REDIS_URL, decode_responses=True)
    logger.info(f"Redis 연결: {settings.REDIS_URL}")


async def close_redis():
    global pool
    if pool:
        await pool.close()
    pool = None
    _memory_cache.clear()


async def get(key: str) -> Any | None:
    cached = _memory_cache.get(key)
    if cached is not None:
        expires_at, value = cached
        if time.monotonic() < expires_at:
            return value
        _memory_cache.pop(key, None)

    if not pool:
        return None
    raw = await pool.get(key)
    if raw is None:
        return None
    value = json.loads(raw)
    _memory_cache[key] = (time.monotonic() + MEMORY_CACHE_TTL, value)
    return value


async def set(key: str, value: Any, ttl: int = 600):
    if ttl > 0:
        _memory_cache[key] = (time.monotonic() + ttl, value)
    else:
        _memory_cache.pop(key, None)

    if not pool:
        return
    await pool.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)


@asynccontextmanager
async def _single_flight(key: str):
    async with _key_locks_guard:
        entry = _key_locks.setdefault(key, _LockEntry())
        entry.users += 1

    try:
        await entry.lock.acquire()
    except BaseException:
        async with _key_locks_guard:
            entry.users -= 1
            if entry.users == 0 and _key_locks.get(key) is entry:
                _key_locks.pop(key, None)
        raise

    try:
        yield
    finally:
        entry.lock.release()
        async with _key_locks_guard:
            entry.users -= 1
            if entry.users == 0 and _key_locks.get(key) is entry:
                _key_locks.pop(key, None)


async def get_or_set(
    key: str,
    loader: Callable[[], Awaitable[T]],
    *,
    ttl: int = 600,
    negative_ttl: int = 60,
    is_negative: Callable[[T], bool] | None = None,
) -> T:
    cached = await get(key)
    if cached is not None:
        return cached

    async with _single_flight(key):
        cached = await get(key)
        if cached is not None:
            return cached

        value = await loader()
        negative = is_negative(value) if is_negative else not value
        value_ttl = negative_ttl if negative else ttl
        if value_ttl > 0:
            await set(key, value, ttl=value_ttl)
        return value
