import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException

from app import cache
from app import http_client
from app.metrics import metrics_app, observe_request
from app.routers import meal, water, riot, spotify, time

logger = logging.getLogger(__name__)


async def warm_caches() -> None:
    results = await asyncio.gather(
        riot._load_champion_data(),
        meal.get_meal(meal_type="auto", day="today", date=None),
        meal.get_meal(meal_type="auto", day="tomorrow", date=None),
        water.get_water_temp(),
        return_exceptions=True,
    )
    failures = [result for result in results if isinstance(result, Exception)]
    if failures:
        logger.warning("캐시 사전 로딩 일부 실패: %s", failures)
    else:
        logger.info("초기 응답 캐시 사전 로딩 완료")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await cache.init_redis()
    await http_client.init_http_client()
    warmup_task = None
    if cache.pool is not None:
        warmup_task = asyncio.create_task(warm_caches(), name="api-cache-warmup")
    try:
        yield
    finally:
        if warmup_task is not None and not warmup_task.done():
            warmup_task.cancel()
            with suppress(asyncio.CancelledError):
                await warmup_task
        await http_client.close_http_client()
        await cache.close_redis()


app = FastAPI(title="JEE6 API Gateway", lifespan=lifespan)
app.middleware("http")(observe_request)
app.mount("/metrics", metrics_app)

app.include_router(meal.router, prefix="/meal", tags=["meal"])
app.include_router(water.router, prefix="/water", tags=["water"])
app.include_router(riot.router, prefix="/riot", tags=["riot"])
app.include_router(spotify.router, prefix="/spotify", tags=["spotify"])
app.include_router(time.router, prefix="/time", tags=["time"])


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    if cache.pool is None:
        raise HTTPException(status_code=503, detail="Redis is not initialized")
    try:
        await cache.pool.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Redis is unavailable") from exc
    return {"status": "ready"}
