import os


class Settings:
    REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    MEAL_API_KEY = os.getenv("MEAL_API_KEY", "")
    MEAL_API_BASE_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"
    ATPT_OFCDC_SC_CODE = os.getenv("ATPT_OFCDC_SC_CODE", "F10")
    SD_SCHUL_CODE = os.getenv("SD_SCHUL_CODE", "7380292")

    SEOUL_DATA_API_KEY = os.getenv("SEOUL_DATA_API_KEY", "sample")
    WATER_API_BASE_URL = "http://openapi.seoul.go.kr:8088"

    RIOT_API_KEY = os.getenv("RIOT_API_KEY", "")
    LOL_BASE_URL = "https://kr.api.riotgames.com"
    LOL_ASIA_URL = "https://asia.api.riotgames.com"
    VALO_ASIA_URL = "https://asia.api.riotgames.com"
    VALO_AP_URL = "https://ap.api.riotgames.com"

    SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    SPOTIFY_REFRESH_TOKEN = os.getenv("SPOTIFY_REFRESH_TOKEN", "")
    SPOTIFY_PLAYLIST_ID = [
        pid.strip()
        for pid in os.getenv("SPOTIFY_PLAYLIST_ID", "").split(",")
        if pid.strip()
    ]


settings = Settings()
