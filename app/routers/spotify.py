import asyncio
import logging
import random
from fastapi import APIRouter
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from app.config import settings
from app import cache

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_TTL = 3600  # 1시간

_client: spotipy.Spotify | None = None


def _get_client() -> spotipy.Spotify:
    global _client
    if _client:
        return _client

    if settings.SPOTIFY_REFRESH_TOKEN:
        auth = SpotifyOAuth(
            client_id=settings.SPOTIFY_CLIENT_ID,
            client_secret=settings.SPOTIFY_CLIENT_SECRET,
            redirect_uri="http://localhost:8888/callback",
            scope="playlist-read-private",
        )
        token_info = auth.refresh_access_token(settings.SPOTIFY_REFRESH_TOKEN)
        _client = spotipy.Spotify(auth=token_info["access_token"])
    else:
        _client = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=settings.SPOTIFY_CLIENT_ID,
                client_secret=settings.SPOTIFY_CLIENT_SECRET,
            )
        )
    return _client


def _format_duration(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def _fetch_random_track(playlist_id: str) -> dict | None:
    try:
        client = _get_client()

        total = client.playlist_items(playlist_id, limit=1)["total"]
        if total == 0:
            return None

        offset = random.randint(0, total - 1)
        items = client.playlist_items(playlist_id, limit=1, offset=offset)["items"]
        if not items:
            return None

        track = items[0]["track"]
        if not track:
            return None

        artist_ids = [a["id"] for a in track["artists"] if a.get("id")]
        genres = []
        if artist_ids:
            artist_data = client.artist(artist_ids[0])
            genres = artist_data.get("genres", [])

        images = track.get("album", {}).get("images", [])

        return {
            "name": track["name"],
            "artists": ", ".join(a["name"] for a in track["artists"]),
            "album": track.get("album", {}).get("name", ""),
            "url": track.get("external_urls", {}).get("spotify", ""),
            "image": images[0]["url"] if images else None,
            "duration": _format_duration(track.get("duration_ms", 0)),
            "genres": genres[:3],
        }
    except Exception as e:
        logger.error(f"Spotify 조회 실패: {e}")
        return None


@router.get("/random")
async def random_track():
    playlist_ids = settings.SPOTIFY_PLAYLIST_ID
    if not playlist_ids:
        return {"error": "Spotify 설정이 되어있지 않습니다."}

    playlist_id = random.choice(playlist_ids)

    cached = await cache.get(f"spotify:track:{playlist_id}:last")
    if cached:
        pass  # 트랙은 매번 랜덤이므로 캐시 안 씀 (아티스트 장르만 캐시)

    loop = asyncio.get_event_loop()
    track = await loop.run_in_executor(None, _fetch_random_track, playlist_id)

    if track:
        return track
    return {"error": "곡을 가져오는데 실패했습니다."}
