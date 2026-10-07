"""Push updates preserve committed public state without tying work to the connection."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from jobscout.api.sessions import router, session_events
from jobscout.models import LoginSession, User
from jobscout.schemas.execution import SearchProgress
from jobscout.schemas.session import SessionStopRequest
from jobscout.services.auth_service import Identity
from jobscout.services.session_service import SessionOperationError, SessionService, _Session
from tests.auth_client import AuthenticatedClient as TestClient
from tests.test_search_stop import ProgressGraph
from tests.test_session_operations import Memory, close_manager, create_payload, manager_for


@pytest.mark.parametrize("reason", ["logout", "expiry"])
def test_authentication_ends_an_idle_event_stream_without_stopping_the_operation(
    reason: str,
) -> None:
    async def scenario() -> None:
        graph = ProgressGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            identity = Identity(
                User(user_id="workflow-owner", username="student", password_hash="synthetic"),
                LoginSession(
                    token_hash="synthetic",
                    owner_id="workflow-owner",
                    csrf_token="synthetic",
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
            )
            app = FastAPI()
            app.state.sessions = manager
            request = Request({"type": "http", "app": app, "state": {"identity": identity}})
            response = await session_events(request, created.session_id)
            iterator = aiter(response.body_iterator)
            await anext(iterator)
            await anext(iterator)
            if reason == "expiry":
                identity.session.expires_at = datetime.now(UTC) + timedelta(milliseconds=20)
            pending = asyncio.ensure_future(anext(iterator))
            await asyncio.sleep(0)
            if reason == "logout":
                identity.revoked.set()
            # Expiry can emit the final heartbeat before ending the stream.
            try:
                await asyncio.wait_for(pending, 1)
            except StopAsyncIteration:
                pass
            else:
                with pytest.raises(StopAsyncIteration):
                    await asyncio.wait_for(anext(iterator), 1)
            assert created.session_id not in manager.subscribers
            assert not graph.cancelled.is_set()
            task = manager.sessions[created.session_id].task
            assert task is not None and not task.done()
        finally:
            await close_manager(manager)

    asyncio.run(scenario())


def test_stream_pushes_progress_stop_and_completion_and_reconnects_to_current_state() -> None:
    async def scenario() -> None:
        graph = ProgressGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            first = await manager.subscribe(created.session_id)
            initial = await first.get()
            assert initial is not None and initial.progress.sequence == 1
            second = await manager.subscribe(created.session_id)
            await second.get()
            await graph.callback(
                {
                    "run_id": graph.run_id,
                    "progress": {
                        "sequence": 2,
                        "activity": [
                            {
                                "sequence": 2,
                                "job_id": "candidate-2",
                                "title": "前端工程师\nNew role",
                                "company": "Example",
                                "location": "Hong Kong",
                                "status": "reviewing",
                            }
                        ],
                    },
                }
            )
            updated = await asyncio.wait_for(first.get(), 1)
            assert updated is not None
            assert updated.progress.activity[0].job_id == "candidate-2"
            assert updated.progress.activity[0].status == "reviewing"
            assert await second.get() == updated
            assert initial.progress.activity == []
            manager.unsubscribe(created.session_id, first)
            assert not graph.cancelled.is_set()
            stopped = await manager.stop(
                created.session_id,
                SessionStopRequest(
                    request_id="stop-events", expected_revision=1, run_id=graph.run_id
                ),
            )
            pushed_stop = await asyncio.wait_for(second.get(), 1)
            assert pushed_stop == stopped
            assert pushed_stop.progress.retrieval_stopped
            reconnected = await manager.subscribe(created.session_id)
            assert await reconnected.get() == stopped
            graph.release.set()
            task = manager.sessions[created.session_id].task
            assert task is not None
            await task
            final = await asyncio.wait_for(second.get(), 1)
            assert final is not None and final.outcome == "completed"
            assert await reconnected.get() == final
            assert final.recommendation is not None
            assert [row.job.job_id for row in final.recommendation.jobs] == [
                "complete",
                "unfinished",
            ]
        finally:
            await close_manager(manager)

    asyncio.run(scenario())


def test_slow_subscriber_recovers_latest_state_and_delete_closes_all_listeners() -> None:
    async def scenario() -> None:
        graph = ProgressGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            queue = await manager.subscribe(created.session_id)
            for sequence in range(2, 40):
                await graph.callback({"run_id": graph.run_id, "progress": {"sequence": sequence}})
            snapshots = []
            while not queue.empty():
                snapshots.append(queue.get_nowait())
            latest = snapshots[-1]
            assert latest is not None and latest.progress.sequence == 39
            assert len(snapshots) <= queue.maxsize
            await manager.delete(created.session_id)
            assert await asyncio.wait_for(queue.get(), 1) is None
            with pytest.raises(SessionOperationError) as error:
                await manager.subscribe(created.session_id)
            assert error.value.code == "search_not_found"
            manager.unsubscribe(created.session_id, queue)
            assert created.session_id not in manager.subscribers
        finally:
            await close_manager(manager)

    asyncio.run(scenario())


def test_uncommitted_or_stale_progress_is_not_pushed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        graph = ProgressGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            queue = await manager.subscribe(created.session_id)
            await queue.get()
            await graph.callback({"run_id": "old-run", "progress": {"sequence": 100}})
            await graph.callback({"run_id": graph.run_id, "progress": {"sequence": 1}})

            async def reject(*args: Any, **kwargs: Any) -> None:
                raise RuntimeError("storage unavailable")

            with monkeypatch.context() as patch:
                patch.setattr(manager, "_persist", reject)
                with pytest.raises(RuntimeError, match="storage unavailable"):
                    await graph.callback({"run_id": graph.run_id, "progress": {"sequence": 2}})
            assert queue.empty()
            reconnected = await manager.subscribe(created.session_id)
            snapshot = await reconnected.get()
            assert snapshot is not None and snapshot.progress.sequence == 1
        finally:
            await close_manager(manager)

    asyncio.run(scenario())


def test_sse_disconnect_releases_subscription_without_cancelling_search() -> None:
    async def scenario() -> None:
        graph = ProgressGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            app = FastAPI()
            app.state.sessions = manager
            request = Request({"type": "http", "app": app})
            response = await session_events(request, created.session_id)
            iterator = aiter(response.body_iterator)
            await anext(iterator)
            frame = await anext(iterator)
            assert isinstance(frame, str)
            data = json.loads(frame.split("data: ", 1)[1])
            assert data["session_id"] == created.session_id
            pending = asyncio.ensure_future(anext(iterator))
            await asyncio.sleep(0)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert created.session_id not in manager.subscribers
            assert not graph.cancelled.is_set()
            task = manager.sessions[created.session_id].task
            assert task is not None and not task.done()
        finally:
            await close_manager(manager)

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["paused", "completed", "failed"])
def test_sse_http_returns_terminal_snapshot_and_public_missing_error(outcome: str) -> None:
    manager = SessionService(None, None)
    manager.sessions["existing"] = _Session(
        "existing", {"progress": SearchProgress(sequence=7)}, outcome=outcome
    )
    app = FastAPI()
    app.state.sessions = manager
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/v1/sessions/existing/events")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        data = json.loads(response.text.split("data: ", 1)[1])
        assert data["session_id"] == "existing"
        assert data["outcome"] == outcome
        assert data["progress"]["sequence"] == 7
        assert not manager.subscribers
        missing = client.get("/api/v1/sessions/missing/events")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "search_not_found"
