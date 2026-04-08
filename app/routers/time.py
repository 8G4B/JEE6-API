from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def get_time():
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    return {
        "datetime": now.isoformat(),
        "korean": f"{now.strftime('%Y년 %m월 %d일 %H시 %M분 %S초')}",
    }
