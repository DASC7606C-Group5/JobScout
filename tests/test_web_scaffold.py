"""HTTP lifecycle tests with an injected, offline interrupt graph."""

import time
from typing import Any, TypedDict, cast

from fastapi.testclient import TestClient as BaseTestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from jobscout.main import create_app
from tests.auth_client import AuthenticatedClient as TestClient

SESSION_INPUT: dict[str, object] = {
    "request_id": "http-create",
    "description": "熟悉 React 的应届毕业生",
}


class FixtureState(TypedDict, total=False):
    session_id: str
    input_data: dict[str, object]
    revision: int
    current_stage: str


def fixture_graph() -> Any:
    def prepare(state: FixtureState) -> FixtureState:
        return {"current_stage": "clarify"}

    def wait(state: FixtureState) -> FixtureState:
        interrupt({"message": "测试等待"})
        return {"current_stage": "completed"}

    builder = StateGraph(FixtureState)
    builder.add_node("prepare", prepare)
    builder.add_node("wait", wait)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "wait")
    builder.add_edge("wait", END)
    compiled = builder.compile(checkpointer=InMemorySaver())

    async def cleanup_session(session_id: str) -> None:
        pass

    cast(Any, compiled).cleanup_session = cleanup_session
    return compiled


def settled(client: BaseTestClient, session_id: str) -> dict[str, Any]:
    for _ in range(100):
        data: dict[str, Any] = client.get(f"/api/v1/sessions/{session_id}").json()
        if data["outcome"] != "running":
            return data
        time.sleep(0.01)
    raise AssertionError("Session did not settle")


def test_health_endpoint() -> None:
    with TestClient(create_app(graph=fixture_graph())) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_get_session() -> None:
    with TestClient(create_app(graph=fixture_graph())) as client:
        created = client.post("/api/v1/sessions", json=SESSION_INPUT)
        assert created.status_code == 202
        assert created.json()["outcome"] == "running"
        session_id = created.json()["session_id"]
        fetched = settled(client, session_id)
        repeated = client.post("/api/v1/sessions", json=SESSION_INPUT)
        assert repeated.json()["session_id"] == session_id
        assert fetched["outcome"] == "paused"
        assert fetched["revision"] == 1


def test_session_can_pause_resume_and_delete() -> None:
    with TestClient(create_app(graph=fixture_graph())) as client:
        session_id = client.post("/api/v1/sessions", json=SESSION_INPUT).json()["session_id"]
        fetched = settled(client, session_id)
        resumed = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "answer-1",
                "expected_revision": fetched["revision"],
                "message": "继续",
            },
        )
        assert resumed.status_code == 202
        assert settled(client, session_id)["outcome"] == "completed"
        assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204
        assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404


def test_resume_rejects_stale_revision() -> None:
    with TestClient(create_app(graph=fixture_graph())) as client:
        session_id = client.post("/api/v1/sessions", json=SESSION_INPUT).json()["session_id"]
        settled(client, session_id)
        response = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "stale",
                "expected_revision": 0,
                "message": "继续",
            },
        )
        assert response.status_code == 409


def test_create_session_rejects_non_contract_fields() -> None:
    with TestClient(create_app(graph=fixture_graph())) as client:
        response = client.post(
            "/api/v1/sessions", json={**SESSION_INPUT, "job_directions": ["前端"]}
        )
        assert response.status_code == 422


def test_create_accepts_partial_preferences_but_requires_materials() -> None:
    with TestClient(create_app(graph=fixture_graph())) as client:
        response = client.post("/api/v1/sessions", json={**SESSION_INPUT, "preferences": {}})
        assert response.status_code == 202
        missing = client.post("/api/v1/sessions", json={"request_id": "empty"})
        assert missing.status_code == 422
