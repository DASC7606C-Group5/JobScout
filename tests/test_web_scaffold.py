"""Tests for the web and database scaffolding only."""

from fastapi.testclient import TestClient

from jobscout.main import create_app


def test_health_endpoint() -> None:
    """The application exposes a stable infrastructure health endpoint."""

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
