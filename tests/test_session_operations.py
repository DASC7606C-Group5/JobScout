"""Operation tests use a controllable graph, with no network or provider."""

import asyncio
from typing import Any

import pytest

from jobscout.schemas.conversation import QuestionOption
from jobscout.schemas.search import ClarificationMessage
from jobscout.schemas.session import SessionCreateRequest, SessionResumeRequest
from jobscout.services.notice_service import make_notice
from jobscout.services.session_service import SessionOperationError, SessionService


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


def test_create_is_accepted_and_idempotent() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        manager = SessionService(graph, Memory())
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
        await manager.close()

    asyncio.run(check())


def test_stale_and_concurrent_operations_are_rejected() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        manager = SessionService(graph, Memory())
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
            assert (await manager.get(session.session_id)).revision == completed.revision
        finally:
            await manager.close()

    asyncio.run(check())


def test_delete_cancels_and_never_restores_session() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        memory = Memory()
        manager = SessionService(graph, memory)
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
        await manager.close()

    asyncio.run(check())


def test_sessions_are_isolated_and_completed_edit_is_idempotent() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        graph.release.set()
        manager = SessionService(graph, Memory())
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
        await manager.close()

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
        manager = SessionService(graph, Memory())
        session = await manager.create(create_payload())
        await graph.started.wait()
        await manager.delete(session.session_id)
        with pytest.raises(SessionOperationError) as error:
            await manager.get(session.session_id)
        assert error.value.status == 404
        assert session.session_id not in manager.sessions
        await manager.close()

    asyncio.run(check())


def test_question_controls_and_confirmation_are_validated_before_acceptance() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        manager = SessionService(graph, Memory())
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
        await manager.close()

    asyncio.run(check())


def test_get_does_not_restore_a_previous_revision_while_editing() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        graph.release.set()
        manager = SessionService(graph, Memory())
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
        await manager.close()

    asyncio.run(check())


def test_unknown_question_and_privileged_field_rejected() -> None:
    async def check() -> None:
        graph = ControlledGraph()
        graph.release.set()
        manager = SessionService(graph, Memory())
        session = await manager.create(create_payload())
        await asyncio.sleep(0)
        for changes in (
            {"skipped_question_ids": ["unknown"]},
            {"profile_updates": {"profile_id": "bad"}},
        ):
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
        await manager.close()

    asyncio.run(check())
