from datetime import datetime
from unittest.mock import AsyncMock, call, patch
from zoneinfo import ZoneInfo

import pytest

from app.routers import meal


def test_get_meal_no_cache_no_api(client):
    with (
        patch("app.routers.meal._fetch_meals", new_callable=AsyncMock, return_value=[]),
        patch(
            "app.routers.meal._fetch_meals_from_school",
            new_callable=AsyncMock,
            return_value=[],
        ),
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
    with (
        patch("app.routers.meal._fetch_meals", new_callable=AsyncMock, return_value=[]),
        patch(
            "app.routers.meal._fetch_meals_from_school",
            new_callable=AsyncMock,
            return_value=school_rows,
        ),
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


@pytest.mark.asyncio
async def test_warm_meal_cache_loads_current_and_next_week_on_sunday():
    sunday = datetime(2026, 8, 23, 12, tzinfo=ZoneInfo("Asia/Seoul"))

    with patch("app.routers.meal._get_week", new_callable=AsyncMock) as get_week:
        await meal.warm_meal_cache(sunday)

    assert get_week.await_count == 2
    assert get_week.await_args_list == [
        call(datetime(2026, 8, 17, 12, tzinfo=ZoneInfo("Asia/Seoul"))),
        call(datetime(2026, 8, 24, 12, tzinfo=ZoneInfo("Asia/Seoul"))),
    ]


@pytest.mark.asyncio
async def test_refresh_meal_cache_keeps_stale_data_on_empty_response():
    now = datetime(2026, 8, 22, 12, tzinfo=ZoneInfo("Asia/Seoul"))

    with (
        patch("app.routers.meal._load_week", new_callable=AsyncMock, return_value=[]),
        patch("app.routers.meal.cache.set", new_callable=AsyncMock) as cache_set,
    ):
        await meal.refresh_meal_cache(now)

    cache_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_meal_reads_next_week_cache_on_sunday_night():
    class SundayNight(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 23, 22, 19, tzinfo=tz)

    next_monday_breakfast = {
        "date": "20260824",
        "meal_code": "1",
        "menu": "- 친환경백미밥",
        "cal_info": "577.91 Kcal",
    }

    with (
        patch("app.routers.meal.datetime", SundayNight),
        patch(
            "app.routers.meal._get_week",
            new_callable=AsyncMock,
            side_effect=[[], [next_monday_breakfast]],
        ) as get_week,
    ):
        result = await meal.get_meal(meal_type="auto", day="today", date=None)

    assert result["title"] == "🍳 내일 아침"
    assert result["menu"] == "- 친환경백미밥"
    assert result["date"] == "20260824"
    assert get_week.await_count == 2


def test_parse_school_content_merges_wrapped_dish_names():
    # 학교 게시판은 메뉴명이 길면 중간에 <br />를 넣어 올린다.
    content = (
        "오므라이스<br />\n"
        "(1.2.5.6.10.12.13.15.16.18)<br />\n"
        "얼갈이된장국(5.6.9.13)<br />\n"
        "진미채야채초무침(자율)<br />\n"
        "(5.6.13.17)<br />\n"
        "청포도주스<br />\n"
        "*에너지/단백질/칼슘/철<br />\n"
        "887.91/37.84/310.41/3.81"
    )
    menu, cal = meal._parse_school_content(content)

    assert menu.split("<br/>") == [
        "오므라이스(1.2.5.6.10.12.13.15.16.18)",
        "얼갈이된장국(5.6.9.13)",
        "진미채야채초무침(자율)(5.6.13.17)",
        "청포도주스",
    ]
    assert cal == "887.91 Kcal"


def test_parse_school_content_merges_break_inside_parens():
    content = "상추쌈,청양고추&amp;쌈장(<br />\n5.6.13)<br />\n배추김치(9)"
    menu, _ = meal._parse_school_content(content)

    assert menu.split("<br/>") == ["상추쌈,청양고추&쌈장(5.6.13)", "배추김치(9)"]


def test_parse_school_content_merges_star_continuation_but_keeps_banner():
    content = (
        "*잔반없는날*<br />\n"
        "감말랭이양상추샐러드<br />\n"
        "*오리엔탈s(5.6.12.13)<br />\n"
        "배추김치(9)"
    )
    menu, _ = meal._parse_school_content(content)

    assert menu.split("<br/>") == [
        "*잔반없는날*",
        "감말랭이양상추샐러드*오리엔탈s(5.6.12.13)",
        "배추김치(9)",
    ]
