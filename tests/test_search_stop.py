"""Ending retrieval preserves published vacancies and rejects stale execution callbacks."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from jobscout.models import SearchSession
from jobscout.schemas.job import JobPosting
from jobscout.schemas.profile import SearchOptions, UserProfile
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.schemas.session import SessionResumeRequest, SessionStopRequest
from jobscout.schemas.workspace import SaveJobRequest
from jobscout.services.session_service import SessionOperationError
from jobscout.services.workspace_service import WorkspaceService
from tests.test_session_operations import (
    ControlledGraph,
    Memory,
    close_manager,
    create_payload,
    manager_for,
)


def item(job_id: str, *, complete: bool = True) -> RecommendationItem:
    return RecommendationItem(
        job=JobPosting(
            job_id=job_id,
            source="jobsdb",
            source_url=f"https://hk.jobsdb.com/job/{job_id}",
            title="Analyst",
            company="Synthetic",
            location="Hong Kong",
            target_direction="Analyst",
            fetched_at=datetime.now(UTC),
            description="Analyse supplied data.",
        ),
        analysis_status="complete" if complete else "partial",
        verification_status="confirmed",
    )


class ProgressGraph(ControlledGraph):
    def __init__(self, *, publish_results: bool = True) -> None:
        super().__init__()
        self.publish_results = publish_results
        self.callback: Any = None
        self.run_id = ""
        self.cancelled = asyncio.Event()

    async def ainvoke(self, data: Any, config: dict[str, Any]) -> dict[str, Any]:
        runtime = config["configurable"]
        self.run_id = runtime["run_id"]
        self.callback = runtime["on_progress"]
        result = RecommendationResult(
            session_id=data["session_id"],
            generated_at=datetime.now(UTC),
            jobs=[item("complete"), item("unfinished", complete=False)]
            if self.publish_results
            else [],
            pending_jobs=[item("pending").model_copy(update={"verification_status": "pending"})]
            if self.publish_results
            else [],
        )
        await self.callback(
            {
                "run_id": self.run_id,
                "progress_seq": 1,
                "progress": {
                    "sequence": 1,
                    "analyzed_count": 2,
                    "matched_count": 1,
                    "pending_count": 1,
                },
                "recommendation": result,
            }
        )
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            if result.jobs:
                result.jobs[0].job.title = "Late mutation"
            # A provider that suppresses cancellation still must not restore late results.
            await self.callback(
                {
                    "run_id": self.run_id,
                    "progress_seq": 100,
                    "progress": {"sequence": 100, "matched_count": 1},
                    "recommendation": result.model_copy(update={"jobs": [item("late")]}),
                }
            )
        return {"recommendation": result, "run_id": self.run_id, "current_stage": "completed"}


def test_jobs_from_an_earlier_shortlist_remain_saveable_with_server_supplied_data() -> None:
    async def scenario() -> None:
        graph = ProgressGraph()
        manager = await manager_for(graph, Memory())
        try:
            session = await manager.create(create_payload("shortlist"))
            await graph.started.wait()
            original = (await manager.get(session.session_id)).recommendation
            assert original is not None
            replacement = original.model_copy(update={"jobs": [item("better")], "pending_jobs": []})
            await graph.callback(
                {
                    "run_id": graph.run_id,
                    "progress_seq": 2,
                    "progress": {"sequence": 2, "matched_count": 1},
                    "recommendation": replacement,
                }
            )
            workspace = WorkspaceService(manager)
            payload = SaveJobRequest(session_id=session.session_id, expected_revision=1)
            saved = await workspace.save_job("complete", payload)
            assert saved == original.jobs[0]
            current = (await manager.get(session.session_id)).recommendation
            assert current is not None
            assert [row.job.job_id for row in current.jobs] == ["better"]
            assert [row.job.job_id for row in (await workspace.saved_jobs()).items] == ["complete"]
            with pytest.raises(SessionOperationError) as unknown:
                await workspace.save_job("never-published", payload)
            assert unknown.value.code == "saved_job_not_found"
            with pytest.raises(SessionOperationError) as stale:
                await workspace.save_job(
                    "complete", payload.model_copy(update={"expected_revision": 0})
                )
            assert stale.value.code == "search_changed"
            manager._get(session.session_id).state["run_id"] = "new-run"
            with pytest.raises(SessionOperationError) as prior_run:
                await workspace.save_job("unfinished", payload)
            assert prior_run.value.code == "saved_job_not_found"
        finally:
            await close_manager(manager)

    asyncio.run(scenario())


@pytest.mark.parametrize("publish_results", [True, False])
def test_stop_preserves_published_vacancies_while_reviews_finish(publish_results: bool) -> None:
    async def check() -> None:
        graph = ProgressGraph(publish_results=publish_results)
        manager = await manager_for(graph, Memory())
        try:
            session = await manager.create(create_payload())
            await graph.started.wait()
            payload = SessionStopRequest(
                request_id="stop", expected_revision=1, run_id=graph.run_id
            )
            response = await manager.stop(session.session_id, payload)
            assert response.outcome == "running"
            assert response.stop_reason == "user_stopped"
            assert response.progress.retrieval_stopped
            assert not graph.cancelled.is_set()
            assert response.recommendation is not None
            expected = ["complete", "unfinished"] if publish_results else []
            assert [entry.job.job_id for entry in response.recommendation.jobs] == expected
            assert all(entry.job.title == "Analyst" for entry in response.recommendation.jobs)
            assert [entry.job.job_id for entry in response.recommendation.pending_jobs] == (
                ["pending"] if publish_results else []
            )
            repeated = await manager.stop(session.session_id, payload)
            assert repeated == response
            current = await manager.get(session.session_id)
            assert current == response
            stored = await SearchSession.get(session_id=session.session_id)
            assert [
                entry["job"]["job_id"] for entry in stored.state["recommendation"]["jobs"]
            ] == expected
            with pytest.raises(SessionOperationError) as conflict:
                await manager.stop(
                    session.session_id, payload.model_copy(update={"expected_revision": 2})
                )
            assert conflict.value.code == "request_conflict"
            graph.release.set()
            task = manager.sessions[session.session_id].task
            assert task is not None
            await task
            completed = await manager.get(session.session_id)
            assert completed.outcome == "completed"
            assert completed.stop_reason == "user_stopped"
            assert completed.recommendation is not None
            await graph.callback(
                {
                    "run_id": graph.run_id,
                    "progress_seq": 100,
                    "progress": {"sequence": 100, "matched_count": 1},
                    "recommendation": completed.recommendation.model_copy(
                        update={"jobs": [item("late")]}
                    ),
                }
            )
            assert (await manager.get(session.session_id)) == completed
        finally:
            await close_manager(manager)

    asyncio.run(check())


@pytest.mark.parametrize("outcome", ["completed", "failed"])
def test_stop_after_natural_terminal_returns_the_existing_result(outcome: str) -> None:
    async def check() -> None:
        graph = ProgressGraph(publish_results=False)
        manager = await manager_for(graph, Memory())
        try:
            session = await manager.create(create_payload())
            await graph.started.wait()
            graph.release.set()
            task = manager.sessions[session.session_id].task
            assert task is not None
            await task
            record = manager.sessions[session.session_id]
            record.outcome = outcome
            record.state["stop_reason"] = "source_exhausted" if outcome == "completed" else "error"
            before = await manager.get(session.session_id)
            stopped = await manager.stop(
                session.session_id,
                SessionStopRequest(
                    request_id="after-terminal",
                    expected_revision=1,
                    run_id=graph.run_id,
                ),
            )
            assert stopped == before
        finally:
            await close_manager(manager)

    asyncio.run(check())


def test_stale_stop_and_old_checkpoint_cannot_replace_new_progress() -> None:
    async def check() -> None:
        graph = ProgressGraph()
        manager = await manager_for(graph, Memory())
        try:
            session = await manager.create(create_payload())
            await graph.started.wait()
            graph.states[session.session_id] = {
                "revision": 1,
                "progress_seq": 0,
                "recommendation": None,
                "run_id": None,
                "progress": {},
            }
            current = await manager.get(session.session_id)
            assert current.progress.sequence == 1
            assert current.recommendation is not None
            for request in (
                SessionStopRequest(request_id="wrong-run", expected_revision=1, run_id="another"),
                SessionStopRequest(
                    request_id="wrong-revision", expected_revision=0, run_id=graph.run_id
                ),
            ):
                with pytest.raises(SessionOperationError) as error:
                    await manager.stop(session.session_id, request)
                assert error.value.code == "search_changed"
            assert (await manager.get(session.session_id)).outcome == "running"
            await manager.stop(
                session.session_id,
                SessionStopRequest(
                    request_id="valid",
                    expected_revision=1,
                    run_id=graph.run_id,
                ),
            )
        finally:
            await close_manager(manager)

    asyncio.run(check())


def test_patch_preserves_omitted_fields_and_explicit_clearing() -> None:
    request = SessionResumeRequest.model_validate(
        {
            "request_id": "edit",
            "expected_revision": 1,
            "profile_updates": {"skills": [], "preferences.location": None},
            "search_options": {"result_count": 20},
        }
    )
    assert request.model_dump()["profile_updates"] == {"skills": [], "preferences.location": None}
    assert request.search_options == SearchOptions(result_count=20)
    profile = UserProfile(profile_id="p", education=["Original"], skills=["SQL"])
    from jobscout.services.conversation_service import ProfileChange, apply_changes

    updated = apply_changes(
        profile,
        [ProfileChange(field=key, value=value) for key, value in request.profile_updates.items()],
    )
    assert updated.education == ["Original"]
    assert updated.skills == []
    assert updated.preferences.location is None
