import asyncio

import pytest

from app import cache


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
