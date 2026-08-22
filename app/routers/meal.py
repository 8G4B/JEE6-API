import html
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Query
from app.config import settings
from app import cache
from app.http_client import request
from app.meal_images import get_meal_image

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
            async with request("GET", url, upstream="neis", params=params) as resp:
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


_SCHOOL_DAY_RE = re.compile(r'<div class="day_num">(\d+)<')
_SCHOOL_MEAL_RE = re.compile(
    r'food_title(\d)[^>]*>.*?<span class="content">(.*?)</span>', re.S
)
_BR_RE = re.compile(r"<br\s*/?>")


def _parse_school_content(content: str) -> tuple[str, str]:
    parts = [
        html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in _BR_RE.split(content)
    ]
    parts = [p for p in parts if p]
    dishes: list[str] = []
    cal = ""
    for i, p in enumerate(parts):
        if p.startswith("*") and "에너지" in p:
            if i + 1 < len(parts):
                energy = parts[i + 1].split("/")[0].strip()
                cal = f"{energy} Kcal" if energy else ""
            break
        dishes.append(p)
    return "<br/>".join(dishes), cal


async def _fetch_month_from_school(year: int, month: int) -> list[dict]:
    url = f"{settings.MEAL_IMAGE_BASE_URL}/xboard/board.php"
    params = {
        "mode": "list",
        "tbnum": settings.MEAL_IMAGE_TBNUM,
        "sYear": year,
        "sMonth": f"{month:02d}",
    }
    try:
        async with request(
            "GET",
            url,
            upstream="school_meal",
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as resp:
            page = await resp.text()
    except Exception as e:
        logger.error(f"학교 급식 게시판 오류: {e}")
        return []

    marks = [(m.start(), int(m.group(1))) for m in _SCHOOL_DAY_RE.finditer(page)]
    marks.append((len(page), None))

    rows: list[dict] = []
    for i in range(len(marks) - 1):
        start, day = marks[i]
        block = page[start : marks[i + 1][0]]
        date_str = f"{year}{month:02d}{day:02d}"
        for tm in _SCHOOL_MEAL_RE.finditer(block):
            menu, cal = _parse_school_content(tm.group(2))
            if menu:
                rows.append(
                    {
                        "MLSV_YMD": date_str,
                        "MMEAL_SC_CODE": tm.group(1),
                        "DDISH_NM": menu,
                        "CAL_INFO": cal,
                    }
                )
    return rows


async def _fetch_meals_from_school(from_ymd: str, to_ymd: str) -> list[dict]:
    from_dt = datetime.strptime(from_ymd, "%Y%m%d")
    to_dt = datetime.strptime(to_ymd, "%Y%m%d")
    months = {(from_dt.year, from_dt.month), (to_dt.year, to_dt.month)}

    rows: list[dict] = []
    for year, month in months:
        rows.extend(await _fetch_month_from_school(year, month))

    return [r for r in rows if from_ymd <= r["MLSV_YMD"] <= to_ymd]


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


def _meal_response(
    title: str, menu: str, cal_info: str, date_str: str = "", code: str = ""
) -> dict:
    # 사진은 여기서 가져오지 않는다. date/meal_code만 실어 보내고,
    # 클라이언트가 /meal/image 로 따로 받아 메시지를 수정해 붙이도록 한다.
    resp = {"title": title, "menu": menu, "cal_info": cal_info}
    if menu != NO_MEAL and date_str and code:
        resp["date"] = date_str
        resp["meal_code"] = code
    return resp


def _error_response(message: str) -> dict:
    return {"title": "❗ 오류", "menu": "", "cal_info": "", "error": message}


@router.get("/")
async def get_meal(
    meal_type: str = Query("auto", regex="^(auto|breakfast|lunch|dinner)$"),
    day: str = Query("today", regex="^(today|tomorrow)$"),
    date: str | None = Query(None, regex="^[0-9]{8}$"),
):
    now = datetime.now(ZoneInfo("Asia/Seoul"))

    # date(YYYYMMDD)가 오면 day보다 우선한다. 올해 날짜만 허용.
    if date is not None:
        if date[:4] != f"{now.year}":
            return _error_response(f"올해({now.year}년) 날짜만 조회할 수 있어요.")
        try:
            target = datetime.strptime(date, "%Y%m%d").replace(
                tzinfo=ZoneInfo("Asia/Seoul")
            )
        except ValueError:
            return _error_response("올바르지 않은 날짜예요.")
    elif day == "tomorrow":
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
        if not rows:
            rows = await _fetch_meals_from_school(from_ymd, to_ymd)
        cached = [_format_meal(r) for r in rows]
        if cached:
            await cache.set(week_key, cached, ttl=CACHE_TTL)

    if meal_type == "auto":
        if date is None and day == "tomorrow":
            code, title = "1", "🍳 내일 아침"
        else:
            code, title = _detect_meal_type(now)
            if date is None and code == "1" and title == "🍳 내일 아침":
                tomorrow = now + timedelta(days=1)
                tomorrow_str = tomorrow.strftime("%Y%m%d")
                for m in cached or []:
                    if m["date"] == tomorrow_str and m["meal_code"] == "1":
                        return _meal_response(
                            title, m["menu"], m["cal_info"], tomorrow_str, "1"
                        )
                return _meal_response(title, NO_MEAL, "")
            if date is not None and title == "🍳 내일 아침":
                code, title = "1", "🍳 아침"
    else:
        code_map = {"breakfast": "1", "lunch": "2", "dinner": "3"}
        if date is None and day == "tomorrow":
            title_map = {
                "breakfast": "🍳 내일 아침",
                "lunch": "🍚 내일 점심",
                "dinner": "🍖 내일 저녁",
            }
        else:
            title_map = {
                "breakfast": "🍳 아침",
                "lunch": "🍚 점심",
                "dinner": "🍖 저녁",
            }
        code = code_map[meal_type]
        title = title_map[meal_type]

    # 날짜를 직접 지정한 경우 제목에 날짜를 덧붙여 명확히 한다.
    if date is not None:
        title = f"{title} ({target.month}/{target.day})"

    for m in cached or []:
        if m["date"] == date_str and m["meal_code"] == code:
            return _meal_response(title, m["menu"], m["cal_info"], date_str, code)

    return _meal_response(title, NO_MEAL, "")


@router.get("/image")
async def get_meal_image_url(
    date: str = Query(..., regex="^[0-9]{8}$"),
    meal_code: str = Query(..., regex="^[123]$"),
):
    return {"image_url": await get_meal_image(date, meal_code)}
