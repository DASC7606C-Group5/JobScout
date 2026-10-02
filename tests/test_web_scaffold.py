"""Tests for the web and database scaffolding only."""

from fastapi.testclient import TestClient

from jobscout.main import create_app

SESSION_PREFERENCES: dict[str, object] = {
    "location": "香港",
    "location_unrestricted": False,
    "employment_type": "full-time",
    "salary_range": None,
    "work_mode": None,
    "industry": None,
}
SESSION_INPUT: dict[str, object] = {
    "description": "熟悉 React 的应届毕业生",
    "resume": None,
    "target_directions": ["前端开发"],
    "preferences": SESSION_PREFERENCES,
}


def test_health_endpoint() -> None:
    """The application exposes a stable infrastructure health endpoint."""

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_get_session() -> None:
    with TestClient(create_app()) as client:
        created = client.post("/api/v1/sessions", json=SESSION_INPUT)
        session_id = created.json()["session_id"]
        fetched = client.get(f"/api/v1/sessions/{session_id}")

    assert created.status_code == 201
    assert created.json()["outcome"] == "completed"
    assert created.json()["state"]["input_data"] == SESSION_INPUT
    assert fetched.status_code == 200
    assert fetched.json()["session_id"] == session_id
    assert fetched.json()["state"]["current_stage"] == "completed"


def test_session_can_pause_resume_and_delete() -> None:
    incomplete_input = {
        **SESSION_INPUT,
        "target_directions": [],
        "preferences": {
            **SESSION_PREFERENCES,
            "location": None,
            "employment_type": None,
        },
    }
    with TestClient(create_app()) as client:
        created = client.post("/api/v1/sessions", json=incomplete_input)
        session_id = created.json()["session_id"]
        fetched = client.get(f"/api/v1/sessions/{session_id}")
        resumed = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "answers": {
                    "target_directions": "前端开发",
                    "preferences.location": "香港",
                    "preferences.employment_type": "full-time",
                }
            },
        )
        deleted = client.delete(f"/api/v1/sessions/{session_id}")
        missing = client.get(f"/api/v1/sessions/{session_id}")

    assert created.status_code == 201
    assert created.json()["outcome"] == "paused"
    assert fetched.status_code == 200
    assert fetched.json()["outcome"] == "paused"
    assert resumed.status_code == 200
    assert resumed.json()["outcome"] == "completed"
    assert resumed.json()["session_id"] == session_id
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_resume_rejects_non_paused_session() -> None:
    with TestClient(create_app()) as client:
        created = client.post("/api/v1/sessions", json=SESSION_INPUT)
        session_id = created.json()["session_id"]
        response = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={"answers": {"preferences.location": "香港"}},
        )

    assert response.status_code == 409


def test_create_session_rejects_non_contract_fields() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/sessions",
            json={**SESSION_INPUT, "job_directions": ["前端开发"]},
        )

    assert response.status_code == 422


def test_create_session_requires_all_preference_fields() -> None:
    preferences = {key: value for key, value in SESSION_PREFERENCES.items() if key != "salary_range"}
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/sessions",
            json={**SESSION_INPUT, "preferences": preferences},
        )

    assert response.status_code == 422
