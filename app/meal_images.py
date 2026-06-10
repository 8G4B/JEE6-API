import logging
import re
import aiohttp
from app.config import settings
from app import cache

logger = logging.getLogger(__name__)

CACHE_TTL = 3600 * 6
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_DAY_RE = re.compile(r'<div class="day_num">(\d+)<')
_IMG_RE = re.compile(r"imgOpen\('([^']*?_(\d)_middle_thumb\.[a-zA-Z]+)'")


async def _fetch_month_images(year: int, month: int) -> dict:
    url = f"{settings.MEAL_IMAGE_BASE_URL}/xboard/board.php"
    params = {
        "mode": "list",
        "tbnum": settings.MEAL_IMAGE_TBNUM,
        "sYear": year,
        "sMonth": f"{month:02d}",
    }

    try:
        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                html = await resp.text()
    except Exception as e:
        logger.error(f"급식 사진 게시판 오류: {e}")
        return {}

    marks = [(m.start(), int(m.group(1))) for m in _DAY_RE.finditer(html)]
    marks.append((len(html), None))

    result: dict = {}
    for i in range(len(marks) - 1):
        start, day = marks[i]
        end = marks[i + 1][0]
        date_str = f"{year}{month:02d}{day:02d}"
        for img in _IMG_RE.finditer(html[start:end]):
            rel, code = img.group(1), img.group(2)
            path = rel.lstrip("./")
            result.setdefault(date_str, {})[code] = f"{settings.MEAL_IMAGE_BASE_URL}/{path}"

    return result


async def get_meal_image(date_str: str, meal_code: str) -> str | None:
    year, month = int(date_str[:4]), int(date_str[4:6])
    cache_key = f"meal_img:{date_str[:6]}"

    images = await cache.get(cache_key)
    if images is None:
        images = await _fetch_month_images(year, month)
        if images:
            await cache.set(cache_key, images, ttl=CACHE_TTL)

    return (images or {}).get(date_str, {}).get(meal_code)
