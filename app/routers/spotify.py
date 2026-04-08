import asyncio
import logging
import random
import time
from fastapi import APIRouter
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from spotipy.cache_handler import MemoryCacheHandler
from app.config import settings
from app import cache

logger = logging.getLogger(__name__)
router = APIRouter()

_client: spotipy.Spotify | None = None
_playlist_total_cache: dict[str, tuple[float, int]] = {}
_artist_genres_cache: dict[str, tuple[float, list]] = {}
CACHE_TTL = 3600


def _get_client() -> spotipy.Spotify:
    global _client
    if _client:
        return _client

    if settings.SPOTIFY_REFRESH_TOKEN:
        cache_handler = MemoryCacheHandler(token_info={
            "access_token": None,
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": settings.SPOTIFY_REFRESH_TOKEN,
            "scope": "playlist-read-private playlist-read-collaborative",
            "expires_at": 0,
        })
        auth_manager = SpotifyOAuth(
            client_id=settings.SPOTIFY_CLIENT_ID,
            client_secret=settings.SPOTIFY_CLIENT_SECRET,
            redirect_uri="http://127.0.0.1:8888/callback",
            scope="playlist-read-private playlist-read-collaborative",
            cache_handler=cache_handler,
            open_browser=False,
        )
        _client = spotipy.Spotify(auth_manager=auth_manager)
    else:
        _client = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=settings.SPOTIFY_CLIENT_ID,
                client_secret=settings.SPOTIFY_CLIENT_SECRET,
            )
        )
    return _client


def _fetch_random_track(playlist_id: str) -> dict | None:
    try:
        client = _get_client()
        now = time.time()

        if playlist_id in _playlist_total_cache:
            cache_time, cached_total = _playlist_total_cache[playlist_id]
            if now - cache_time < CACHE_TTL:
                total = cached_total
            else:
                result = client.playlist_tracks(playlist_id, limit=1, fields="total")
                total = result["total"]
                _playlist_total_cache[playlist_id] = (now, total)
        else:
            result = client.playlist_tracks(playlist_id, limit=1, fields="total")
            total = result["total"]
            _playlist_total_cache[playlist_id] = (now, total)

        if total == 0:
            return None

        offset = random.randint(0, total - 1)
        result = client.playlist_tracks(
            playlist_id,
            limit=1,
            offset=offset,
            fields="items(track(id,name,artists(id,name),album(name,images),external_urls,duration_ms))",
        )

        items = result.get("items", [])
        if not items or not items[0].get("track"):
            return None

        track = items[0]["track"]
        artists = ", ".join(a["name"] for a in track["artists"])
        album_img = (
            track["album"]["images"][0]["url"]
            if track["album"]["images"]
            else None
        )
        duration_ms = track.get("duration_ms", 0)
        minutes, seconds = divmod(duration_ms // 1000, 60)

        genres = []
        if track["artists"]:
            artist_id = track["artists"][0]["id"]
            if artist_id in _artist_genres_cache:
                cache_time, cached_genres = _artist_genres_cache[artist_id]
                if time.time() - cache_time < CACHE_TTL:
                    genres = cached_genres
                else:
                    artist_info = client.artist(artist_id)
                    genres = artist_info.get("genres", [])
                    _artist_genres_cache[artist_id] = (time.time(), genres)
            else:
                artist_info = client.artist(artist_id)
                genres = artist_info.get("genres", [])
                _artist_genres_cache[artist_id] = (time.time(), genres)

        return {
            "name": track["name"],
            "artists": artists,
            "album": track["album"]["name"],
            "url": track["external_urls"]["spotify"],
            "image": album_img,
            "duration": f"{minutes}:{seconds:02d}",
            "genres": genres,
        }
    except Exception as e:
        logger.error(f"Spotify API 오류: {e}")
        return None


@router.get("/random")
async def random_track():
    playlist_ids = settings.SPOTIFY_PLAYLIST_ID
    if not playlist_ids:
        return {"error": "Spotify 설정이 되어있지 않습니다."}

    playlist_id = random.choice(playlist_ids)

    loop = asyncio.get_event_loop()
    track = await loop.run_in_executor(None, _fetch_random_track, playlist_id)

    if track:
        return track
    return {"error": "곡을 가져오는데 실패했습니다."}
