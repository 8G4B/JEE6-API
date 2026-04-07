import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
import aiohttp
from app.config import settings
from app import cache

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_TTL = 3600 * 6  # 6시간

MEAL_TIMES = {
    "breakfast": (0, 8, 20),
    "lunch": (8, 20, 13, 30),
    "dinner": (13, 30, 19, 30),
}


def _detect_meal_type(now: datetime) -> tuple[str, str]:
    h, m = now.hour, now.minute
    t = h * 60 + m
    if t < 8 * 60 + 20:
        return "1", "🍳 아침"
    elif t < 13 * 60 + 30:
        return "2", "🍚 점심"
    elif t < 19 * 60 + 30:
        return "3", "🍖 저녁"
    else:
        tomorrow = now + timedelta(days=1)
        return "1", f"🍳 내일 아침"


async def _fetch_meals(from_ymd: str, to_ymd: str) -> list[dict]:
    url = settings.MEAL_API_BASE_URL
    params = {
        "key": settings.MEAL_API_KEY,
        "type": "json",
        "ATPT_OFCDC_SC_CODE": settings.ATPT_OFCDC_SC_CODE,
        "SD_SCHUL_CODE": settings.SD_SCHUL_CODE,
        "MLSV_FROM_YMD": from_ymd,
        "MLSV_TO_YMD": to_ymd,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
                rows = data.get("mealServiceDietInfo", [{}])
                if len(rows) < 2:
                    return []
                return rows[1].get("row", [])
    except Exception as e:
        logger.error(f"급식 API 오류: {e}")
        return []


def _format_meal(row: dict) -> dict:
    menu = row.get("DDISH_NM", "").replace("<br/>", "\n")
    menu = "\n".join(
        item.strip().split("(")[0].strip()
        for item in menu.split("\n")
        if item.strip()
    )
    return {
        "date": row.get("MLSV_YMD", ""),
        "meal_code": row.get("MMEAL_SC_CODE", ""),
        "menu": menu,
        "cal_info": row.get("CAL_INFO", ""),
    }


@router.get("/")
async def get_meal(
    meal_type: str = Query("auto", regex="^(auto|breakfast|lunch|dinner)$"),
    day: str = Query("today", regex="^(today|tomorrow)$"),
):
    now = datetime.now()

    if day == "tomorrow":
        target = now + timedelta(days=1)
    else:
        target = now

    date_str = target.strftime("%Y%m%d")

    # 주간 캐시 키
    monday = target - timedelta(days=target.weekday())
    week_key = f"meal:{monday.strftime('%Y%m%d')}"

    # 캐시 조회
    cached = await cache.get(week_key)
    if not cached:
        from_ymd = monday.strftime("%Y%m%d")
        to_ymd = (monday + timedelta(days=6)).strftime("%Y%m%d")
        rows = await _fetch_meals(from_ymd, to_ymd)
        cached = [_format_meal(r) for r in rows]
        if cached:
            await cache.set(week_key, cached, ttl=CACHE_TTL)

    # meal_type 결정
    if meal_type == "auto":
        code, title = _detect_meal_type(now if day == "today" else target)
    else:
        code_map = {"breakfast": "1", "lunch": "2", "dinner": "3"}
        title_map = {
            "breakfast": "🍳 아침",
            "lunch": "🍚 점심",
            "dinner": "🍖 저녁",
        }
        if day == "tomorrow":
            title_map = {k: f"{v.split()[0]} 내일 {v.split()[1]}" for k, v in title_map.items()}
        code = code_map[meal_type]
        title = title_map[meal_type]

    # 해당 날짜+코드 필터
    for m in (cached or []):
        if m["date"] == date_str and m["meal_code"] == code:
            return {"title": title, "menu": m["menu"], "cal_info": m["cal_info"]}

    return {"title": title, "menu": "급식이 없습니다.", "cal_info": ""}
