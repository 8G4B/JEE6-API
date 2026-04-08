from contextlib import asynccontextmanager
from fastapi import FastAPI
from app import cache
from app.routers import meal, water, riot, spotify, time


@asynccontextmanager
async def lifespan(app: FastAPI):
    await cache.init_redis()
    yield
    await cache.close_redis()


app = FastAPI(title="JEE6 API Gateway", lifespan=lifespan)

app.include_router(meal.router, prefix="/meal", tags=["meal"])
app.include_router(water.router, prefix="/water", tags=["water"])
app.include_router(riot.router, prefix="/riot", tags=["riot"])
app.include_router(spotify.router, prefix="/spotify", tags=["spotify"])
app.include_router(time.router, prefix="/time", tags=["time"])


@app.get("/health")
async def health():
    return {"status": "ok"}
