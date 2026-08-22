import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiohttp

from app.metrics import UPSTREAM_COUNT, UPSTREAM_DURATION


_session: aiohttp.ClientSession | None = None
_timeout = aiohttp.ClientTimeout(total=10, connect=2, sock_read=8)


async def init_http_client() -> None:
    global _session
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=20,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
    )
    _session = aiohttp.ClientSession(timeout=_timeout, connector=connector)


async def close_http_client() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


def get_http_client() -> aiohttp.ClientSession:
    if _session is None or _session.closed:
        raise RuntimeError("HTTP client is not initialized")
    return _session


@asynccontextmanager
async def request(
    method: str,
    url: str,
    *,
    upstream: str,
    **kwargs,
) -> AsyncIterator[aiohttp.ClientResponse]:
    started_at = time.perf_counter()
    status = "error"
    try:
        async with get_http_client().request(method, url, **kwargs) as response:
            status = str(response.status)
            yield response
    finally:
        duration = time.perf_counter() - started_at
        UPSTREAM_COUNT.labels(upstream, method, status).inc()
        UPSTREAM_DURATION.labels(upstream, method).observe(duration)
