from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo


def test_get_meal_no_cache_no_api(client):
    with patch(
        "app.routers.meal._fetch_meals", new_callable=AsyncMock, return_value=[]
    ), patch(
        "app.routers.meal._fetch_meals_from_school",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = client.get("/meal/?meal_type=auto&day=today")
        assert response.status_code == 200
        data = response.json()
        assert "title" in data
        assert data["menu"] == "급식이 없습니다."


def test_get_meal_falls_back_to_school(client):
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    school_rows = [
        {
            "MLSV_YMD": today,
            "MMEAL_SC_CODE": "2",
            "DDISH_NM": "김치볶음밥<br/>계란국(1.5)",
            "CAL_INFO": "800.0 Kcal",
        }
    ]
    with patch(
        "app.routers.meal._fetch_meals", new_callable=AsyncMock, return_value=[]
    ), patch(
        "app.routers.meal._fetch_meals_from_school",
        new_callable=AsyncMock,
        return_value=school_rows,
    ):
        response = client.get(f"/meal/?meal_type=lunch&date={today}")
        assert response.status_code == 200
        data = response.json()
        assert "김치볶음밥" in data["menu"]
        assert data["cal_info"] == "800.0 Kcal"


def test_get_meal_invalid_type(client):
    response = client.get("/meal/?meal_type=invalid")
    assert response.status_code == 422


def test_get_meal_invalid_day(client):
    response = client.get("/meal/?day=yesterday")
    assert response.status_code == 422
