"""Restart, ownership and raw-data contracts against the actual shared SQLite storage."""

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from replay.app import create_replay_app
from replay.dataset import load_dataset
from replay.provider import ReplayProvider
from tortoise.backends.base.client import BaseDBAsyncClient

from jobscout.main import create_app
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.services.session_service import _Session
from tests.test_applicant_notices import NOW, posting
from tests.test_session_operations import ControlledGraph
from tests.test_web_scaffold import settled

CREATE: dict[str, Any] = {
    "request_id": "persistent-create",
    "description": load_dataset().profile_input("data-analyst-internship")["description"],
    "target_directions": ["Data Analyst"],
    "preferences": {"location": "Hong Kong", "employment_type": "internship"},
}
RAW_DRAFT: dict[str, Any] = {
    "search_options": {"result_count": 10},
    "description": "  学生经历\nPython, SQL  ",
    "resume": {"name": "简历.txt", "text": "Education\n项目经历，SQL\n"},
    "directions": "数据分析， 前端开发，",
    "preferences": {
        "location": "  深圳  ",
        "location_unrestricted": False,
        "employment_type": None,
        "employment_type_unrestricted": False,
        "salary_range": "  25000  ",
        "work_mode": "",
        "industry": None,
    },
}


class CountingProvider(ReplayProvider):
    def __init__(self) -> None:
        super().__init__(load_dataset())
        self.calls = 0

    async def structured[T: BaseModel](
        self,
        schema: type[T],
        messages: list[dict[str, str]],
        *,
        deadline: float | None = None,
    ) -> T:
        self.calls += 1
        return await super().structured(schema, messages, deadline=deadline)


def summary_draft(profile: dict[str, Any]) -> dict[str, Any]:
    fields = {
        name: "\n".join(profile[name])
        for name in ("education", "skills", "internships", "projects", "target_directions")
    }
    fields.update(
        {
            f"preferences.{name}": value if value is not None else ""
            for name, value in profile["preferences"].items()
            if name not in {"locations", "employment", "work_arrangement"}
        }
    )
    fields["target_directions"] = "  Data Analyst，\n"
    fields["search_options.result_count"] = profile["search_options"]["result_count"]
    return {"fields": fields, "message": "  keep this unfinished note  "}


def test_restart_restores_waiting_checkpoint_and_raw_drafts_then_resumes(tmp_path: Path) -> None:
    database = tmp_path / "restart.sqlite3"
    database_url = f"sqlite://{database.as_posix()}"
    with TestClient(create_replay_app(database_url=database_url)) as client:
        draft = client.put(
            "/api/v1/workspace/draft",
            json={"request_id": "profile-draft", "expected_revision": 0, "data": RAW_DRAFT},
        )
        assert draft.status_code == 200
        assert draft.json()["data"] == RAW_DRAFT
        session_id = client.post("/api/v1/sessions", json=CREATE).json()["session_id"]
        waiting = settled(client, session_id)
        assert waiting["current_stage"] == "confirm"
        original_summary = summary_draft(waiting["profile"])
        saved = client.put(
            f"/api/v1/sessions/{session_id}/drafts/{waiting['revision']}/summary",
            json={"request_id": "summary-draft", "expected_revision": 0, "data": original_summary},
        )
        assert saved.status_code == 200
        assert saved.json()["data"] == original_summary

    provider = CountingProvider()
    with TestClient(create_replay_app(provider=provider, database_url=database_url)) as client:
        restored = client.get(f"/api/v1/sessions/{session_id}").json()
        assert restored == waiting
        assert provider.calls == 0
        repeated = client.post("/api/v1/sessions", json=CREATE)
        assert repeated.json()["session_id"] == session_id
        assert provider.calls == 0
        assert client.get("/api/v1/workspace/draft").json() == draft.json()
        assert (
            client.get(f"/api/v1/sessions/{session_id}/drafts/{waiting['revision']}/summary").json()
            == saved.json()
        )
        resumed = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "restored-confirm",
                "expected_revision": waiting["revision"],
                "action": "confirm_search",
            },
        )
        assert resumed.status_code == 202, resumed.json()
        completed = settled(client, session_id)
        assert completed["outcome"] == "completed"
        assert completed["conversation"][: len(waiting["conversation"])] == waiting["conversation"]
        assert completed["recommendation"]["jobs"]
        assert (
            client.get(
                f"/api/v1/sessions/{session_id}/drafts/{completed['revision']}/summary"
            ).json()["data"]
            == {}
        )
        assert client.get("/api/v1/workspace/draft").json()["data"] == RAW_DRAFT

    with TestClient(create_replay_app(database_url=database_url)) as client:
        assert client.get(f"/api/v1/sessions/{session_id}").json() == completed
        history = client.get("/api/v1/sessions").json()["items"]
        assert [item["session_id"] for item in history] == [session_id]
        assert history[0]["title"] == "Data Analyst"
        assert history[0]["location"] == "Hong Kong"
        assert history[0]["mode"] == "replay"


