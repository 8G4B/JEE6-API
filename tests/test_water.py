from unittest.mock import AsyncMock, patch, MagicMock
import aiohttp


def test_get_water_temp_success(client):
    mock_data = {
        "WPOSInformationTime": {
            "row": [
                {"MSRSTN_NM": "선유", "HR": "14:30", "WATT": "22.5"}
            ]
        }
    }

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status = 200

        async def json_fn(content_type=None):
            return mock_data
        resp.json = json_fn
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    mock_session = MagicMock()
    mock_session.get = mock_get
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        response = client.get("/water/")
        assert response.status_code == 200
        data = response.json()
        assert data["hour"] == "14"
        assert data["minute"] == "30"
        assert data["temp"] == "22.5"
