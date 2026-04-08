from unittest.mock import AsyncMock, patch


def test_get_meal_no_cache_no_api(client):
    with patch("app.routers.meal._fetch_meals", new_callable=AsyncMock, return_value=[]):
        response = client.get("/meal/?meal_type=auto&day=today")
        assert response.status_code == 200
        data = response.json()
        assert "title" in data
        assert data["menu"] == "급식이 없습니다."


def test_get_meal_invalid_type(client):
    response = client.get("/meal/?meal_type=invalid")
    assert response.status_code == 422


def test_get_meal_invalid_day(client):
    response = client.get("/meal/?day=yesterday")
    assert response.status_code == 422
