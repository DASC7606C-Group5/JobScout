"""Session cancellation, checkpoint contention, and provider ownership regressions."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from tortoise import Tortoise

from jobscout.models import AcceptedRequest, SearchSession, SessionOperation
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.session import SessionResumeRequest, SessionStopRequest
from jobscout.services.identity import current_user_id
from jobscout.services.session_service import SessionOperationError, _Session
from tests.test_search_stop import ProgressGraph
from tests.test_session_operations import (
    ControlledGraph,
    Memory,
    Snapshot,
    close_manager,
    create_payload,
    manager_for,
)


class PreparedModels:
    def __init__(self) -> None:
        self.closed = False
        self.provider = self
        self.uses_server = False
        self.settings = SimpleNamespace(concurrent_user_limit=10, concurrent_total_limit=10)

    async def snapshot(self, owner: str) -> tuple[dict[str, Any], bool]:
        return {}, False

    def restore(self, values: dict[str, Any], uses_server: bool) -> PreparedModels:
        return self

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize("operation", ["create", "resume"])
@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_acceptance_releases_provider_and_restores_committed_state(
    operation: str, cancelled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        graph = ControlledGraph()
        graph.release.set()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            task = manager.sessions[created.session_id].task
            assert task is not None
            await task
            before = await manager.get(created.session_id)
            models = PreparedModels()
            manager.model_settings = models
            original_persist = manager._persist
            failure = asyncio.CancelledError() if cancelled else OSError("Storage unavailable")

            async def fail_after_write(record: _Session, **kwargs: Any) -> None:
                await original_persist(record, **kwargs)
                raise failure

            with monkeypatch.context() as patch:
                patch.setattr(manager, "_persist", fail_after_write)
                with pytest.raises(type(failure)) as raised:
                    if operation == "create":
                        await manager.create(create_payload("not-accepted"))
                    else:
                        await manager.resume(
                            created.session_id,
                            SessionResumeRequest(
                                request_id="not-accepted",
                                expected_revision=before.revision,
                                action="edit_conditions",
                            ),
                        )
                assert raised.value is failure
            assert not models.closed  # No provider was created before admission committed.
            assert await manager.get(created.session_id) == before
            stored = await SearchSession.get(session_id=created.session_id)
            assert stored.revision == before.revision
            assert stored.outcome == before.outcome
            assert [record.session_id for record in await SearchSession.all()] == [
                created.session_id
            ]
            assert not await AcceptedRequest.filter(request_id="not-accepted").exists()
        finally:
            await close_manager(manager)

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_stage", ["build", "cleanup"])
def test_worker_setup_and_cleanup_failures_close_provider(
    failure_stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        graph = ControlledGraph()
        graph.release.set()
        manager = await manager_for(graph, Memory())
        models = PreparedModels()
        manager.model_settings = models

        def build(provider: Any) -> ControlledGraph:
            if failure_stage == "build":
                raise RuntimeError("Graph unavailable")
            return graph

        async def fail_cleanup(session_id: str) -> None:
            raise RuntimeError("Cleanup unavailable")

        manager.graph_factory = build
        try:
            with monkeypatch.context() as patch:
                patch.setattr(graph, "cleanup_session", fail_cleanup)
                created = await manager.create(create_payload())
                task = manager.sessions[created.session_id].task
                assert task is not None
                await task
            current = await manager.get(created.session_id)
            assert current.outcome == ("failed" if failure_stage == "build" else "completed")
            assert models.closed
            assert (
                await SearchSession.get(session_id=created.session_id)
            ).outcome == current.outcome
        finally:
            await close_manager(manager)

    asyncio.run(scenario())


def test_shutdown_releases_provider_and_rejects_new_work() -> None:
    async def scenario() -> None:
        graph = ControlledGraph()
        manager = await manager_for(graph, Memory())
        models = PreparedModels()
        manager.model_settings = models
        manager.graph_factory = lambda provider: graph
        try:
            await manager.create(create_payload())
            await manager.close()
            assert models.closed
            with pytest.raises(SessionOperationError) as error:
                await manager.create(create_payload("after-close"))
            assert error.value.code == "service_unavailable"
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_checkpoint_read_does_not_block_other_sessions_or_restore_deleted_session() -> None:
    class BlockedSnapshotGraph(ControlledGraph):
        def __init__(self) -> None:
            super().__init__()
            self.read_started = asyncio.Event()
            self.read_release = asyncio.Event()

        async def aget_state(self, config: dict[str, Any]) -> Snapshot:
            self.read_started.set()
            await self.read_release.wait()
            return Snapshot({"revision": 1, "current_stage": "profile"})

    async def scenario() -> None:
        graph = BlockedSnapshotGraph()
        manager = await manager_for(graph, Memory())
        pending = None
        try:
            created = await manager.create(create_payload())
            pending = asyncio.create_task(manager.get(created.session_id))
            await graph.read_started.wait()
            identity = current_user_id.set("another-owner")
            try:
                another = await asyncio.wait_for(manager.create(create_payload("other")), timeout=1)
            finally:
                current_user_id.reset(identity)
            assert another.session_id != created.session_id
            await asyncio.wait_for(manager.delete(created.session_id), timeout=1)
            graph.read_release.set()
            with pytest.raises(SessionOperationError) as error:
                await pending
            assert error.value.code == "search_not_found"
            assert not await SearchSession.filter(session_id=created.session_id).exists()
        finally:
            graph.read_release.set()
            if pending is not None:
                await asyncio.gather(pending, return_exceptions=True)
            await close_manager(manager)

    asyncio.run(scenario())


def test_busy_checkpoint_returns_latest_published_session_without_waiting_for_writer() -> None:
    class BlockedGraph(ControlledGraph):
        def __init__(self) -> None:
            super().__init__()
            self.read_release = asyncio.Event()

        async def aget_state(self, config: dict[str, Any]) -> Snapshot:
            await self.read_release.wait()
            return Snapshot({})

    async def scenario() -> None:
        graph = BlockedGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            record = manager.sessions[created.session_id]
            record.state.update(
                profile=UserProfile(profile_id="published", skills=["SQL"]),
                progress_seq=7,
                progress={"sequence": 7, "retrieval_stopped": True},
            )
            await manager._persist(record)
            manager._notify(record)
            snapshot = await asyncio.wait_for(manager.get(created.session_id), timeout=2)
            assert snapshot.session_id == created.session_id
            assert snapshot.outcome == "running" and snapshot.revision == created.revision
            assert snapshot.profile is not None and snapshot.profile.skills == ["SQL"]
            assert snapshot.progress.sequence == 7 and snapshot.progress.retrieval_stopped
            assert record.task is not None and not record.task.done()
        finally:
            graph.read_release.set()
            await close_manager(manager)

    asyncio.run(scenario())


def test_busy_workspace_write_returns_committed_snapshot_and_never_uncommitted_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        graph = ControlledGraph()
        manager = await manager_for(graph, Memory())
        started = asyncio.Event()
        release = asyncio.Event()
        failure = OSError("Workspace write failed")
        writer = None
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            record = manager.sessions[created.session_id]

            async def blocked_write(*args: Any, **kwargs: Any) -> None:
                started.set()
                await release.wait()
                raise failure

            with monkeypatch.context() as patch:
                patch.setattr(manager, "_persist", blocked_write)
                writer = asyncio.create_task(
                    manager._progress(
                        record,
                        record.active_run_id or "",
                        record.revision,
                        {
                            "run_id": record.active_run_id,
                            "progress_seq": 7,
                            "progress": {"sequence": 7, "retrieval_stopped": True},
                        },
                    )
                )
                await started.wait()
                snapshot = await asyncio.wait_for(manager.get(created.session_id), timeout=2)
                assert snapshot == created
                assert snapshot.progress.sequence == 0
                assert not snapshot.progress.retrieval_stopped
                release.set()
                with pytest.raises(OSError) as error:
                    await writer
                assert error.value is failure
            assert await manager.get(created.session_id) == created
        finally:
            release.set()
            if writer is not None:
                await asyncio.gather(writer, return_exceptions=True)
            await close_manager(manager)

    asyncio.run(scenario())


def test_polling_unchanged_checkpoints_does_not_rewrite_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        graph = ControlledGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            graph.states[created.session_id] = {"revision": 1, "current_stage": "profile"}
            first = await manager.get(created.session_id)

            async def reject_write(*args: Any, **kwargs: Any) -> None:
                raise AssertionError("Unchanged checkpoints must not write")

            with monkeypatch.context() as patch:
                patch.setattr(manager, "_persist", reject_write)
                assert await manager.get(created.session_id) == first
                assert await manager.get(created.session_id) == first
        finally:
            await close_manager(manager)

    asyncio.run(scenario())


def test_concurrent_checkpoint_reads_cannot_replace_a_newer_snapshot() -> None:
    class ReorderedGraph(ControlledGraph):
        def __init__(self) -> None:
            super().__init__()
            self.old_started = asyncio.Event()
            self.old_release = asyncio.Event()
            self.reads = 0

        async def aget_state(self, config: dict[str, Any]) -> Snapshot:
            self.reads += 1
            read_number = self.reads
            if read_number == 1:
                self.old_started.set()
                await self.old_release.wait()
            return Snapshot(
                {
                    "revision": 1,
                    "profile": UserProfile(
                        profile_id="applicant", skills=["Old" if read_number == 1 else "New"]
                    ),
                }
            )

    async def scenario() -> None:
        graph = ReorderedGraph()
        manager = await manager_for(graph, Memory())
        old_read = None
        try:
            created = await manager.create(create_payload())
            old_read = asyncio.create_task(manager.get(created.session_id))
            await graph.old_started.wait()
            latest = await asyncio.wait_for(manager.get(created.session_id), 1)
            assert latest.profile is not None and latest.profile.skills == ["New"]
            graph.old_release.set()
            assert await old_read == latest
            stored = await SearchSession.get(session_id=created.session_id)
            assert stored.state["profile"]["skills"] == ["New"]
        finally:
            graph.old_release.set()
            if old_read is not None:
                await asyncio.gather(old_read, return_exceptions=True)
            await close_manager(manager)

    asyncio.run(scenario())


def test_shutdown_failure_still_closes_all_unstarted_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        graph = ControlledGraph()
        manager = await manager_for(graph, Memory())
        first = PreparedModels()
        second = PreparedModels()
        failure = OSError("Checkpoint unavailable")

        async def reject_checkpoint(config: dict[str, Any]) -> Snapshot:
            raise failure

        try:
            # Install two accepted workers before either coroutine receives its first turn.
            for session_id, models in [("first", first), ("second", second)]:
                record = _Session(session_id, {}, thread_id=session_id)
                manager.sessions[session_id] = record
                manager._start(record, {}, models=models, operation=SessionOperation())
            monkeypatch.setattr(graph, "aget_state", reject_checkpoint)
            with pytest.raises(ExceptionGroup) as error:
                await manager.close()
            assert all(item is failure for item in error.value.exceptions)
            assert first.closed and second.closed
            assert set(graph.cleaned) == {"first", "second"}
            assert not graph.started.is_set()
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["close", "delete"])
def test_cancelling_an_edit_drains_the_previous_provider_cleanup(operation: str) -> None:
    class ClosingModels(PreparedModels):
        def __init__(self) -> None:
            super().__init__()
            self.close_started = asyncio.Event()
            self.close_release = asyncio.Event()

        async def aclose(self) -> None:
            self.close_started.set()
            await self.close_release.wait()
            await super().aclose()

    async def scenario() -> None:
        graph = ProgressGraph()
        manager = await manager_for(graph, Memory())
        previous_models = ClosingModels()
        next_models = PreparedModels()
        next_built = asyncio.Event()

        def build(provider: Any) -> ControlledGraph:
            if provider is next_models:
                next_built.set()
            return graph

        manager.model_settings = previous_models
        manager.graph_factory = build
        cleanup = None
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            record = manager.sessions[created.session_id]
            record.state["profile"] = UserProfile(profile_id="applicant", skills=["SQL"])
            previous_task = record.task
            assert previous_task is not None
            manager.model_settings = next_models
            await manager.resume(
                created.session_id,
                SessionResumeRequest(
                    request_id="edit", expected_revision=1, action="edit_conditions"
                ),
            )
            await previous_models.close_started.wait()
            assert not next_built.is_set()
            assert record.task is previous_task
            assert len(manager.tasks) == 1
            assert (await manager.get(created.session_id)).outcome == "queued"
            cleanup = asyncio.create_task(
                manager.close() if operation == "close" else manager.delete(created.session_id)
            )

            await asyncio.sleep(0)
            assert not cleanup.done()
            previous_models.close_release.set()
            await asyncio.wait_for(cleanup, 1)
            assert previous_models.closed and not next_models.closed
            assert previous_task.done()
            assert not next_built.is_set()
        finally:
            previous_models.close_release.set()
            if cleanup is not None:
                await asyncio.gather(cleanup, return_exceptions=True)
            await close_manager(manager)

    asyncio.run(scenario())


def test_shutdown_drains_previous_cleanup_before_replacement_worker_starts() -> None:
    class ClosingModels(PreparedModels):
        def __init__(self) -> None:
            super().__init__()
            self.close_started = asyncio.Event()
            self.close_release = asyncio.Event()

        async def aclose(self) -> None:
            self.close_started.set()
            await self.close_release.wait()
            await super().aclose()

    async def scenario() -> None:
        graph = ProgressGraph()
        manager = await manager_for(graph, Memory())
        previous_models = ClosingModels()
        next_models = PreparedModels()
        manager.model_settings = previous_models
        built_providers = []

        def build(provider: Any) -> ControlledGraph:
            built_providers.append(provider)
            return graph

        manager.graph_factory = build
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            record = manager.sessions[created.session_id]
            record.state["profile"] = UserProfile(profile_id="applicant", skills=["SQL"])
            manager.model_settings = next_models
            await manager.resume(
                created.session_id,
                SessionResumeRequest(
                    request_id="edit", expected_revision=1, action="edit_conditions"
                ),
            )

            async def finish_previous_cleanup() -> None:
                await previous_models.close_started.wait()
                previous_models.close_release.set()

            release = asyncio.create_task(finish_previous_cleanup())
            await manager.close()
            await release
            assert built_providers == [previous_models]
            assert previous_models.closed and not next_models.closed
            assert not record.previous_tasks
        finally:
            previous_models.close_release.set()
            await close_manager(manager)

    asyncio.run(scenario())


@pytest.mark.parametrize("checkpoint_sequence", [0, 1])
def test_lagging_checkpoint_cannot_undo_stop(checkpoint_sequence: int) -> None:
    async def scenario() -> None:
        graph = ProgressGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            stopped = await manager.stop(
                created.session_id,
                SessionStopRequest(request_id="stop", expected_revision=1, run_id=graph.run_id),
            )
            graph.states[created.session_id] = {
                "revision": 1,
                "current_stage": "plan",
                "run_id": graph.run_id,
                "progress_seq": checkpoint_sequence,
                "progress": {"sequence": checkpoint_sequence},
                "stop_reason": None,
            }
            current = await manager.get(created.session_id)
            assert current.current_stage == stopped.current_stage == "review"
            assert current.progress.retrieval_stopped
            assert current.stop_reason == "user_stopped"
        finally:
            await close_manager(manager)

    asyncio.run(scenario())


def test_failed_completion_commit_publishes_durable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        graph = ControlledGraph()
        manager = await manager_for(graph, Memory())
        try:
            created = await manager.create(create_payload())
            await graph.started.wait()
            queue = await manager.subscribe(created.session_id)
            await queue.get()
            original_persist = manager._persist

            async def reject_completion(record: _Session, **kwargs: Any) -> None:
                if record.outcome == "completed":
                    raise OSError("Completion write failed")
                await original_persist(record, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(manager, "_persist", reject_completion)
                graph.release.set()
                task = manager.sessions[created.session_id].task
                assert task is not None
                await task
            snapshot = await asyncio.wait_for(queue.get(), 1)
            assert snapshot is not None and snapshot.outcome == "failed"
            assert snapshot.retryable
            assert (await SearchSession.get(session_id=created.session_id)).outcome == "failed"
        finally:
            await close_manager(manager)

    asyncio.run(scenario())
