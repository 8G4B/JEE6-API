from unittest.mock import AsyncMock, patch


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics(client):
    response = client.get("/metrics/")
    assert response.status_code == 200
    assert "jee6_api_http_request_duration_seconds" in response.text


def test_ready(client):
    redis = AsyncMock()
    with patch("app.main.cache.pool", redis):
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    redis.ping.assert_awaited_once()


def test_ready_fails_without_redis(client):
    with patch("app.main.cache.pool", None):
        response = client.get("/ready")

    assert response.status_code == 503
