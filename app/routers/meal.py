import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Query
import aiohttp
from app.config import settings
from app import cache

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_TTL = 3600 * 6

NO_MEAL = "급식이 없습니다."

MEAL_TIMES = [
    (lambda h, m: h < 7 or (h == 7 and m < 30), "1", "🍳 아침"),
    (lambda h, m: h < 12 or (h == 12 and m < 30), "2", "🍚 점심"),
    (lambda h, m: h < 18 or (h == 18 and m < 30), "3", "🍖 저녁"),
]


def _detect_meal_type(now: datetime) -> tuple[str, str]:
    h, m = now.hour, now.minute
    for time_check, code, title in MEAL_TIMES:
        if time_check(h, m):
            return code, title
    return "1", "🍳 내일 아침"


async def _fetch_meals(from_ymd: str, to_ymd: str) -> list[dict]:
    if not settings.MEAL_API_KEY:
        logger.warning("MEAL_API_KEY가 없습니다. NEIS API가 pSize=5로 제한됩니다.")

    url = settings.MEAL_API_BASE_URL
    all_rows = []
    page = 1

    try:
        async with aiohttp.ClientSession() as session:
            while True:
                params = {
                    "key": settings.MEAL_API_KEY,
                    "type": "json",
                    "pIndex": page,
                    "pSize": 100,
                    "ATPT_OFCDC_SC_CODE": settings.ATPT_OFCDC_SC_CODE,
                    "SD_SCHUL_CODE": settings.SD_SCHUL_CODE,
                    "MLSV_FROM_YMD": from_ymd,
                    "MLSV_TO_YMD": to_ymd,
                }
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json(content_type=None)
                    info = data.get("mealServiceDietInfo", [{}])
                    if len(info) < 2:
                        break

                    rows = info[1].get("row", [])
                    all_rows.extend(rows)

                    total_count = info[0].get("head", [{}])[0].get("list_total_count", 0)
                    if len(all_rows) >= total_count:
                        break
                    page += 1
    except Exception as e:
        logger.error(f"급식 API 오류: {e}")

    return all_rows


def _format_menu(raw: str) -> str:
    return "\n".join(
        f"- {dish.strip()}"
        for dish in raw.replace("*", "").split("<br/>")
        if dish.strip()
    )


def _format_meal(row: dict) -> dict:
    return {
        "date": row.get("MLSV_YMD", ""),
        "meal_code": row.get("MMEAL_SC_CODE", ""),
        "menu": _format_menu(row.get("DDISH_NM", "")),
        "cal_info": row.get("CAL_INFO", "").strip(),
    }


@router.get("/")
async def get_meal(
    meal_type: str = Query("auto", regex="^(auto|breakfast|lunch|dinner)$"),
    day: str = Query("today", regex="^(today|tomorrow)$"),
):
    now = datetime.now(ZoneInfo("Asia/Seoul"))

    if day == "tomorrow":
        target = now + timedelta(days=1)
    else:
        target = now

    date_str = target.strftime("%Y%m%d")

    monday = target - timedelta(days=target.weekday())
    week_key = f"meal:{monday.strftime('%Y%m%d')}"

    cached = await cache.get(week_key)
    if not cached:
        from_ymd = monday.strftime("%Y%m%d")
        to_ymd = (monday + timedelta(days=6)).strftime("%Y%m%d")
        rows = await _fetch_meals(from_ymd, to_ymd)
        cached = [_format_meal(r) for r in rows]
        if cached:
            await cache.set(week_key, cached, ttl=CACHE_TTL)

    if meal_type == "auto":
        if day == "today":
            code, title = _detect_meal_type(now)
            if code == "1" and title == "🍳 내일 아침":
                tomorrow = now + timedelta(days=1)
                tomorrow_str = tomorrow.strftime("%Y%m%d")
                for m in (cached or []):
                    if m["date"] == tomorrow_str and m["meal_code"] == "1":
                        return {"title": title, "menu": m["menu"], "cal_info": m["cal_info"]}
                return {"title": title, "menu": NO_MEAL, "cal_info": ""}
        else:
            code, title = "1", "🍳 내일 아침"
    else:
        code_map = {"breakfast": "1", "lunch": "2", "dinner": "3"}
        title_map = {
            "breakfast": "🍳 아침",
            "lunch": "🍚 점심",
            "dinner": "🍖 저녁",
        }
        if day == "tomorrow":
            title_map = {
                "breakfast": "🍳 내일 아침",
                "lunch": "🍚 내일 점심",
                "dinner": "🍖 내일 저녁",
            }
        code = code_map[meal_type]
        title = title_map[meal_type]

    for m in (cached or []):
        if m["date"] == date_str and m["meal_code"] == code:
            return {"title": title, "menu": m["menu"], "cal_info": m["cal_info"]}

    return {"title": title, "menu": NO_MEAL, "cal_info": ""}
