"""Session feedback and follow-up regressions use offline model and search substitutes."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, TypeAdapter, ValidationError
from tortoise import Tortoise

from jobscout.database import tortoise_config
from jobscout.graph.live import build_live_graph
from jobscout.models import AcceptedRequest
from jobscout.replay.app import create_replay_app
from jobscout.replay.dataset import load_dataset
from jobscout.replay.provider import SyntheticProvider
from jobscout.schemas.conversation import QuestionAnswer
from jobscout.schemas.feedback import (
    FindSimilarRequest,
    FollowUpAnswerRequest,
    FollowUpMessageRequest,
    ResultExclusion,
    ResultPreferences,
    SessionFeedbackRequest,
    SessionFollowUpRequest,
)
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.schemas.session import SessionResumeRequest, SessionStopRequest
from jobscout.services.job_processing_service import process_jobs
from jobscout.services.llm_service import ModelServiceError, ToolTurn
from jobscout.services.result_feedback_service import (
    ResultFeedbackService,
    match_key,
    merge_results,
    refresh_hidden,
)
from jobscout.services.search_agent import SearchAgent
from jobscout.services.session_service import SessionOperationError, SessionService, _Session
from tests.auth_client import AuthenticatedClient
from tests.test_search_agent import Assessment, SnapshotSearch, profile, raw
from tests.test_session_operations import ControlledGraph, Memory
from tests.test_web_scaffold import settled


def result(count: int = 2) -> RecommendationResult:
    jobs = process_jobs([raw(index).model_dump() for index in range(count)]).jobs
    return RecommendationResult(
        session_id="results",
        generated_at=datetime.now(UTC),
        jobs=[RecommendationItem(job=job, recommendation_fit="possible") for job in jobs],
    )


@asynccontextmanager
async def service_for(graph: Any) -> AsyncIterator[SessionService]:
    await Tortoise.init(config=tortoise_config("sqlite://:memory:"))
    await Tortoise.generate_schemas(safe=True)
    service = SessionService(graph, getattr(graph, "checkpointer", None) or Memory())
    record = _Session(
        "results",
        {
            "session_id": "results",
            "revision": 1,
            "profile": profile(),
            "recommendation": result(),
            "conversation": [],
            "current_stage": "completed",
        },
        outcome="completed",
        thread_id="results",
        thread_ids=["results"],
    )
    refresh_hidden(record.state)
    service.sessions["results"] = record
    await service._persist(record)
    try:
        yield service
    finally:
        await service.close()
        await Tortoise.close_connections()


async def finish(service: SessionService) -> Any:
    task = service.sessions["results"].task
    assert task is not None
    await task
    return await service.get("results")


class RecordingProvider(SyntheticProvider):
    def __init__(self) -> None:
        self.schemas: list[str] = []
        self.fail = False

    async def structured[T: BaseModel](
        self, schema: type[T], messages: list[dict[str, str]], *, deadline: float | None = None
    ) -> T:
        self.schemas.append(schema.__name__)
        if self.fail and schema.__name__ == "ResultInterpretation":
            self.fail = False
            raise ModelServiceError("model_timeout")
        return await super().structured(schema, messages, deadline=deadline)


class FollowUpAssessment(Assessment):
    async def begin_search(self, search_id: str) -> None:
        pass

    async def cleanup_session(self, session_id: str) -> None:
        pass

    def import_cache(self, snapshot: object, session_id: str) -> None:
        pass

    def export_cache(self) -> dict[str, object]:
        return {}


def test_reaction_has_no_model_side_effects_and_restores_after_restart() -> None:
    class NoModels:
        async def prepare(self, owner: str) -> None:
            raise AssertionError("Reaction must not prepare a model")

    async def check() -> None:
        graph = ControlledGraph()
        async with service_for(graph) as service:
            service.model_settings = NoModels()
            before = await service.get("results")
            assert before.recommendation is not None
            job_id = before.recommendation.jobs[0].job.job_id
            payload = SessionFeedbackRequest(
                request_id="reaction", expected_revision=1, job_id=job_id, reaction="not_interested"
            )
            saved = await service.feedback("results", payload)
            assert saved.hidden_job_ids == [job_id]
            assert saved.recommendation == before.recommendation
            assert saved.progress == before.progress
            assert saved.conversation == before.conversation
            assert saved.operation_kind == "initial_search"
            assert saved.revision == 2
            assert await service.feedback("results", payload) == saved
            assert graph.calls == 0
            restarted = SessionService(graph, Memory())
            await restarted.open()
            assert await restarted.get("results") == saved
            await restarted.close()
            with pytest.raises(SessionOperationError) as error:
                await service.feedback(
                    "results", payload.model_copy(update={"reaction": "interested"})
                )
            assert error.value.code == "request_conflict"
            with pytest.raises(SessionOperationError) as error:
                await service.feedback(
                    "results", payload.model_copy(update={"request_id": "stale"})
                )
            assert error.value.code == "search_changed"

    asyncio.run(check())


def test_reaction_rollback_and_category_exclusion_survives_undo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        async with service_for(ControlledGraph()) as service:
            record = service.sessions["results"]
            job = record.state["recommendation"].jobs[0].job
            rule = ResultExclusion(
                exclusion_id="sales", description="Exclude sales", user_message_id="user-rule"
            )
            record.state.update(
                result_preferences=ResultPreferences(exclusions=[rule]),
                exclusion_matches={
                    match_key(job, rule.exclusion_id, rule.description): {"decision": "matches"}
                },
            )
            await service.feedback(
                "results",
                SessionFeedbackRequest(
                    request_id="dislike",
                    expected_revision=1,
                    job_id=job.job_id,
                    reaction="not_interested",
                ),
            )
            saved = await service.feedback(
                "results",
                SessionFeedbackRequest(
                    request_id="undo", expected_revision=2, job_id=job.job_id, reaction=None
                ),
            )
            assert saved.job_feedback == []
            assert saved.hidden_job_ids == [job.job_id]
            assert [reason.kind for reason in saved.hidden_job_reasons] == ["excluded"]

            async def fail(*args: Any, **kwargs: Any) -> None:
                raise RuntimeError("database failure")

            monkeypatch.setattr(service, "_persist", fail)
            with pytest.raises(RuntimeError, match="database failure"):
                await service.feedback(
                    "results",
                    SessionFeedbackRequest(
                        request_id="failed-save",
                        expected_revision=3,
                        job_id=job.job_id,
                        reaction="interested",
                    ),
                )
            assert await service.get("results") == saved
            assert "failed-save" not in record.requests
            assert not await AcceptedRequest.filter(request_id="failed-save").exists()

    asyncio.run(check())


def test_follow_up_preflight_does_not_accept_or_append_input() -> None:
    class NoModels:
        settings = type("Limits", (), {"concurrent_user_limit": 2, "concurrent_total_limit": 2})()

        async def prepare(self, owner: str) -> None:
            raise ModelServiceError("model_configuration")

    async def check() -> None:
        async with service_for(ControlledGraph()) as service:
            service.model_settings = NoModels()
            before = await service.get("results")
            with pytest.raises(ModelServiceError):
                await service.follow_up(
                    "results",
                    FollowUpMessageRequest(
                        request_id="unprepared",
                        expected_revision=1,
                        action="message",
                        message="Is this suitable?",
                    ),
                )
            assert await service.get("results") == before
            assert not await AcceptedRequest.filter(request_id="unprepared").exists()

    asyncio.run(check())


def test_questions_do_not_change_feedback_and_failed_interpretation_retries_once() -> None:
    async def check() -> None:
        provider = RecordingProvider()
        graph = build_live_graph(InMemorySaver(), provider, SnapshotSearch())
        async with service_for(graph) as service:
            job_id = result().jobs[0].job.job_id
            await service.feedback(
                "results",
                SessionFeedbackRequest(
                    request_id="like", expected_revision=1, job_id=job_id, reaction="interested"
                ),
            )
            provider.fail = True
            request = FollowUpMessageRequest(
                request_id="question",
                expected_revision=2,
                action="message",
                job_id=job_id,
                message="Is this job suitable for me?",
            )
            accepted = await service.follow_up("results", request)
            assert accepted.outcome == "running" and accepted.run_id is None
            failed = await finish(service)
            assert failed.outcome == "failed"
            assert failed.errors[0].code == "model_unavailable"
            assert failed.recommendation == accepted.recommendation
            assert failed.job_feedback[0].reason is None
            await service.resume(
                "results",
                SessionResumeRequest(request_id="retry", expected_revision=3, action="retry"),
            )
            completed = await finish(service)
            assert completed.outcome == "completed"
            assert completed.job_feedback[0].reason is None
            assert [
                message.text for message in completed.conversation if message.role == "user"
            ] == [request.message]
            assert set(provider.schemas) == {"ResultInterpretation"}
            assert await service.follow_up("results", request) == completed

    asyncio.run(check())


@pytest.mark.parametrize("skip", [False, True])
def test_ambiguous_reason_pauses_and_answer_resumes_original_request(skip: bool) -> None:
    async def check() -> None:
        provider = RecordingProvider()
        search = SnapshotSearch()
        graph = build_live_graph(InMemorySaver(), provider, search)
        async with service_for(graph) as service:
            record = service.sessions["results"]
            original = record.state["recommendation"]
            first = original.jobs[0]
            first.job.title = "Sales Assistant"
            job_id = first.job.job_id
            await service.feedback(
                "results",
                SessionFeedbackRequest(
                    request_id="dislike",
                    expected_revision=1,
                    job_id=job_id,
                    reaction="not_interested",
                ),
            )
            await service.follow_up(
                "results",
                FollowUpMessageRequest(
                    request_id="ambiguous",
                    expected_revision=2,
                    action="message",
                    job_id=job_id,
                    message="这种不喜欢",
                ),
            )
            paused = await finish(service)
            assert paused.outcome == "paused" and paused.current_stage == "follow_up_clarify"
            assert paused.result_preferences.exclusions == []
            assert paused.recommendation is not None and len(paused.recommendation.jobs) == 2
            thread_id = record.thread_id
            question_id = paused.clarification_questions[0].question_id
            with pytest.raises(SessionOperationError) as error:
                await service.feedback(
                    "results",
                    SessionFeedbackRequest(
                        request_id="blocked", expected_revision=3, job_id=job_id, reaction=None
                    ),
                )
            assert error.value.code == "follow_up_answer_required"
            await service.follow_up(
                "results",
                FollowUpAnswerRequest(
                    request_id="answer",
                    expected_revision=3,
                    action="answer",
                    answers=[]
                    if skip
                    else [QuestionAnswer(question_id=question_id, value="不喜欢销售职责")],
                    skipped_question_ids=[question_id] if skip else [],
                ),
            )
            completed = await finish(service)
            assert record.thread_id == thread_id
            assert completed.outcome == "completed"
            assert completed.hidden_job_ids == [job_id]
            assert search.requests == []
            assert len(completed.result_preferences.exclusions) == (0 if skip else 1)
            if not skip:
                assert completed.job_feedback[0].reason == "不喜欢销售职责"
                assert completed.result_preferences.exclusions[0].user_message_id in {
                    message.message_id for message in completed.conversation
                }
            assert "ProfileExtraction" not in provider.schemas
            assert "QuestionGeneration" not in provider.schemas

    asyncio.run(check())


def test_merge_keeps_stable_id_sources_and_order_across_pending_review_and_25_jobs() -> None:
    previous = result(20)
    first = previous.jobs.pop(0)
    first = first.model_copy(update={"review_status": "queued"})
    previous.pending_jobs = [first]
    order = [first.job.job_id, *(item.job.job_id for item in previous.jobs)]
    duplicate = first.model_copy(
        update={
            "job": first.job.model_copy(
                update={
                    "job_id": "alternate-source",
                    "source_url": "https://other.example/job",
                    "source_links": ["https://other.example/job"],
                }
            ),
            "review_status": "reviewed",
        }
    )
    incoming = result(25)
    incoming.jobs = [duplicate, *incoming.jobs[20:]]
    merged, next_order = merge_results(previous, incoming, order)
    assert len(merged.jobs) == 25 and merged.pending_jobs == []
    assert next_order[:20] == order
    assert "alternate-source" not in next_order
    assert "https://other.example/job" in merged.jobs[0].job.source_links
    assert merged.jobs[0].job.job_id == first.job.job_id


def test_supplementary_search_deduplicates_history_without_changing_initial_limit() -> None:
    async def check() -> None:
        original = result(20)
        search = SnapshotSearch(26)
        confirmed = profile(20)
        snapshots: list[dict[str, Any]] = []

        async def progress(update: dict[str, Any]) -> None:
            snapshots.append(update)

        agent = SearchAgent(SyntheticProvider(), search, Assessment())
        update = await agent.run(
            confirmed,
            {},
            "results",
            deadline=asyncio.get_running_loop().time() + 10,
            history=original,
            reference_job=original.jobs[0].job,
            additional_result_count=5,
            on_progress=progress,
        )
        old_ids = {item.job.job_id for item in original.jobs}
        new_ids = {
            item.job.job_id
            for item in update["recommendation"].jobs + update["recommendation"].pending_jobs
        } - old_ids
        assert len(new_ids) == 5
        assert confirmed.search_options.result_count == 20
        assert agent.target == 5
        assert not old_ids & set(agent.jobs)
        assert snapshots

    asyncio.run(check())


@pytest.mark.parametrize("case", ["unknown", "forged_quote", "wrong_job", "wrong_rule"])
def test_exclusion_checks_quotes_and_ids_and_unknown_never_hides(case: str) -> None:
    class Provider(SyntheticProvider):
        async def structured[T: BaseModel](
            self, schema: type[T], messages: list[dict[str, str]], *, deadline: float | None = None
        ) -> T:
            return schema.model_validate(
                {
                    "matches": [
                        {
                            "job_id": "foreign"
                            if case == "wrong_job"
                            else result().jobs[0].job.job_id,
                            "exclusion_id": "foreign" if case == "wrong_rule" else "sales",
                            "decision": "unknown" if case == "unknown" else "matches",
                            "quotes": [] if case == "unknown" else ["invented quote"],
                        }
                    ]
                }
            )

    async def check() -> None:
        service = ResultFeedbackService(Provider())
        job = result().jobs[0].job
        preferences = ResultPreferences(
            exclusions=[
                ResultExclusion(
                    exclusion_id="sales",
                    description="Exclude sales",
                    user_message_id="rule-message",
                )
            ]
        )
        if case == "unknown":
            hidden, cache = await service.classify(
                [job], preferences, {}, deadline=asyncio.get_running_loop().time() + 10
            )
            assert hidden == set()
            assert cache[match_key(job, "sales", "Exclude sales")]["decision"] == "unknown"
        else:
            with pytest.raises(ModelServiceError) as error:
                await service.classify(
                    [job], preferences, {}, deadline=asyncio.get_running_loop().time() + 10
                )
            assert error.value.code == "model_output"

    asyncio.run(check())


def test_feedback_and_follow_up_http_contract_permissions_and_generated_schema() -> None:
    dataset = load_dataset()
    with AuthenticatedClient(create_replay_app()) as client:
        created = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "create-feedback",
                **dataset.profile_input("data-analyst-internship"),
            },
        ).json()
        session_id = created["session_id"]
        summary = settled(client, session_id)
        client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "confirm",
                "expected_revision": summary["revision"],
                "action": "confirm_search",
            },
        )
        completed = settled(client, session_id)
        job_id = completed["recommendation"]["jobs"][0]["job"]["job_id"]
        reaction = client.post(
            f"/api/v1/sessions/{session_id}/feedback",
            json={
                "request_id": "feedback",
                "expected_revision": completed["revision"],
                "job_id": job_id,
                "reaction": "not_interested",
            },
        )
        assert reaction.status_code == 200
        assert reaction.json()["hidden_job_ids"] == [job_id]
        bad = client.post(
            f"/api/v1/sessions/{session_id}/follow-up",
            json={
                "request_id": "bad-action",
                "expected_revision": reaction.json()["revision"],
                "action": "answer",
                "message": "not an answer",
            },
        )
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_follow_up_input"
        missing = client.post(
            f"/api/v1/sessions/{session_id}/feedback",
            json={
                "request_id": "foreign-job",
                "expected_revision": reaction.json()["revision"],
                "job_id": "not-in-search",
                "reaction": None,
            },
        )
        assert (
            missing.status_code == 404 and missing.json()["detail"]["code"] == "job_not_in_session"
        )
        message = client.post(
            f"/api/v1/sessions/{session_id}/follow-up",
            json={
                "request_id": "question",
                "expected_revision": reaction.json()["revision"],
                "action": "message",
                "job_id": job_id,
                "message": "What salary does this job offer?",
            },
        )
        assert message.status_code == 202
        final = settled(client, session_id)
        assert final["outcome"] == "completed" and final["operation_kind"] == "follow_up"
        assert final["job_feedback"][0]["reason"] is None
        assert all("job_id" in entry for entry in final["conversation"])
        assert final["conversation"][-2]["job_id"] == job_id
        snapshot = client.get(f"/api/v1/sessions/{session_id}/events").text
        assert '"operation_kind":"follow_up"' in snapshot
        assert job_id in snapshot
        schema = client.get("/openapi.json").json()
        body = schema["paths"]["/api/v1/sessions/{session_id}/follow-up"]["post"]["requestBody"][
            "content"
        ]["application/json"]["schema"]
        assert body["discriminator"]["propertyName"] == "action"
        assert (
            "maxItems"
            not in schema["components"]["schemas"]["RecommendationResult"]["properties"]["jobs"]
        )
        assert "job_feedback" in schema["components"]["schemas"]["SessionResponse"]["properties"]


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "message", "message": "question", "answers": []},
        {"action": "find_similar", "job_id": "job", "skipped_question_ids": []},
        {"action": "answer", "job_id": "job"},
    ],
)
def test_action_models_reject_fields_from_other_actions(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(SessionFollowUpRequest).validate_python(
            {"request_id": "request", "expected_revision": 0, **payload}
        )


def test_follow_up_search_snapshots_preserve_twenty_old_jobs_and_failed_search_retries_remaining_count() -> (
    None
):
    class Provider(RecordingProvider):
        fail_decision = True

        async def tool_turn(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            *,
            deadline: float | None = None,
        ) -> ToolTurn:
            import json

            observation = json.loads(messages[-1]["content"])
            if observation["matched_count"] and self.fail_decision:
                raise ModelServiceError("model_transport")
            return await super().tool_turn(messages, tools, deadline=deadline)

    async def check() -> None:
        provider = Provider()
        search = SnapshotSearch(22)
        graph = build_live_graph(
            InMemorySaver(), provider, search, assessment_factory=lambda _: FollowUpAssessment()
        )
        async with service_for(graph) as service:
            record = service.sessions["results"]
            record.state.update(recommendation=result(20), profile=profile(20))
            refresh_hidden(record.state)
            old_ids = set(record.state["result_order"])
            queue = await service.subscribe("results")
            await queue.get()
            request = FindSimilarRequest(
                request_id="more",
                expected_revision=1,
                action="find_similar",
                job_id=record.state["result_order"][0],
                message="I like Python",
            )
            await service.follow_up("results", request)
            failed = await finish(service)
            assert failed.outcome == "failed" and failed.retryable
            assert failed.recommendation is not None
            assert len(failed.recommendation.jobs + failed.recommendation.pending_jobs) == 22
            assert failed.result_preferences.preferred_features == ["Python"]
            assert failed.profile.search_options.result_count == 20
            while not queue.empty():
                snapshot = queue.get_nowait()
                assert snapshot is not None and snapshot.recommendation is not None
                assert old_ids <= {
                    item.job.job_id
                    for item in snapshot.recommendation.jobs + snapshot.recommendation.pending_jobs
                }
            provider.fail_decision = False
            search.rows = [raw(index) for index in range(26)]
            await service.resume(
                "results",
                SessionResumeRequest(request_id="retry-more", expected_revision=2, action="retry"),
            )
            completed = await finish(service)
            assert completed.outcome == "completed"
            assert completed.recommendation is not None
            assert len(completed.recommendation.jobs + completed.recommendation.pending_jobs) == 25
            assert set(completed.result_order[:20]) == old_ids
            assert [
                message.text for message in completed.conversation if message.role == "user"
            ] == [request.message]
            assert completed.result_preferences.preferred_features == ["Python"]
            assert await service.follow_up("results", request) == completed

    asyncio.run(check())


def test_stop_follow_up_search_keeps_old_and_new_results() -> None:
    class Provider(RecordingProvider):
        def __init__(self) -> None:
            super().__init__()
            self.waiting = asyncio.Event()

        async def tool_turn(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            *,
            deadline: float | None = None,
        ) -> ToolTurn:
            import json

            if json.loads(messages[-1]["content"])["matched_count"]:
                self.waiting.set()
                await asyncio.Event().wait()
            return await super().tool_turn(messages, tools, deadline=deadline)

    async def check() -> None:
        provider = Provider()
        graph = build_live_graph(
            InMemorySaver(),
            provider,
            SnapshotSearch(4),
            assessment_factory=lambda _: FollowUpAssessment(),
        )
        async with service_for(graph) as service:
            original = await service.get("results")
            assert original.recommendation is not None
            old_ids = set(original.result_order)
            await service.follow_up(
                "results",
                FindSimilarRequest(
                    request_id="stop-more",
                    expected_revision=1,
                    action="find_similar",
                    job_id=original.result_order[0],
                ),
            )
            await asyncio.wait_for(provider.waiting.wait(), 2)
            running = await service.get("results")
            assert running.run_id is not None
            request = SessionStopRequest(
                request_id="stop", expected_revision=2, run_id=running.run_id
            )
            await service.stop("results", request)
            completed = await finish(service)
            assert completed.outcome == "completed" and completed.stop_reason == "user_stopped"
            assert completed.recommendation is not None
            assert len(completed.result_order) == 4
            assert old_ids <= set(completed.result_order)
            assert await service.stop("results", request) == completed
            with pytest.raises(SessionOperationError) as error:
                await service.feedback(
                    "results",
                    SessionFeedbackRequest(
                        request_id="stop",
                        expected_revision=completed.revision,
                        job_id=completed.result_order[0],
                        reaction="interested",
                    ),
                )
            assert error.value.code == "request_conflict"

    asyncio.run(check())


def test_explicit_exclusions_filter_existing_and_new_jobs_and_cancellation_keeps_direct_dislike() -> (
    None
):
    async def check() -> None:
        provider = RecordingProvider()
        search = SnapshotSearch(8)
        search.rows[2].title = "Sales Data Analyst"
        graph = build_live_graph(
            InMemorySaver(), provider, search, assessment_factory=lambda _: FollowUpAssessment()
        )
        async with service_for(graph) as service:
            first = service.sessions["results"].state["recommendation"].jobs[0].job
            first.title = "Sales Data Analyst"
            await service.feedback(
                "results",
                SessionFeedbackRequest(
                    request_id="dislike-rule",
                    expected_revision=1,
                    job_id=first.job_id,
                    reaction="not_interested",
                ),
            )
            await service.follow_up(
                "results",
                FollowUpMessageRequest(
                    request_id="exclude",
                    expected_revision=2,
                    action="message",
                    message="Exclude sales roles",
                ),
            )
            filtered = await finish(service)
            assert filtered.hidden_job_ids == [first.job_id]
            assert search.requests == []
            assert {reason.kind for reason in filtered.hidden_job_reasons} == {
                "not_interested",
                "excluded",
            }
            await service.follow_up(
                "results",
                FindSimilarRequest(
                    request_id="more-filtered",
                    expected_revision=3,
                    action="find_similar",
                    job_id=first.job_id,
                ),
            )
            completed = await finish(service)
            assert completed.outcome == "completed"
            assert len(completed.hidden_job_ids) == 2
            assert completed.recommendation is not None
            kept = completed.recommendation.jobs + completed.recommendation.pending_jobs
            assert all(
                item.job.job_id in completed.hidden_job_ids
                for item in kept
                if "Sales" in item.job.title
            )
            new_visible = {
                item.job.job_id for item in kept if item.job.job_id not in completed.hidden_job_ids
            } - set(filtered.result_order)
            assert len(new_visible) == 5
            await service.follow_up(
                "results",
                FollowUpMessageRequest(
                    request_id="cancel",
                    expected_revision=4,
                    action="message",
                    message="Cancel the sales exclusion",
                ),
            )
            cancelled = await finish(service)
            assert cancelled.result_preferences.exclusions == []
            assert cancelled.hidden_job_ids == [first.job_id]
            assert all(reason.kind == "not_interested" for reason in cancelled.hidden_job_reasons)
            assert service.sessions["results"].state["exclusion_matches"] == {}

    asyncio.run(check())


def test_exclusion_cache_reuses_matches_and_invalidates_changed_job_content() -> None:
    async def check() -> None:
        provider = RecordingProvider()
        jobs = [result().jobs[0].job.model_copy(update={"title": "Sales Assistant"})]
        preferences = ResultPreferences(
            exclusions=[
                ResultExclusion(
                    exclusion_id="sales",
                    description="Exclude sales",
                    user_message_id="rule-message",
                )
            ]
        )
        service = ResultFeedbackService(provider)
        blocked, cache = await service.classify(
            jobs, preferences, {}, deadline=asyncio.get_running_loop().time() + 10
        )
        assert blocked == {jobs[0].job_id}
        _, same = await service.classify(
            jobs, preferences, cache, deadline=asyncio.get_running_loop().time() + 10
        )
        assert same == cache
        assert provider.schemas == ["ExclusionMatches"]
        changed = jobs[0].model_copy(update={"title": "Data Analyst"})
        blocked, changed_cache = await service.classify(
            [changed], preferences, cache, deadline=asyncio.get_running_loop().time() + 10
        )
        assert blocked == set()
        assert set(cache).isdisjoint(changed_cache)
        assert provider.schemas == ["ExclusionMatches", "ExclusionMatches"]

    asyncio.run(check())


def test_normalized_employment_exclusion_uses_existing_condition_without_a_model_call() -> None:
    async def check() -> None:
        provider = RecordingProvider()
        job = result().jobs[0].job
        preferences = ResultPreferences(
            exclusions=[
                ResultExclusion(
                    exclusion_id="internship",
                    description="Exclude internships",
                    user_message_id="rule-message",
                )
            ]
        )
        blocked, cache = await ResultFeedbackService(provider).classify(
            [job],
            preferences,
            {},
            deadline=asyncio.get_running_loop().time() + 10,
            conditions={"internship": {"employment": {"excluded": ["internship"]}}},
        )
        assert blocked == {job.job_id}
        assert provider.schemas == []
        assert cache[match_key(job, "internship", "Exclude internships")]["quotes"] == [
            "internship"
        ]

    asyncio.run(check())


def test_follow_up_provider_is_closed_on_acceptance_failure_and_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    class Provider(RecordingProvider):
        closed = 0

        async def aclose(self) -> None:
            self.closed += 1

    class Settings:
        settings = SimpleNamespace(concurrent_user_limit=2, concurrent_total_limit=2)

        def __init__(self, provider: Provider) -> None:
            self.provider = provider

        async def prepare(self, owner: str) -> Any:
            return SimpleNamespace(provider=self.provider, uses_server=False)

    async def check() -> None:
        provider = Provider()
        saver = InMemorySaver()
        graph = build_live_graph(saver, provider, SnapshotSearch())
        async with service_for(graph) as service:
            service.model_settings = Settings(provider)
            service.graph_factory = lambda model: build_live_graph(saver, model, SnapshotSearch())
            persist = service._persist

            async def fail(*args: Any, **kwargs: Any) -> None:
                raise RuntimeError("acceptance storage failed")

            before = await service.get("results")
            request = FollowUpMessageRequest(
                request_id="accepted-model",
                expected_revision=1,
                action="message",
                message="Is the salary stated?",
            )
            monkeypatch.setattr(service, "_persist", fail)
            with pytest.raises(RuntimeError, match="acceptance storage failed"):
                await service.follow_up("results", request)
            assert provider.closed == 1
            assert await service.get("results") == before
            monkeypatch.setattr(service, "_persist", persist)
            await service.follow_up("results", request)
            assert (await finish(service)).outcome == "completed"
            assert provider.closed == 2
            assert service.sessions["results"].operation_models is None

    asyncio.run(check())


def test_follow_up_security_uses_existing_account_origin_and_csrf_checks() -> None:
    from jobscout.config import get_settings

    dataset = load_dataset()
    with AuthenticatedClient(create_replay_app()) as client:
        created = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "security-search",
                **dataset.profile_input("data-analyst-internship"),
            },
        ).json()
        session_id = created["session_id"]
        summary = settled(client, session_id)
        client.post(
            f"/api/v1/sessions/{session_id}/resume",
            json={
                "request_id": "confirm-security",
                "expected_revision": summary["revision"],
                "action": "confirm_search",
            },
        )
        completed = settled(client, session_id)
        for path, payload in [
            ("feedback", {"job_id": completed["result_order"][0], "reaction": "interested"}),
            ("follow-up", {"action": "message", "message": "Is salary known?"}),
        ]:
            data = {
                "request_id": f"secure-{path}",
                "expected_revision": completed["revision"],
                **payload,
            }
            invalid_origin = client.post(
                f"/api/v1/sessions/{session_id}/{path}",
                json=data,
                headers={"Origin": "https://other.example"},
            )
            assert (
                invalid_origin.status_code == 403
                and invalid_origin.json()["detail"]["code"] == "invalid_origin"
            )
            invalid_csrf = client.post(
                f"/api/v1/sessions/{session_id}/{path}",
                json=data,
                headers={"X-CSRF-Token": "invalid"},
            )
            assert (
                invalid_csrf.status_code == 403
                and invalid_csrf.json()["detail"]["code"] == "invalid_csrf_token"
            )
        client.cookies.clear()
        unauthenticated = client.post(
            f"/api/v1/sessions/{session_id}/follow-up",
            json={
                "request_id": "not-signed-in",
                "expected_revision": completed["revision"],
                "action": "message",
                "message": "Question",
            },
            headers={"Origin": get_settings().public_origin},
        )
        assert (
            unauthenticated.status_code == 401
            and unauthenticated.json()["detail"]["code"] == "authentication_required"
        )
