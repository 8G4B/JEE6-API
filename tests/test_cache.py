import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app import cache


@pytest.fixture(autouse=True)
def clear_memory_cache():
    cache._memory_cache.clear()
    yield
    cache._memory_cache.clear()


@pytest.mark.asyncio
async def test_get_reuses_the_in_process_cache(monkeypatch):
    redis_pool = AsyncMock()
    redis_pool.get.return_value = json.dumps({"value": 1})
    monkeypatch.setattr(cache, "pool", redis_pool)

    assert await cache.get("hot-key") == {"value": 1}
    assert await cache.get("hot-key") == {"value": 1}

    redis_pool.get.assert_awaited_once_with("hot-key")


@pytest.mark.asyncio
async def test_set_keeps_a_local_fallback_without_redis(monkeypatch):
    monkeypatch.setattr(cache, "pool", None)

    await cache.set("local-key", {"value": 1}, ttl=60)

    assert await cache.get("local-key") == {"value": 1}


@pytest.mark.asyncio
async def test_expired_local_value_falls_back_to_redis(monkeypatch):
    redis_pool = AsyncMock()
    redis_pool.get.return_value = json.dumps({"value": "fresh"})
    monkeypatch.setattr(cache, "pool", redis_pool)
    monkeypatch.setattr(cache.time, "monotonic", lambda: 100)
    cache._memory_cache["expired-key"] = (99, {"value": "stale"})

    assert await cache.get("expired-key") == {"value": "fresh"}
    redis_pool.get.assert_awaited_once_with("expired-key")


@pytest.mark.asyncio
async def test_get_or_set_coalesces_concurrent_misses(monkeypatch):
    values = {}
    loader_calls = 0

    async def fake_get(key):
        return values.get(key)

    async def fake_set(key, value, ttl):
        values[key] = value

    async def loader():
        nonlocal loader_calls
        loader_calls += 1
        await asyncio.sleep(0)
        return {"value": 1}

    monkeypatch.setattr(cache, "get", fake_get)
    monkeypatch.setattr(cache, "set", fake_set)

    results = await asyncio.gather(
        *[cache.get_or_set("same-key", loader) for _ in range(10)]
    )

    assert results == [{"value": 1}] * 10
    assert loader_calls == 1


@pytest.mark.asyncio
async def test_get_or_set_uses_short_ttl_for_empty_values(monkeypatch):
    recorded_ttls = []

    async def fake_get(key):
        return None

    async def fake_set(key, value, ttl):
        recorded_ttls.append(ttl)

    async def loader():
        return []

    monkeypatch.setattr(cache, "get", fake_get)
    monkeypatch.setattr(cache, "set", fake_set)

    assert await cache.get_or_set("empty-key", loader, ttl=600, negative_ttl=30) == []
    assert recorded_ttls == [30]


@pytest.mark.asyncio
async def test_get_or_set_supports_custom_negative_values(monkeypatch):
    recorded_ttls = []

    async def fake_get(key):
        return None

    async def fake_set(key, value, ttl):
        recorded_ttls.append(ttl)

    async def loader():
        return {"error": "unavailable"}

    monkeypatch.setattr(cache, "get", fake_get)
    monkeypatch.setattr(cache, "set", fake_set)

    result = await cache.get_or_set(
        "error-key",
        loader,
        ttl=600,
        negative_ttl=30,
        is_negative=lambda value: "error" in value,
    )

    assert result == {"error": "unavailable"}
    assert recorded_ttls == [30]