def test_interrupted_operation_waits_for_manual_retry_without_provider_calls(
    tmp_path: Path,
) -> None:
    class BlockedProvider(CountingProvider):
        async def structured[T: BaseModel](
            self,
            schema: type[T],
            messages: list[dict[str, str]],
            *,
            deadline: float | None = None,
        ) -> T:
            self.calls += 1
            await asyncio.Event().wait()
            raise AssertionError("The blocked operation should be cancelled on shutdown")

    database_url = f"sqlite://{(tmp_path / 'interrupted.sqlite3').as_posix()}"
    blocked = BlockedProvider()
    with TestClient(create_replay_app(provider=blocked, database_url=database_url)) as client:
        accepted = client.post("/api/v1/sessions", json=CREATE).json()
        for _ in range(100):
            if blocked.calls:
                break
            time.sleep(0.01)
        assert blocked.calls == 1
        assert (
            client.get(f"/api/v1/sessions/{accepted['session_id']}").json()["outcome"] == "running"
        )

    provider = CountingProvider()
    with TestClient(create_replay_app(provider=provider, database_url=database_url)) as client:
        session_id = accepted["session_id"]
        interrupted = client.get(f"/api/v1/sessions/{session_id}").json()
        assert interrupted["outcome"] == "failed"
        assert interrupted["retryable"] is True
        assert [error["code"] for error in interrupted["errors"]] == ["search_interrupted"]
        assert provider.calls == 0
        retry = {
            "request_id": "manual-retry",
            "expected_revision": interrupted["revision"],
            "action": "retry",
        }
        assert client.post(f"/api/v1/sessions/{session_id}/resume", json=retry).status_code == 202
        waiting = settled(client, session_id)
        assert waiting["outcome"] == "paused"
        assert waiting["profile"]["target_directions"] == CREATE["target_directions"]
        assert waiting["profile"]["preferences"]["location"] == "Hong Kong"
        repeat = client.post(f"/api/v1/sessions/{session_id}/resume", json=retry)
        assert repeat.json()["revision"] == waiting["revision"]


