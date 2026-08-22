import logging
from fastapi import APIRouter
from app.config import settings
from app import cache
from app.http_client import request

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_TTL = 600


@router.get("/")
async def get_water_temp():
    async def load_water_temp() -> dict:
        url = f"{settings.WATER_API_BASE_URL}/{settings.SEOUL_DATA_API_KEY}/json/WPOSInformationTime/1/5/"
        try:
            async with request("GET", url, upstream="seoul_data") as resp:
                data = await resp.json(content_type=None)

            if "WPOSInformationTime" not in data:
                return {"error": "데이터 없음"}

            rows = data["WPOSInformationTime"].get("row", [])
            if not rows:
                return {"error": "데이터 없음"}

            target = next(
                (row for row in rows if row.get("MSRSTN_NM") == "선유"), rows[0]
            )
            msr_time = target.get("HR", "00:00")
            if ":" in msr_time:
                hour, minute = msr_time.split(":")
            else:
                hour, minute = "00", "00"

            return {
                "hour": hour,
                "minute": minute,
                "temp": target.get("WATT", "0.0"),
            }
        except Exception as e:
            logger.error(f"한강 수온 API 오류: {e}")
            return {"error": str(e)}

    return await cache.get_or_set(
        "water:temp",
        load_water_temp,
        ttl=CACHE_TTL,
        negative_ttl=60,
        is_negative=lambda value: "error" in value,
    )
