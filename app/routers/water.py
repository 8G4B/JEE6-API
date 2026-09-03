import asyncio
import logging

import aiohttp
from fastapi import APIRouter

from app.config import settings
from app import cache
from app.http_client import request

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_TTL = 600
SEOUL_DATA_TIMEOUT = aiohttp.ClientTimeout(total=3, connect=1.5, sock_read=2)


def _split_time(value: object) -> tuple[str, str]:
    parts = str(value).split(":", maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else ("00", "00")


def _parse_seoul_data(data: dict) -> dict:
    rows = data.get("WPOSInformationTime", {}).get("row", [])
    if not rows:
        raise ValueError("서울 열린데이터 응답에 수온 정보가 없습니다.")

    target = next(
        (row for row in rows if row.get("MSRSTN_NM") == "선유"),
        rows[0],
    )
    hour, minute = _split_time(target.get("HR", "00:00"))
    return {
        "hour": hour,
        "minute": minute,
        "temp": str(target.get("WATT", "0.0")),
    }


def _parse_fallback_data(data: dict) -> dict:
    if not data.get("success") or data.get("temperature") is None:
        raise ValueError("보조 API 응답에 수온 정보가 없습니다.")

    hour, minute = _split_time(data.get("time", "00:00"))
    return {
        "hour": hour,
        "minute": minute,
        "temp": str(data["temperature"]),
    }


async def _load_from_seoul_data() -> dict:
    url = (
        f"{settings.WATER_API_BASE_URL}/{settings.SEOUL_DATA_API_KEY}"
        "/json/WPOSInformationTime/1/5/"
    )
    async with request(
        "GET",
        url,
        upstream="seoul_data",
        timeout=SEOUL_DATA_TIMEOUT,
    ) as resp:
        resp.raise_for_status()
        return _parse_seoul_data(await resp.json(content_type=None))


async def _load_from_fallback() -> dict:
    async with request(
        "GET",
        settings.WATER_FALLBACK_API_URL,
        upstream="hangang_temp_fallback",
    ) as resp:
        resp.raise_for_status()
        return _parse_fallback_data(await resp.json(content_type=None))


@router.get("/")
async def get_water_temp():
    async def load_water_temp() -> dict:
        loaders = (
            ("서울 열린데이터", _load_from_seoul_data),
            ("보조 API", _load_from_fallback),
        )
        for source, loader in loaders:
            try:
                return await loader()
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                ValueError,
            ) as exc:
                logger.warning("한강 수온 %s 조회 실패: %s", source, exc)

        return {
            "error": "한강 수온 정보를 가져올 수 없습니다. 잠시 후 다시 시도해주세요."
        }

    return await cache.get_or_set(
        "water:temp",
        load_water_temp,
        ttl=CACHE_TTL,
        negative_ttl=60,
        is_negative=lambda value: "error" in value,
    )
