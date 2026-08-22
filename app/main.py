from contextlib import asynccontextmanager
from fastapi import FastAPI
from app import cache
from app import http_client
from app.metrics import metrics_app, observe_request
from app.routers import meal, water, riot, spotify, time


@asynccontextmanager
async def lifespan(app: FastAPI):
    await cache.init_redis()
    await http_client.init_http_client()
    try:
        yield
    finally:
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