def test_interrupted_answer_preserves_accepted_input_before_checkpoint_commit(
    tmp_path: Path,
) -> None:
    class BlockedInterpretation(CountingProvider):
        blocked = False

        async def structured[T: BaseModel](
            self,
            schema: type[T],
            messages: list[dict[str, str]],
            *,
            deadline: float | None = None,
        ) -> T:
            if schema.__name__ == "AnswerInterpretation":
                self.blocked = True
                await asyncio.Event().wait()
                raise AssertionError("Interpretation should be cancelled on shutdown")
            return await super().structured(schema, messages, deadline=deadline)

    database_url = f"sqlite://{(tmp_path / 'interrupted-answer.sqlite3').as_posix()}"
    provider = BlockedInterpretation()
    with TestClient(create_replay_app(provider=provider, database_url=database_url)) as client:
        session_id = client.post("/api/v1/sessions", json=CREATE).json()["session_id"]
        waiting = settled(client, session_id)
        accepted = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "accepted-answer",
                "expected_revision": waiting["revision"],
                "action": "edit_conditions",
                "message": "location: Shenzhen",
                "profile_updates": {"projects": ["  Supplied project ， "]},
            },
        )
        assert accepted.status_code == 202
        for _ in range(100):
            if provider.blocked:
                break
            time.sleep(0.01)
        assert provider.blocked

    provider_after_restart = CountingProvider()
    with TestClient(
        create_replay_app(provider=provider_after_restart, database_url=database_url)
    ) as client:
        interrupted = client.get(f"/api/v1/sessions/{session_id}").json()
        assert interrupted["outcome"] == "failed"
        assert provider_after_restart.calls == 0
        response = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "retry-answer",
                "expected_revision": interrupted["revision"],
                "action": "retry",
            },
        )
        assert response.status_code == 202
        recovered = settled(client, session_id)
        assert recovered["profile"]["preferences"]["location"] == "Shenzhen"
        assert recovered["profile"]["projects"] == ["Supplied project ，"]
        assert [message["text"] for message in recovered["conversation"]].count(
            "location: Shenzhen"
        ) == 1


def test_delete_removes_all_threads_and_session_drafts_but_preserves_saved_jobs(
    tmp_path: Path,
) -> None:
    database = tmp_path / "deletion.sqlite3"
    database_url = f"sqlite://{database.as_posix()}"
    with TestClient(create_replay_app(database_url=database_url)) as client:
        client.put(
            "/api/v1/workspace/draft",
            json={"request_id": "workspace", "expected_revision": 0, "data": RAW_DRAFT},
        )
        session_id = client.post("/api/v1/sessions", json=CREATE).json()["session_id"]
        waiting = settled(client, session_id)
        client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "confirm",
                "expected_revision": waiting["revision"],
                "action": "confirm_search",
            },
        )
        completed = settled(client, session_id)
        expected = completed["recommendation"]["jobs"][0]
        job_id = expected["job"]["job_id"]
        invalid = client.put(
            f"/api/v1/saved-jobs/{job_id}",
            json={"session_id": session_id, "expected_revision": completed["revision"] - 1},
        )
        assert invalid.status_code == 409
        assert invalid.json()["detail"]["code"] == "search_changed"
        saved = client.put(
            f"/api/v1/saved-jobs/{job_id}",
            json={"session_id": session_id, "expected_revision": completed["revision"]},
        )
        assert saved.json() == expected
        edited = client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "edit",
                "expected_revision": completed["revision"],
                "action": "edit_conditions",
            },
        )
        assert edited.status_code == 202
        second_wait = settled(client, session_id)
        client.put(
            f"/api/v1/sessions/{session_id}/drafts/{second_wait['revision']}/summary",
            json={
                "request_id": "draft",
                "expected_revision": 0,
                "data": summary_draft(second_wait["profile"]),
            },
        )
        assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204
        assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204
        assert client.get("/api/v1/sessions").json()["items"] == []
        assert client.get("/api/v1/saved-jobs").json()["items"] == [expected]
        assert client.get("/api/v1/workspace/draft").json()["data"] == RAW_DRAFT

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT thread_id FROM checkpoints").fetchall() == []
        assert connection.execute("SELECT thread_id FROM writes").fetchall() == []
        assert connection.execute("SELECT session_id FROM workspace_sessions").fetchall() == []
        assert (
            connection.execute(
                "SELECT scope FROM workspace_drafts WHERE session_id IS NOT NULL"
            ).fetchall()
            == []
        )
    with TestClient(create_replay_app(database_url=database_url)) as client:
        repeated = client.post("/api/v1/sessions", json=CREATE)
        assert repeated.status_code == 404
        assert repeated.json()["detail"]["code"] == "search_not_found"
        assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204
        assert client.get("/api/v1/saved-jobs").json()["items"] == [expected]
        assert client.delete(f"/api/v1/saved-jobs/{job_id}").status_code == 204
        assert client.get("/api/v1/saved-jobs").json()["items"] == []


