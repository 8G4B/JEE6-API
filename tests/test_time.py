def test_get_time(client):
    response = client.get("/time/")
    assert response.status_code == 200
    data = response.json()
    assert "datetime" in data
    assert "korean" in data
    assert "년" in data["korean"]
