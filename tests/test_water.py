from contextlib import asynccontextmanager
from unittest.mock import patch, MagicMock


def test_get_water_temp_success(client):
    mock_data = {
        "WPOSInformationTime": {
            "row": [{"MSRSTN_NM": "선유", "HR": "14:30", "WATT": "22.5"}]
        }
    }

    @asynccontextmanager
    async def mock_request(method, url, **kwargs):
        resp = MagicMock()
        resp.status = 200

        async def json_fn(content_type=None):
            return mock_data

        resp.json = json_fn
        yield resp

    with patch("app.routers.water.request", mock_request):
        response = client.get("/water/")
        assert response.status_code == 200
        data = response.json()
        assert data["hour"] == "14"
        assert data["minute"] == "30"
        assert data["temp"] == "22.5"