def test_draft_conflicts_idempotency_shape_validation_and_scope_isolation() -> None:
    with TestClient(create_replay_app()) as client:
        payload = {"request_id": "draft-1", "expected_revision": 0, "data": RAW_DRAFT}
        first = client.put("/api/v1/workspace/draft", json=payload)
        assert first.status_code == 200
        assert client.put("/api/v1/workspace/draft", json=payload).json() == first.json()
        changed = RAW_DRAFT | {"directions": " Product Design，  "}
        same_id = client.put("/api/v1/workspace/draft", json=payload | {"data": changed})
        assert same_id.status_code == 409
        assert same_id.json()["detail"]["code"] == "request_conflict"
        stale = client.put("/api/v1/workspace/draft", json=payload | {"request_id": "stale"})
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "draft_conflict"
        assert client.get("/api/v1/workspace/draft").json()["data"] == RAW_DRAFT
        malformed = client.put(
            "/api/v1/workspace/draft",
            json={
                "request_id": "bad",
                "expected_revision": 1,
                "data": RAW_DRAFT | {"arbitrary": "unexpected"},
            },
        )
        assert malformed.status_code == 422
        second = client.put(
            "/api/v1/workspace/draft",
            json={"request_id": "draft-2", "expected_revision": 1, "data": changed},
        )
        assert second.json()["data"] == changed
        assert second.json()["revision"] == 2
        lost_response_retry = client.put("/api/v1/workspace/draft", json=payload)
        assert lost_response_retry.status_code == 409
        assert lost_response_retry.json()["detail"]["code"] == "draft_conflict"
        assert client.get("/api/v1/workspace/draft").json() == second.json()
        sessions = [
            client.post(
                "/api/v1/sessions", json=CREATE | {"request_id": f"session-{index}"}
            ).json()["session_id"]
            for index in range(2)
        ]
        for session_id in sessions:
            settled(client, session_id)
        raw_answers = {
            "values": {"preferences.location": "  深圳，  "},
            "skipped": [],
            "message": "未提交",
        }
        saved = client.put(
            f"/api/v1/sessions/{sessions[0]}/drafts/1/clarification",
            json={"request_id": "answer-draft", "expected_revision": 0, "data": raw_answers},
        )
        assert saved.json()["data"] == raw_answers
        assert (
            client.get(f"/api/v1/sessions/{sessions[1]}/drafts/1/clarification").json()["data"]
            == {}
        )
        assert (
            client.get(f"/api/v1/sessions/{sessions[0]}/drafts/2/clarification").status_code == 409
        )
        assert client.get(f"/api/v1/sessions/{sessions[0]}/drafts/1/summary").json()["data"] == {}
        assert client.get("/api/v1/workspace/draft").json()["data"] == changed


def test_history_pagination_order_changes_only_after_accepted_user_operations() -> None:
    with TestClient(create_replay_app()) as client:
        ids = [
            client.post(
                "/api/v1/sessions", json=CREATE | {"request_id": f"history-{index}"}
            ).json()["session_id"]
            for index in range(3)
        ]
        waiting = settled(client, ids[0])
        for session_id in ids[1:]:
            settled(client, session_id)
        page = client.get("/api/v1/sessions?limit=2").json()
        assert [item["session_id"] for item in page["items"]] == [ids[2], ids[1]]
        other = client.get(
            "/api/v1/sessions", params={"cursor": page["next_cursor"], "limit": 2}
        ).json()
        assert [item["session_id"] for item in other["items"]] == [ids[0]]
        assert other["next_cursor"] is None
        client.get(f"/api/v1/sessions/{ids[0]}")
        assert client.get("/api/v1/sessions?limit=2").json() == page
        accepted = client.post(
            f"/api/v1/sessions/{ids[0]}/resume",
            json={
                "request_id": "latest",
                "expected_revision": waiting["revision"],
                "action": "edit_conditions",
            },
        )
        assert accepted.status_code == 202
        latest = client.get("/api/v1/sessions").json()["items"]
        assert [item["session_id"] for item in latest] == [ids[0], ids[2], ids[1]]
        settled(client, ids[0])
        assert (
            client.get("/api/v1/sessions").json()["items"][0]["updated_at"]
            == latest[0]["updated_at"]
        )
        assert client.get("/api/v1/sessions?cursor=bad").status_code == 422


