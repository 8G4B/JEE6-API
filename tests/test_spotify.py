from unittest.mock import MagicMock, patch

from app.routers import spotify


def _track() -> dict:
    return {
        "id": "track-id",
        "name": "Test Track",
        "is_local": False,
        "artists": [{"id": "artist-id", "name": "Test Artist"}],
        "album": {"name": "Test Album", "images": [{"url": "image-url"}]},
        "external_urls": {"spotify": "spotify-url"},
        "duration_ms": 185000,
    }


def setup_function():
    spotify._playlist_total_cache.clear()
    spotify._artist_genres_cache.clear()


def test_fetch_random_track_retries_local_tracks():
    client = MagicMock()
    client.playlist_tracks.side_effect = [
        {"total": 2},
        {"items": [{"track": {"id": None, "is_local": True}}]},
        {"items": [{"track": _track()}]},
    ]
    client.artist.return_value = {"genres": ["pop"]}

    with (
        patch("app.routers.spotify._get_client", return_value=client),
        patch("app.routers.spotify.random.sample", return_value=[0, 1]),
    ):
        result = spotify._fetch_random_track("playlist-id")

    assert result == {
        "name": "Test Track",
        "artists": "Test Artist",
        "album": "Test Album",
        "url": "spotify-url",
        "image": "image-url",
        "duration": "3:05",
        "genres": ["pop"],
    }
    assert client.playlist_tracks.call_count == 3


def test_fetch_random_track_keeps_track_when_genres_fail():
    client = MagicMock()
    client.playlist_tracks.side_effect = [
        {"total": 1},
        {"items": [{"track": _track()}]},
    ]
    client.artist.side_effect = RuntimeError("genre lookup failed")

    with patch("app.routers.spotify._get_client", return_value=client):
        result = spotify._fetch_random_track("playlist-id")

    assert result is not None
    assert result["name"] == "Test Track"
    assert result["genres"] == []
