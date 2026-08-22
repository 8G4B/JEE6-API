import asyncio
import logging
import random
import time
from fastapi import APIRouter
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from spotipy.cache_handler import MemoryCacheHandler
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

_client: spotipy.Spotify | None = None
_playlist_total_cache: dict[str, tuple[float, int]] = {}
_artist_genres_cache: dict[str, tuple[float, list]] = {}
CACHE_TTL = 3600
MAX_TRACK_ATTEMPTS = 5


def _get_client() -> spotipy.Spotify:
    global _client
    if _client:
        return _client

    if settings.SPOTIFY_REFRESH_TOKEN:
        cache_handler = MemoryCacheHandler(
            token_info={
                "access_token": None,
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": settings.SPOTIFY_REFRESH_TOKEN,
                "scope": "playlist-read-private playlist-read-collaborative",
                "expires_at": 0,
            }
        )
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

        offsets = random.sample(range(total), min(total, MAX_TRACK_ATTEMPTS))
        for offset in offsets:
            result = client.playlist_tracks(
                playlist_id,
                limit=1,
                offset=offset,
                fields=(
                    "items(track(id,name,is_local,artists(id,name),"
                    "album(name,images),external_urls,duration_ms))"
                ),
            )

            items = result.get("items", [])
            track = items[0].get("track") if items else None
            if not track or track.get("is_local") or not track.get("id"):
                continue

            spotify_url = track.get("external_urls", {}).get("spotify")
            album = track.get("album") or {}
            artist_items = track.get("artists") or []
            artists = ", ".join(
                artist["name"] for artist in artist_items if artist.get("name")
            )
            if not track.get("name") or not spotify_url or not artists:
                continue

            images = album.get("images") or []
            album_img = images[0].get("url") if images else None
            duration_ms = track.get("duration_ms", 0)
            minutes, seconds = divmod(duration_ms // 1000, 60)

            genres = []
            artist_id = artist_items[0].get("id") if artist_items else None
            if artist_id:
                cached = _artist_genres_cache.get(artist_id)
                if cached and time.time() - cached[0] < CACHE_TTL:
                    genres = cached[1]
                else:
                    try:
                        artist_info = client.artist(artist_id)
                        genres = artist_info.get("genres", [])
                        _artist_genres_cache[artist_id] = (time.time(), genres)
                    except Exception:
                        logger.warning(
                            "Spotify 아티스트 장르 조회 실패",
                            exc_info=True,
                        )

            return {
                "name": track["name"],
                "artists": artists,
                "album": album.get("name", ""),
                "url": spotify_url,
                "image": album_img,
                "duration": f"{minutes}:{seconds:02d}",
                "genres": genres,
            }

        logger.warning("Spotify 플레이리스트에서 유효한 곡을 찾지 못했습니다")
        return None
    except Exception:
        logger.exception("Spotify API 곡 조회 실패")
        return None


@router.get("/random")
async def random_track():
    playlist_ids = settings.SPOTIFY_PLAYLIST_ID
    if not playlist_ids:
        return {"error": "Spotify 설정이 되어있지 않습니다."}

    playlist_id = random.choice(playlist_ids)

    track = await asyncio.to_thread(_fetch_random_track, playlist_id)

    if track:
        return track
    return {"error": "곡을 가져오는데 실패했습니다."}