def test_pending_checkpoint_deletion_is_completed_on_restart(tmp_path: Path) -> None:
    database = tmp_path / "pending-delete.sqlite3"
    database_url = f"sqlite://{database.as_posix()}"
    application = create_replay_app(database_url=database_url)
    with TestClient(application, raise_server_exceptions=False) as client:
        session_id = client.post("/api/v1/sessions", json=CREATE).json()["session_id"]
        settled(client, session_id)

        async def unavailable_checkpoint_delete(thread_id: str) -> None:
            raise OSError("Synthetic cleanup failure")

        application.state.checkpointer.adelete_thread = unavailable_checkpoint_delete
        assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 500
        assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404
        assert client.get("/api/v1/sessions").json()["items"] == []
    with TestClient(create_replay_app(database_url=database_url)) as client:
        assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404
        assert client.post("/api/v1/sessions", json=CREATE).status_code == 404
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT thread_id FROM checkpoints").fetchall() == []
        assert connection.execute("SELECT thread_id FROM writes").fetchall() == []
        assert connection.execute("SELECT session_id FROM workspace_sessions").fetchall() == []


def test_failed_deletion_marker_commit_preserves_readable_state_and_can_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_replay_app()
    with TestClient(application, raise_server_exceptions=False) as client:
        session_id = client.post("/api/v1/sessions", json=CREATE).json()["session_id"]
        waiting = settled(client, session_id)
        original_persist = application.state.sessions._persist

        async def reject_deletion_marker(
            record: _Session, *, connection: BaseDBAsyncClient | None = None
        ) -> None:
            if record.deleted:
                raise OSError("Synthetic marker commit failure")
            await original_persist(record, connection=connection)

        monkeypatch.setattr(application.state.sessions, "_persist", reject_deletion_marker)
        assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 500
        assert client.get(f"/api/v1/sessions/{session_id}").json() == waiting
        assert [item["session_id"] for item in client.get("/api/v1/sessions").json()["items"]] == [
            session_id
        ]
        monkeypatch.setattr(application.state.sessions, "_persist", original_persist)
        assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204
        assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404


def test_saved_job_ids_with_encoded_path_characters_roundtrip_exactly() -> None:
    job_id = "source/role 42?中文"
    item = RecommendationItem(job=posting(job_id=job_id))

    class RecommendedGraph(ControlledGraph):
        async def ainvoke(self, data: Any, config: dict[str, Any]) -> dict[str, Any]:
            state = await super().ainvoke(data, config)
            state["recommendation"] = RecommendationResult(
                session_id=state["session_id"], generated_at=NOW, jobs=[item]
            )
            return state

    graph = RecommendedGraph()
    graph.release.set()
    with TestClient(create_app(graph=graph)) as client:
        session_id = client.post("/api/v1/sessions", json=CREATE).json()["session_id"]
        completed = settled(client, session_id)
        path = f"/api/v1/saved-jobs/{quote(job_id, safe='')}"
        saved = client.put(
            path, json={"session_id": session_id, "expected_revision": completed["revision"]}
        )
        assert saved.status_code == 200
        assert saved.json() == completed["recommendation"]["jobs"][0]
        assert client.get("/api/v1/saved-jobs").json()["items"] == [saved.json()]
        assert client.delete(path).status_code == 204
        assert client.get("/api/v1/saved-jobs").json()["items"] == []
