def test_job_routes_remain_open_when_api_key_is_unset(client, monkeypatch):
    monkeypatch.setattr("app.security.settings.API_KEY", "")

    response = client.get("/api/v1/jobs/unknown")

    assert response.status_code == 404


def test_job_routes_require_configured_api_key(client, monkeypatch):
    monkeypatch.setattr("app.security.settings.API_KEY", "test-secret")

    missing = client.get("/api/v1/jobs/unknown")
    invalid = client.get(
        "/api/v1/jobs/unknown",
        headers={"X-API-Key": "wrong-secret"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_job_route_accepts_configured_api_key(client, monkeypatch):
    monkeypatch.setattr("app.security.settings.API_KEY", "test-secret")

    response = client.post(
        "/api/v1/jobs",
        headers={"X-API-Key": "test-secret"},
        json={
            "title": "Authorized Job",
            "recipients": [{"name": "Alice", "email": "alice@example.com"}],
        },
    )

    assert response.status_code == 202
