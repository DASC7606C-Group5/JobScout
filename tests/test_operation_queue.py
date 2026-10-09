"""Durable queue admission, quota settlement, recovery and bounded retention."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import HTTPException
from tortoise import Tortoise

from jobscout.config import get_settings
from jobscout.database import tortoise_config
from jobscout.models import (
    AcceptedRequest,
    DailyUsage,
    LoginSession,
    SearchSession,
    SessionOperation,
)
from jobscout.schemas.session import (
    SessionCancelRequest,
    SessionCreateRequest,
    SessionResponse,
    SessionResumeRequest,
)
from jobscout.services.identity import current_user_id, owner_id
from jobscout.services.llm_service import ModelRouter
from jobscout.services.model_settings_service import ModelSettingsService, OperationModels
from jobscout.services.session_service import SessionOperationError, SessionService
from tests.test_session_operations import ControlledGraph, Memory


class QueueGraph(ControlledGraph):
    def __init__(self) -> None:
        super().__init__()
        self.owners: list[str] = []
        self.active = 0
        self.peak = 0

    async def ainvoke(self, data: Any, config: dict[str, Any]) -> dict[str, Any]:
        self.owners.append(owner_id())
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            return await super().ainvoke(data, config)
        finally:
            self.active -= 1


class QueueModels(ModelSettingsService):
    created = 0
    closed = 0
    invalid = False

    def restore(self, values: dict[str, Any], uses_server: bool) -> OperationModels:
        if self.invalid:
            raise ValueError("Synthetic invalid model settings")
        self.created += 1
        return OperationModels(cast(ModelRouter, self), uses_server)

    async def aclose(self) -> None:
        self.closed += 1


@asynccontextmanager
async def queue_manager(
    **limits: Any,
) -> AsyncIterator[tuple[SessionService, QueueGraph, QueueModels]]:
    settings = get_settings().model_copy(
        update={
            "production": True,
            "llm_semantic_api_key": "synthetic-semantic-key",
            "llm_decision_api_key": "synthetic-decision-key",
            **limits,
        }
    )
    await Tortoise.init(config=tortoise_config("sqlite://:memory:"))
    await Tortoise.generate_schemas()
    graph = QueueGraph()
    models = QueueModels(settings)
    manager = SessionService(
        graph, Memory(), settings=settings, model_settings=models, graph_factory=lambda _: graph
    )
    try:
        yield manager, graph, models
    finally:
        await manager.close()
        await Tortoise.close_connections()


async def submit(manager: SessionService, owner: str, request_id: str = "create") -> Any:
    token = current_user_id.set(owner)
    try:
        return await manager.create(
            SessionCreateRequest(request_id=request_id, description=f"Synthetic applicant {owner}")
        )
    finally:
        current_user_id.reset(token)


async def wait_until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.mark.parametrize("concurrency", [3, 128])
def test_140_simultaneous_submissions_are_durable_fifo_and_owner_isolated(concurrency: int) -> None:
    async def scenario() -> None:
        async with queue_manager(concurrent_total_limit=concurrency) as (manager, graph, models):
            responses = await asyncio.gather(*(submit(manager, f"student-{i}") for i in range(140)))
            assert len({r.operation_id for r in responses}) == 140
            assert await SessionOperation.filter(status="running").count() == concurrency
            assert (
                await SessionOperation.filter(status="queued").count()
                == len(responses) - concurrency
            )
            assert len(manager.tasks) == concurrency and len(manager.sessions) == concurrency
            assert models.created == concurrency
            order = await SessionOperation.all().order_by("id").values_list("owner_id", flat=True)
            usage = await DailyUsage.get(owner_id="__all__", day=models.day())
            assert (usage.operations, usage.reserved) == (concurrency, len(responses) - concurrency)
            queued = await SessionOperation.filter(status="queued").first()
            assert queued is not None
            assert "synthetic" not in queued.encrypted_models
            assert "applicant" not in queued.encrypted_input
            assert (
                json.loads(manager.profile_cipher.decrypt(queued.encrypted_models))["values"][
                    "llm_semantic_api_key"
                ]
                == "synthetic-semantic-key"
            )
            graph.release.set()
            await wait_until(lambda: models.closed == 140 and not manager.tasks)
            assert graph.peak == concurrency
            assert graph.owners == cast(list[str], order)
            assert await SessionOperation.filter(status="succeeded").count() == 140
            assert not await SessionOperation.exclude(encrypted_models="").exists()
            assert (await DailyUsage.get(owner_id="__all__", day=models.day())).operations == 140
            assert len(manager.sessions) <= manager.settings.session_cache_entries
            assert await SearchSession.all().count() == 140

    asyncio.run(scenario())


def test_capacity_idempotency_cancel_retry_and_position_events() -> None:
    async def scenario() -> None:
        async with queue_manager(concurrent_total_limit=1, queue_limit=2) as (
            manager,
            graph,
            models,
        ):
            manager.testing_users.add("connection-test")
            first = await submit(manager, "first")
            second = await submit(manager, "second")
            assert first.outcome == second.outcome == "queued" and models.created == 0
            assert (await submit(manager, "first")).operation_id == first.operation_id
            with pytest.raises(HTTPException) as user_limit:
                await submit(manager, "first", "another")
            assert cast(object, user_limit.value.detail) == {"code": "operation_capacity"}
            with pytest.raises(HTTPException) as queue_limit:
                await submit(manager, "third")
            assert cast(object, queue_limit.value.detail) == {"code": "queue_full"}
            assert queue_limit.value.headers == {"Retry-After": "10"}
            assert not await AcceptedRequest.filter(owner_id="third").exists()
            assert not await DailyUsage.filter(owner_id="third").exists()
            token = current_user_id.set("second")
            try:
                stream = await manager.subscribe(second.session_id)
                extra = await manager.subscribe(second.session_id)
                with pytest.raises(HTTPException) as streams:
                    await manager.subscribe(second.session_id)
                assert cast(object, streams.value.detail) == {"code": "event_stream_capacity"}
                with pytest.raises(SessionOperationError) as foreign:
                    await manager.get(first.session_id)
                assert foreign.value.status == 404
                with pytest.raises(SessionOperationError):
                    await manager.subscribe(first.session_id)
                with pytest.raises(SessionOperationError) as foreign_cancel:
                    await manager.cancel(
                        first.session_id,
                        SessionCancelRequest(
                            request_id="foreign",
                            expected_revision=1,
                            operation_id=first.operation_id,
                        ),
                    )
                assert foreign_cancel.value.status == 404
            finally:
                current_user_id.reset(token)
            token = current_user_id.set("first")
            try:
                cancel = SessionCancelRequest(
                    request_id="cancel", expected_revision=1, operation_id=first.operation_id
                )
                cancelled = await manager.cancel(first.session_id, cancel)
                assert cancelled.outcome == "cancelled" and cancelled.retryable
                assert (
                    await manager.cancel(first.session_id, cancel)
                ).snapshot_version == cancelled.snapshot_version
                assert (await models.usage("first"))["reserved"] == 0
                position = await stream.get()
                assert position is not None and position.queue_position == 1
                assert position.snapshot_version > second.snapshot_version
                assert extra.qsize() == 1
                retry = await manager.resume(
                    first.session_id,
                    SessionResumeRequest(request_id="retry", expected_revision=1, action="retry"),
                )
                assert retry.operation_id != first.operation_id and retry.queue_position == 2
                with pytest.raises(SessionOperationError) as conflict:
                    await manager.create(
                        SessionCreateRequest(request_id="create", description="changed")
                    )
                assert conflict.value.code == "request_conflict"
            finally:
                current_user_id.reset(token)
            manager.testing_users.clear()
            graph.release.set()
            manager.wake.set()
            await wait_until(lambda: models.closed == 2 and not manager.tasks)
            assert graph.owners == ["second", "first"]
            manager.unsubscribe(second.session_id, stream)
            manager.unsubscribe(second.session_id, extra)

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_first", [False, True])
def test_cancel_claim_race_has_exactly_one_quota_settlement(cancel_first: bool) -> None:
    async def scenario() -> None:
        async with queue_manager(concurrent_total_limit=1) as (manager, graph, models):
            manager.testing_users.add("occupied")
            session = await submit(manager, "student")
            # Stop the automatic scanner so both orderings are deterministic.
            assert manager.scheduler is not None
            manager.scheduler.cancel()
            await asyncio.gather(manager.scheduler, return_exceptions=True)
            manager.scheduler = None
            token = current_user_id.set("student")
            try:

                async def claim() -> None:
                    async with manager.lock:
                        manager.testing_users.clear()
                        await manager._dispatch_locked()

                async def cancel() -> Any:
                    return await manager.cancel(
                        session.session_id,
                        SessionCancelRequest(
                            request_id="cancel",
                            expected_revision=1,
                            operation_id=session.operation_id,
                        ),
                    )

                calls = [cancel(), claim()] if cancel_first else [claim(), cancel()]
                results = await asyncio.gather(*calls, return_exceptions=True)
                if cancel_first:
                    assert isinstance(results[0], SessionResponse)
                    assert results[0].outcome == "cancelled"
                else:
                    assert isinstance(results[1], SessionOperationError)
                    assert results[1].code == "operation_already_started"
                usage = await models.usage("student")
                assert (usage["used"], usage["reserved"]) == (0 if cancel_first else 1, 0)
                assert graph.calls <= 1
            finally:
                current_user_id.reset(token)

    asyncio.run(scenario())


@pytest.mark.parametrize("finish", ["expire", "invalid", "cancel", "delete", "execute"])
def test_reservations_belong_to_admission_day_and_release_only_before_start(finish: str) -> None:
    async def scenario() -> None:
        async with queue_manager(concurrent_total_limit=1) as (manager, graph, models):
            models.day = lambda: "2099-01-01"  # type: ignore[method-assign]
            manager.testing_users.add("occupied")
            session = await submit(manager, "student")
            assert (await models.usage("student"))["reserved"] == 1
            models.day = lambda: "2099-01-02"  # type: ignore[method-assign]
            token = current_user_id.set("student")
            try:
                if finish == "cancel":
                    await manager.cancel(
                        session.session_id,
                        SessionCancelRequest(
                            request_id="cancel",
                            expected_revision=1,
                            operation_id=session.operation_id,
                        ),
                    )
                elif finish == "delete":
                    await manager.delete(session.session_id)
                elif finish == "expire":
                    await SessionOperation.filter(operation_id=session.operation_id).update(
                        expires_at=datetime.now(UTC) - timedelta(seconds=1)
                    )
                    async with manager.lock:
                        await manager._cleanup_locked()
                    expired = await manager.get(session.session_id)
                    assert expired.outcome == "failed" and expired.retryable
                    assert expired.errors[0].code == "queue_expired"
                else:
                    models.invalid = finish == "invalid"
                    manager.testing_users.clear()
                    graph.release.set()
                    async with manager.lock:
                        await manager._dispatch_locked()
                    await asyncio.gather(*manager.tasks)
                old = await DailyUsage.get(owner_id="student", day="2099-01-01")
                assert (old.operations, old.reserved) == (int(finish == "execute"), 0)
                assert (await models.usage("student"))["used"] == 0
                assert not await SessionOperation.exclude(encrypted_models="").exists()
                if finish != "delete":
                    stored = await SearchSession.get(session_id=session.session_id)
                    assert (
                        stored.state["input_data"]["description"] == "Synthetic applicant student"
                    )
            finally:
                current_user_id.reset(token)

    asyncio.run(scenario())


def test_restart_recovers_waiting_without_loading_history_or_repeating_interrupted_work() -> None:
    async def scenario() -> None:
        async with queue_manager(concurrent_total_limit=1) as (manager, graph, models):
            running = await submit(manager, "running")
            waiting = await submit(manager, "waiting")
            await graph.started.wait()
            await manager.close()
            # Simulate a crash after claiming a task but before publishing its failure.
            await SearchSession.filter(session_id=running.session_id).update(outcome="running")
            await SessionOperation.filter(operation_id=running.operation_id).update(
                status="running"
            )
            restored = SessionService(
                graph,
                Memory(),
                settings=manager.settings,
                model_settings=models,
                graph_factory=lambda _: graph,
            )
            restored.testing_users.add("occupied")
            try:
                await restored.open()
                assert not restored.sessions
                token = current_user_id.set("running")
                failed = await restored.get(running.session_id)
                assert failed.outcome == "failed" and failed.errors[0].code == "search_interrupted"
                assert (await models.usage("running"))["used"] == 1
                current_user_id.set("waiting")
                queued = await restored.get(waiting.session_id)
                assert queued.operation_id == waiting.operation_id and queued.outcome == "queued"
                assert (await models.usage("waiting"))["reserved"] == 1
                current_user_id.reset(token)
                restored.testing_users.clear()
                graph.release.set()
                restored.wake.set()
                await wait_until(lambda: models.closed == 2 and not restored.tasks)
                assert graph.owners == ["running", "waiting"]
                assert (await models.usage("waiting"))["used"] == 1
            finally:
                await restored.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_at", ["persist", "request", "operation"])
def test_admission_rolls_back_all_rows_and_reservations(
    failure_at: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        async with queue_manager() as (manager, graph, models):
            failure = OSError("Synthetic transaction failure")

            async def fail(*args: Any, **kwargs: Any) -> Any:
                raise failure

            with monkeypatch.context() as patch:
                target, name = {
                    "persist": (manager, "_persist"),
                    "request": (AcceptedRequest, "create"),
                    "operation": (SessionOperation, "create"),
                }[failure_at]
                patch.setattr(target, name, fail)
                with pytest.raises(OSError) as raised:
                    await submit(manager, "student")
                assert raised.value is failure
            assert not await SearchSession.exists()
            assert not await SessionOperation.exists()
            assert not await AcceptedRequest.exists()
            assert not await DailyUsage.exists()
            assert models.created == graph.calls == 0
            await submit(manager, "student")

    asyncio.run(scenario())


def test_idle_cache_and_cleanup_preserve_history_and_idempotency() -> None:
    async def scenario() -> None:
        async with queue_manager(session_cache_entries=2, cleanup_batch_size=2) as (
            manager,
            graph,
            models,
        ):
            graph.release.set()
            sessions = []
            for index in range(5):
                sessions.append(await submit(manager, f"owner-{index}"))
                await asyncio.gather(*manager.tasks)
            assert len(manager.sessions) == 2
            assert sessions[0].session_id not in manager.sessions
            token = current_user_id.set("owner-0")
            try:
                restored = await manager.get(sessions[0].session_id)
                assert restored.outcome == "completed"
                manager.settings.session_cache_bytes = 1
                manager._trim_cache()
                assert not manager.sessions
                assert (await manager.get(sessions[0].session_id)) == restored
                assert not manager.sessions
                await SessionOperation.all().update(
                    finished_at=datetime.now(UTC) - timedelta(days=3)
                )
                for index in range(3):
                    await LoginSession.create(
                        token_hash=f"expired-{index}",
                        owner_id="owner-0",
                        csrf_token="synthetic",
                        expires_at=datetime.now(UTC) - timedelta(seconds=1),
                    )
                async with manager.lock:
                    await manager._cleanup_locked()
                assert await LoginSession.all().count() == 1
                assert await SessionOperation.all().count() == 5
                for _ in range(3):
                    async with manager.lock:
                        await manager._cleanup_locked()
                assert not await SessionOperation.exists()
                assert await SearchSession.all().count() == 5
                assert await AcceptedRequest.all().count() == 5
                assert (await submit(manager, "owner-0")).operation_id == restored.operation_id
                assert models.created == 5
            finally:
                current_user_id.reset(token)

    asyncio.run(scenario())


def test_queue_positions_advance_persisted_versions_without_event_subscribers() -> None:
    async def scenario() -> None:
        async with queue_manager(concurrent_total_limit=1) as (manager, graph, models):
            manager.testing_users.add("occupied")
            first = await submit(manager, "first")
            second = await submit(manager, "second")
            assert second.session_id not in manager.sessions
            assert not manager.subscribers
            token = current_user_id.set("first")
            try:
                await manager.delete(first.session_id)
                stored = await SearchSession.get(session_id=second.session_id)
                assert stored.state["queue_position"] == 1
                assert stored.snapshot_version > second.snapshot_version
                current_user_id.set("second")
                refreshed = await manager.get(second.session_id)
                assert refreshed.queue_position == 1
                assert refreshed.snapshot_version == stored.snapshot_version
                async with manager.lock:
                    await manager._notify_positions()
                assert (
                    await manager.get(second.session_id)
                ).snapshot_version == stored.snapshot_version
                assert (await models.usage("second"))["reserved"] == 1
            finally:
                current_user_id.reset(token)

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["cancel", "claim"])
def test_failed_queue_transition_rolls_back_quota_snapshot_and_request(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        async with queue_manager(concurrent_total_limit=1) as (manager, graph, models):
            manager.testing_users.add("occupied")
            session = await submit(manager, "student")
            assert manager.scheduler is not None
            manager.scheduler.cancel()
            await asyncio.gather(manager.scheduler, return_exceptions=True)
            manager.scheduler = None
            failure = OSError("Synthetic failure after quota settlement")

            async def fail(*args: Any, **kwargs: Any) -> Any:
                raise failure

            token = current_user_id.set("student")
            try:
                with monkeypatch.context() as patch:
                    if action == "cancel":
                        patch.setattr(AcceptedRequest, "create", fail)
                        with pytest.raises(OSError) as raised:
                            await manager.cancel(
                                session.session_id,
                                SessionCancelRequest(
                                    request_id="cancel",
                                    expected_revision=session.revision,
                                    operation_id=session.operation_id,
                                ),
                            )
                    else:
                        patch.setattr(SessionOperation, "save", fail)
                        manager.testing_users.clear()
                        with pytest.raises(OSError) as raised:
                            async with manager.lock:
                                await manager._dispatch_locked()
                    assert raised.value is failure
                restored = await manager.get(session.session_id)
                assert restored.outcome == "queued"
                assert restored.snapshot_version == session.snapshot_version
                operation = await SessionOperation.get(operation_id=session.operation_id)
                assert (operation.status, operation.quota_status) == ("queued", "reserved")
                assert operation.encrypted_models and operation.encrypted_input
                assert not await AcceptedRequest.filter(request_id="cancel").exists()
                usage = await models.usage("student")
                assert (usage["used"], usage["reserved"]) == (0, 1)
                assert not manager.tasks and graph.calls == 0
                assert models.closed == models.created == int(action == "claim")
                manager.testing_users.clear()
                graph.release.set()
                async with manager.lock:
                    await manager._dispatch_locked()
                await asyncio.gather(*manager.tasks)
                operation = await SessionOperation.get(operation_id=session.operation_id)
                assert (operation.status, operation.quota_status) == ("succeeded", "charged")
                usage = await models.usage("student")
                assert (usage["used"], usage["reserved"]) == (1, 0)
            finally:
                current_user_id.reset(token)

    asyncio.run(scenario())
