from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, call, patch
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
        call(datetime(2026, 8, 17, tzinfo=ZoneInfo("Asia/Seoul"))),
        call(datetime(2026, 8, 24, tzinfo=ZoneInfo("Asia/Seoul"))),
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


def test_week_endpoint_returns_dated_menus(client):
    rows = [
        {"date": "20261029", "meal_code": "2", "menu": "- 밥", "cal_info": "700 Kcal"}
    ]
    with patch(
        "app.routers.meal._get_week", new_callable=AsyncMock, return_value=rows
    ) as get_week:
        response = client.get("/meal/week?date=20261029")

    assert response.status_code == 200
    assert response.json() == {"week_start": "20261026", "meals": rows}
    get_week.assert_awaited_once_with(
        datetime(2026, 10, 26, tzinfo=ZoneInfo("Asia/Seoul"))
    )


def test_week_endpoint_accepts_next_year_for_year_end_warmup(client):
    with patch("app.routers.meal._get_week", new_callable=AsyncMock, return_value=[]):
        response = client.get("/meal/week?date=20270104")
    assert response.json() == {"week_start": "20270104", "meals": []}


def test_week_endpoint_rejects_invalid_calendar_dates(client):
    with patch("app.routers.meal._get_week", new_callable=AsyncMock) as get_week:
        response = client.get("/meal/week?date=20260230")
    assert "error" in response.json()
    get_week.assert_not_awaited()


@pytest.mark.parametrize("path", ["/meal/", "/meal/week?date=20261029"])
def test_outage_is_not_reported_or_cached_as_no_meal(client, path):
    with (
        patch(
            "app.routers.meal._fetch_meals",
            new_callable=AsyncMock,
            side_effect=RuntimeError("NEIS offline"),
        ),
        patch(
            "app.routers.meal._fetch_meals_from_school",
            new_callable=AsyncMock,
            side_effect=RuntimeError("school offline"),
        ),
        patch("app.routers.meal.cache.set", new_callable=AsyncMock) as cache_set,
    ):
        data = client.get(path).json()
    assert "error" in data
    assert data["menu"] != "급식이 없습니다."
    cache_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_school_fallback_recovers_from_a_neis_exception():
    rows = [{"MLSV_YMD": "20261029", "MMEAL_SC_CODE": "2", "DDISH_NM": "밥"}]
    with (
        patch(
            "app.routers.meal._fetch_meals",
            new_callable=AsyncMock,
            side_effect=RuntimeError("offline"),
        ),
        patch(
            "app.routers.meal._fetch_meals_from_school",
            new_callable=AsyncMock,
            return_value=rows,
        ),
    ):
        result = await meal._load_week(datetime(2026, 10, 26))
    assert result == [
        {"date": "20261029", "meal_code": "2", "menu": "- 밥", "cal_info": ""}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("code,is_empty", [("INFO-200", True), ("ERROR-290", False)])
async def test_neis_distinguishes_no_data_from_api_errors(code, is_empty):
    response = MagicMock()
    response.json = AsyncMock(return_value={"RESULT": {"CODE": code}})

    @asynccontextmanager
    async def request(*args, **kwargs):
        yield response

    with patch("app.routers.meal.request", request):
        if is_empty:
            assert await meal._fetch_meals("20261026", "20261101") == []
        else:
            with pytest.raises(RuntimeError):
                await meal._fetch_meals("20261026", "20261101")


@pytest.mark.asyncio
async def test_broken_school_calendar_is_not_treated_as_no_meals():
    response = MagicMock()
    response.text = AsyncMock(return_value="<html>maintenance</html>")

    @asynccontextmanager
    async def request(*args, **kwargs):
        yield response

    with patch("app.routers.meal.request", request):
        with pytest.raises(RuntimeError):
            await meal._fetch_month_from_school(2026, 10)


@pytest.mark.asyncio
async def test_warmup_always_includes_next_week_before_sunday():
    now = datetime(2026, 10, 29, 12, tzinfo=ZoneInfo("Asia/Seoul"))
    with patch("app.routers.meal._get_week", new_callable=AsyncMock) as get_week:
        await meal.warm_meal_cache(now)
    assert get_week.await_args_list == [
        call(datetime(2026, 10, 26, tzinfo=ZoneInfo("Asia/Seoul"))),
        call(datetime(2026, 11, 2, tzinfo=ZoneInfo("Asia/Seoul"))),
    ]


@pytest.mark.asyncio
async def test_failed_pagination_does_not_return_a_partial_week():
    response = MagicMock()
    response.json = AsyncMock(
        side_effect=[
            {
                "mealServiceDietInfo": [
                    {"head": [{"list_total_count": 2}]},
                    {"row": [{"MLSV_YMD": "20261026", "MMEAL_SC_CODE": "1"}]},
                ]
            },
            RuntimeError("second page offline"),
        ]
    )

    @asynccontextmanager
    async def request(*args, **kwargs):
        yield response

    with patch("app.routers.meal.request", request):
        with pytest.raises(RuntimeError, match="second page offline"):
            await meal._fetch_meals("20261026", "20261101")
