import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with patch("app.cache.init_redis", new_callable=AsyncMock), \
         patch("app.cache.close_redis", new_callable=AsyncMock), \
         patch("app.cache.get", new_callable=AsyncMock, return_value=None), \
         patch("app.cache.set", new_callable=AsyncMock):
        from app.main import app
        with TestClient(app) as c:
            yield c
