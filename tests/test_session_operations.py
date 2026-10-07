"""Operation tests use a controllable graph, with no network or provider."""

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError
from tortoise import Tortoise

from jobscout.database import tortoise_config
from jobscout.schemas.conversation import QuestionOption
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.search import ClarificationMessage
from jobscout.schemas.session import SessionCreateRequest, SessionResumeRequest, SessionStopRequest
from jobscout.services.notice_service import make_notice
from jobscout.services.session_service import SessionOperationError, SessionService, _Session


class Snapshot:
    def __init__(self, values: dict[str, Any], waiting: bool = False) -> None:
        self.values = values
        self.next = ("wait",) if waiting else ()


class ControlledGraph:
    def __init__(self) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.states: dict[str, dict[str, Any]] = {}
        self.cleaned: list[str] = []

    async def cleanup_session(self, session_id: str) -> None:
        self.cleaned.append(session_id)

    async def ainvoke(self, data: Any, config: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        session_id = config["configurable"]["thread_id"]
        self.started.set()
        await self.release.wait()
        state = {"session_id": session_id, "current_stage": "completed"}
        self.states[session_id] = state
        return state

    async def aget_state(self, config: dict[str, Any]) -> Snapshot:
        return Snapshot(self.states.get(config["configurable"]["thread_id"], {}))


class Memory:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def adelete_thread(self, session_id: str) -> None:
        self.deleted.append(session_id)


def create_payload(request_id: str = "create-1") -> SessionCreateRequest:
    return SessionCreateRequest(request_id=request_id, description="Synthetic SQL student")


async def manager_for(graph: ControlledGraph, memory: Memory) -> SessionService:
    await Tortoise.init(config=tortoise_config("sqlite://:memory:"))
    await Tortoise.generate_schemas(safe=True)
    return SessionService(graph, memory)


async def close_manager(manager: SessionService) -> None:
    await manager.close()
    await Tortoise.close_connections()


def test_create_is_accepted_and_idempotent() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        manager = await manager_for(graph, Memory())
        first = await manager.create(create_payload())
        assert first.outcome == "running"
        same = await manager.create(create_payload())
        assert same.session_id == first.session_id
        await graph.started.wait()
        assert graph.calls == 1
        with pytest.raises(SessionOperationError) as error:
            await manager.create(SessionCreateRequest(request_id="create-1", description="changed"))
        assert error.value.status == 409
        graph.release.set()
        await asyncio.sleep(0)
        assert (await manager.get(first.session_id)).outcome == "completed"
        await close_manager(manager)

    asyncio.run(check())


def test_stop_preserves_the_running_task_and_accepts_later_review_progress() -> None:
    class ReviewingGraph(ControlledGraph):
        def __init__(self) -> None:
            super().__init__()
            self.stopped = asyncio.Event()

        async def ainvoke(self, data: Any, config: dict[str, Any]) -> dict[str, Any]:
            settings = config["configurable"]
            session_id = settings["thread_id"]
            run_id = settings["run_id"]
            await settings["on_progress"](
                {"run_id": run_id, "current_stage": "search", "progress": {"sequence": 1}}
            )
            self.started.set()
            await settings["stop_event"].wait()
            await settings["on_progress"](
                {
                    "run_id": run_id,
                    "current_stage": "review",
                    "stop_reason": None,
                    "progress": {"sequence": 2, "analyzed_count": 2},
                }
            )
            self.stopped.set()
            await self.release.wait()
            state = {
                "session_id": session_id,
                "run_id": run_id,
                "current_stage": "completed",
                "stop_reason": "user_stopped",
                "progress_seq": 3,
                "progress": {"sequence": 3, "analyzed_count": 3, "retrieval_stopped": True},
            }
            self.states[session_id] = state
            return state

    async def check() -> None:
        graph = ReviewingGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            running = await manager.get(created.session_id)
            assert running.run_id is not None
            payload = SessionStopRequest(
                request_id="stop-1", expected_revision=running.revision, run_id=running.run_id
            )
            stopped = await manager.stop(created.session_id, payload)
            assert stopped.outcome == "running"
            assert stopped.current_stage == "review"
            assert stopped.progress.retrieval_stopped
            assert (await manager.stop(created.session_id, payload)).run_id == running.run_id
            await asyncio.wait_for(graph.stopped.wait(), timeout=1)
            reviewing = await manager.get(created.session_id)
            assert reviewing.outcome == "running"
            assert reviewing.progress.analyzed_count == 2
            assert reviewing.progress.retrieval_stopped
            assert reviewing.stop_reason == "user_stopped"
            graph.release.set()
            task = manager.sessions[created.session_id].task
            assert task is not None
            await task
            completed = await manager.get(created.session_id)
            assert completed.outcome == "completed"
            assert completed.progress.analyzed_count == 3
            assert completed.stop_reason == "user_stopped"
        finally:
            await close_manager(manager)

    asyncio.run(check())


def test_stale_and_concurrent_operations_are_rejected() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        manager = await manager_for(graph, Memory())
        session = await manager.create(create_payload())
        try:
            with pytest.raises(SessionOperationError) as error:
                await manager.resume(
                    session.session_id,
                    SessionResumeRequest(
                        request_id="concurrent",
                        expected_revision=session.revision,
                    ),
                )
            assert error.value.status == 409
            assert error.value.code == "operation_in_progress"
            await graph.started.wait()
            graph.release.set()
            await asyncio.sleep(0)
            completed = await manager.get(session.session_id)
            assert completed.outcome == "completed"
            with pytest.raises(SessionOperationError) as error:
                await manager.resume(
                    session.session_id,
                    SessionResumeRequest(
                        request_id="stale",
                        expected_revision=completed.revision - 1,
                        action="edit_conditions",
                    ),
                )
            assert error.value.status == 409
            assert error.value.code == "search_changed"
            assert (await manager.get(session.session_id)).revision == completed.revision
        finally:
            await close_manager(manager)

    asyncio.run(check())


@pytest.mark.parametrize("late_failure", [False, True])
def test_edit_ignores_cancelled_run_progress_and_completion(late_failure: bool) -> None:
    profile = UserProfile(profile_id="original-profile", skills=["React"])

    class LateGraph(ControlledGraph):
        async def ainvoke(self, data: Any, config: dict[str, Any]) -> dict[str, Any]:
            settings = config["configurable"]
            thread_id = settings["thread_id"]
            if "command" in data:
                state = {**data, "current_stage": "confirm"}
                self.states[thread_id] = state
                return state
            state = {
                **data,
                "run_id": settings["run_id"],
                "profile": profile,
                "current_stage": "search",
            }
            self.states[thread_id] = state
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                await settings["on_progress"](
                    {
                        "run_id": settings["run_id"],
                        "progress_seq": 100,
                        "progress": {"sequence": 100},
                        "current_stage": "review",
                    }
                )
                if late_failure:
                    raise RuntimeError("Late provider failure") from None
                return {
                    **state,
                    "current_stage": "completed",
                    "profile": profile.model_copy(update={"skills": ["Obsolete result"]}),
                }
            raise AssertionError("The original run should have been cancelled")

        async def aget_state(self, config: dict[str, Any]) -> Snapshot:
            state = self.states.get(config["configurable"]["thread_id"], {})
            return Snapshot(state, waiting=state.get("current_stage") == "confirm")

    async def check() -> None:
        graph = LateGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            running = await manager.get(created.session_id)
            edited = await manager.resume(
                created.session_id,
                SessionResumeRequest(
                    request_id="interrupt-late-run",
                    expected_revision=running.revision,
                    action="edit_conditions",
                ),
            )
            task = manager.sessions[created.session_id].task
            assert task is not None
            await asyncio.wait_for(task, timeout=1)
            current = await manager.get(created.session_id)
            assert current.session_id == created.session_id
            assert current.revision == edited.revision == running.revision + 1
            assert current.outcome == "paused"
            assert current.current_stage == "confirm"
            assert current.profile == profile
            assert current.run_id is None
            assert current.progress.sequence == 0
            assert current.errors == []
        finally:
            await close_manager(manager)

    asyncio.run(check())


def test_failed_edit_persistence_keeps_the_active_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        graph = ControlledGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            record = manager.sessions[created.session_id]
            record.state.update(
                run_id=record.active_run_id,
                profile=UserProfile(profile_id="preserved", skills=["SQL"]),
            )
            before = await manager.get(created.session_id)
            old_task = record.task
            old_thread = record.thread_id
            payload = SessionResumeRequest(
                request_id="failed-edit",
                expected_revision=created.revision,
                action="edit_conditions",
            )

            failure = OSError("Storage unavailable")

            async def fail_persist(current: _Session, **kwargs: Any) -> None:
                raise failure

            with monkeypatch.context() as patch:
                patch.setattr(manager, "_persist", fail_persist)
                with pytest.raises(OSError) as raised:
                    await manager.resume(created.session_id, payload)
                assert raised.value is failure
            assert await manager.get(created.session_id) == before
            assert record.task is old_task
            assert old_task is not None and not old_task.done()
            assert record.thread_id == old_thread
            assert payload.request_id not in record.requests
        finally:
            await close_manager(manager)

    asyncio.run(check())


def test_delete_cancels_and_never_restores_session() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        memory = Memory()
        manager = await manager_for(graph, memory)
        session = await manager.create(create_payload())
        await graph.started.wait()
        await manager.delete(session.session_id)
        graph.release.set()
        await asyncio.sleep(0)
        with pytest.raises(SessionOperationError) as error:
            await manager.get(session.session_id)
        assert error.value.status == 404
        assert memory.deleted == [session.session_id]
        assert graph.cleaned == [session.session_id]
        with pytest.raises(SessionOperationError) as repeated:
            await manager.create(create_payload())
        assert repeated.value.status == 404
        await close_manager(manager)

    asyncio.run(check())


def test_sessions_are_isolated_and_completed_edit_is_idempotent() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        graph.release.set()
        manager = await manager_for(graph, Memory())
        first = await manager.create(create_payload())
        second = await manager.create(create_payload("create-2"))
        await asyncio.sleep(0)
        payload = SessionResumeRequest(
            request_id="edit-1",
            expected_revision=1,
            action="edit_conditions",
        )
        accepted = await manager.resume(first.session_id, payload)
        repeat = await manager.resume(first.session_id, payload)
        assert accepted.revision == repeat.revision == 2
        assert (await manager.get(second.session_id)).revision == 1
        await close_manager(manager)

    asyncio.run(check())


def test_late_result_after_cancellation_cannot_restore_deleted_state() -> None:
    class LateGraph(ControlledGraph):
        async def ainvoke(self, data: Any, config: dict[str, Any]) -> dict[str, Any]:
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                return {"session_id": data["session_id"], "current_stage": "completed"}
            return {}

    async def check() -> None:
        graph = LateGraph()
        manager = await manager_for(graph, Memory())
        session = await manager.create(create_payload())
        await graph.started.wait()
        await manager.delete(session.session_id)
        with pytest.raises(SessionOperationError) as error:
            await manager.get(session.session_id)
        assert error.value.status == 404
        assert session.session_id not in manager.sessions
        await close_manager(manager)

    asyncio.run(check())


def test_question_controls_and_confirmation_are_validated_before_acceptance() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        manager = await manager_for(graph, Memory())
        session = await manager.create(create_payload())
        await graph.started.wait()
        graph.release.set()
        await asyncio.sleep(0)
        record = manager.sessions[session.session_id]
        record.outcome = "paused"
        record.state["clarification_questions"] = [
            ClarificationMessage(
                question_id="required",
                question="Choose a role",
                field="target_directions",
                reason="",
                required=True,
                control_type="single_choice",
                options=[QuestionOption(id="one", label="One")],
            )
        ]
        invalid: list[dict[str, Any]] = [
            {"skipped_question_ids": ["required"]},
            {"answers": [{"question_id": "required", "value": "missing-option"}]},
            {"answers": [{"question_id": "required", "value": ["one"]}]},
            {
                "answers": [{"question_id": "required", "value": "one"}],
                "skipped_question_ids": ["required"],
            },
            {"profile_updates": {"skills": "not-a-list"}},
            {"profile_updates": {"preferences.location_unrestricted": "yes"}},
        ]
        for index, changes in enumerate(invalid):
            if "profile_updates" in changes:
                with pytest.raises(ValidationError) as invalid_patch:
                    SessionResumeRequest.model_validate(
                        {"request_id": f"invalid-{index}", "expected_revision": 1, **changes}
                    )
                assert invalid_patch.value.errors()[0]["loc"][0] == "profile_updates"
                assert record.revision == 1
                continue
            payload = SessionResumeRequest.model_validate(
                {
                    "request_id": f"invalid-{index}",
                    "expected_revision": 1,
                    **changes,
                }
            )
            with pytest.raises(SessionOperationError) as error:
                await manager.resume(session.session_id, payload)
            assert error.value.status == 422
            assert record.revision == 1
        with pytest.raises(SessionOperationError) as error:
            await manager.resume(
                session.session_id,
                SessionResumeRequest(
                    request_id="unconfirmed",
                    expected_revision=1,
                    action="confirm_search",
                ),
            )
        assert error.value.status == 409
        await close_manager(manager)

    asyncio.run(check())


def test_get_does_not_restore_a_previous_revision_while_editing() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        graph.release.set()
        manager = await manager_for(graph, Memory())
        session = await manager.create(create_payload())
        await asyncio.sleep(0)
        record = manager.sessions[session.session_id]
        record.state["recommendation"] = None
        graph.states[session.session_id] = {
            "session_id": session.session_id,
            "current_stage": "completed",
            "revision": 1,
            "notices": [make_notice("coverage_limited", source="jobsdb")],
        }
        graph.release.clear()
        await manager.resume(
            session.session_id,
            SessionResumeRequest(
                request_id="edit-new",
                expected_revision=1,
                action="edit_conditions",
            ),
        )
        snapshot = await manager.get(session.session_id)
        assert snapshot.revision == 2
        assert snapshot.recommendation is None
        assert not any(notice.source == "jobsdb" for notice in snapshot.notices)
        await close_manager(manager)

    asyncio.run(check())


def test_unknown_question_and_privileged_field_rejected() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        graph.release.set()
        manager = await manager_for(graph, Memory())
        session = await manager.create(create_payload())
        await asyncio.sleep(0)
        for changes in (
            {"skipped_question_ids": ["unknown"]},
            {"profile_updates": {"profile_id": "bad"}},
        ):
            if "profile_updates" in changes:
                with pytest.raises(ValidationError) as invalid_patch:
                    SessionResumeRequest.model_validate(
                        {"request_id": "invalid", "expected_revision": 1, **changes}
                    )
                assert invalid_patch.value.errors()[0]["type"] == "extra_forbidden"
                continue
            payload = SessionResumeRequest.model_validate(
                {
                    "request_id": "invalid",
                    "expected_revision": 1,
                    "action": "edit_conditions",
                    **changes,
                }
            )
            with pytest.raises(SessionOperationError) as error:
                await manager.resume(session.session_id, payload)
            assert error.value.status == 422
        await close_manager(manager)

    asyncio.run(check())
