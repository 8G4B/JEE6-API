import logging
from fastapi import APIRouter
import aiohttp
from app.config import settings
from app import cache

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_TTL = 600  # 10분


@router.get("/")
async def get_water_temp():
    cached = await cache.get("water:temp")
    if cached:
        return cached

    url = f"{settings.WATER_API_BASE_URL}/{settings.SEOUL_DATA_API_KEY}/json/WPOSInformationTime/1/5/"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)

        rows = data.get("WPOSInformationTime", {}).get("row", [])
        if not rows:
            return {"error": "데이터 없음"}

        target = next((r for r in rows if "선유" in r.get("SITE_ID", "")), rows[0])

        result = {
            "hour": target.get("MSR_TIME", "00")[:2],
            "minute": target.get("MSR_TIME", "0000")[2:4],
            "temp": target.get("W_TEMP", "?"),
        }

        await cache.set("water:temp", result, ttl=CACHE_TTL)
        return result

    except Exception as e:
        logger.error(f"한강 수온 API 오류: {e}")
        return {"error": str(e)}
