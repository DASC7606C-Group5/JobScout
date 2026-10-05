"""Offline production graph tests: waits, confirmation, limits and session isolation."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from jobscout.graph.live import build_live_graph
from jobscout.graph.state import AgentState
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import JobPosting
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.schemas.search import SearchRequest
from jobscout.services.conversation_service import (
    AnswerInterpretation,
    ConversationService,
    ProfileExtraction,
    QuestionGeneration,
)
from jobscout.services.job_retrieval.models import RawJob, SearchResult, SourceOutcome
from jobscout.services.llm_service import LLMProvider, ModelServiceError
from jobscout.services.replay_service import ReplayProvider


class FakeProvider(ReplayProvider):
    def __init__(self, *, extraction: dict[str, Any] | None = None, optional: bool = False) -> None:
        self.extraction = extraction or {"skills": ["Python"]}
        self.optional = optional
        self.calls: list[str] = []
        self.fail: str | None = None
        self.changes: list[dict[str, Any]] = []
        self.intent = "answer"
        self.question_fields: list[list[str]] = []
        self.system_prompts: list[str] = []

    async def structured[SchemaT: BaseModel](
        self,
        schema: type[SchemaT],
        messages: list[dict[str, str]],
        *,
        deadline: float | None = None,
    ) -> SchemaT:
        import json

        self.calls.append(schema.__name__)
        self.system_prompts.append(messages[0]["content"])
        if schema.__name__ == self.fail:
            raise ModelServiceError("model_output")
        data: dict[str, Any] = {}
        prompt = json.loads(messages[-1]["content"])
        if schema is ProfileExtraction:
            data = self.extraction
        elif schema is QuestionGeneration:
            fields = prompt["required_fields"] or (
                prompt["allowed_fields"][:1] if self.optional else []
            )
            self.question_fields.append(fields)
            data = {
                "questions": [
                    {
                        "field": field,
                        "question": f"Please provide {field}",
                        "reason": "This will help refine your search.",
                    }
                    for field in fields[:3]
                ]
            }
        elif schema is AnswerInterpretation:
            data = {"intent": self.intent, "changes": self.changes}
        else:
            return await super().structured(schema, messages, deadline=deadline)
        return schema.model_validate(data)


class FakeSearch:
    def __init__(self, rounds: list[SearchResult] | None = None) -> None:
        self.rounds = rounds or [
            SearchResult(
                outcomes=[
                    SourceOutcome(target_direction="data analyst", source="jobsdb", status="empty")
                ]
            )
        ]
        self.calls: list[list[SearchRequest]] = []
        self.timeouts: list[float] = []

    async def search_many_async(
        self, requests: Sequence[SearchRequest], *, timeout: float = 60
    ) -> SearchResult:
        self.calls.append(list(requests))
        self.timeouts.append(timeout)
        await asyncio.sleep(0.002)
        return self.rounds[min(len(self.calls) - 1, len(self.rounds) - 1)]


class FakeAssessment:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[JobPosting], dict[str, str], float | None]] = []
        self.search_ids: list[str] = []

    async def begin_search(self, search_id: str) -> None:
        self.search_ids.append(search_id)

    async def cleanup_session(self, session_id: str) -> None:
        self.calls.clear()

    def import_cache(self, snapshot: object, session_id: str) -> None:
        pass

    def export_cache(self) -> dict[str, object]:
        return {}

    async def assess(
        self,
        profile: UserProfile,
        jobs: list[JobPosting],
        profile_documents: dict[str, str],
        session_id: str,
        deadline: float | None = None,
    ) -> RecommendationResult:
        self.calls.append((session_id, jobs, profile_documents, deadline))
        return RecommendationResult(
            session_id=session_id,
            generated_at=datetime.now(UTC),
            jobs=[RecommendationItem(job=job) for job in jobs],
        )


def initial(**overrides: Any) -> AgentState:
    data: dict[str, Any] = {
        "request_id": "initial-request",
        "description": "I know Python and have a data project.",
        "target_directions": ["data analyst"],
        "preferences": {"location": "Hong Kong", "employment_type": "internship"},
    }
    data.update(overrides)
    return {"session_id": "s1", "revision": 1, "input_data": data}


def resume(revision: int = 1, **overrides: Any) -> Command[Any]:
    payload = {
        "request_id": f"request-{revision}",
        "expected_revision": revision,
        "message": "",
        "answers": [],
        "skipped_question_ids": [],
        "action": "answer",
        "profile_updates": {},
    }
    payload.update(overrides)
    return Command(resume=payload)


def configuration(session: str = "s1") -> RunnableConfig:
    return {"configurable": {"thread_id": session}, "recursion_limit": 60}


def raw(index: int = 1) -> RawJob:
    return RawJob(
        source="jobsdb",
        source_url=f"https://example.test/jobs/{index}",
        fetched_at=datetime.now(UTC),
        target_direction="data analyst",
        source_job_id=str(index),
        title=f"Data analyst {index}",
        company=f"Company {index}",
        location="Hong Kong",
        employment_type="internship",
        description="Requirements\nPython\nResponsibilities\nAnalyze data",
        raw_payload={},
    )


def setup(
    provider: FakeProvider | None = None, search: FakeSearch | None = None
) -> tuple[Any, FakeProvider, FakeSearch, list[FakeAssessment]]:
    provider = provider or FakeProvider()
    search = search or FakeSearch()
    instances: list[FakeAssessment] = []

    def factory(_: LLMProvider) -> FakeAssessment:
        service = FakeAssessment()
        instances.append(service)
        return service

    return (
        build_live_graph(InMemorySaver(), provider, search, assessment_factory=factory),
        provider,
        search,
        instances,
    )


def test_complete_input_waits_and_confirmation_does_not_repeat_extraction() -> None:
    async def scenario() -> None:
        graph, provider, search, instances = setup()
        state = await graph.ainvoke(initial(), configuration())
        assert state["current_stage"] == "confirm"
        assert state["search_summary"].ready
        assert not search.calls
        before = list(provider.calls)
        assert (await graph.aget_state(configuration())).next == ("await_confirmation",)
        result = await graph.ainvoke(resume(4, action="confirm_search"), configuration())
        assert provider.calls.count("ProfileExtraction") == 1
        assert provider.calls.count("QuestionGeneration") == 1
        assert before == ["ProfileExtraction", "PreferenceMeaning", "QuestionGeneration"]
        assert "AnswerInterpretation" not in provider.calls
        assert [batch[0].keywords for batch in search.calls] == [
            ["data analyst"],
            ["data analyst jobs"],
        ]
        assert result["current_stage"] == "completed"
        assert result["search_summary"].confirmed
        assert result["revision"] == result["search_summary"].revision == 5
        assert result["recommendation"].introduction
        assert len(instances) == 1
        assert instances[0].calls == []
        assert instances[0].search_ids == ["s1:5"]
        assert 0 < search.timeouts[0] <= 60

    asyncio.run(scenario())


def test_changed_result_target_requires_confirmation_and_reaches_the_confirmed_count() -> None:
    async def scenario() -> None:
        graph, _, search, _ = setup(
            search=FakeSearch([SearchResult(raw_jobs=[raw(i) for i in range(25)])])
        )
        original = await graph.ainvoke(initial(), configuration())
        assert original["search_summary"].profile.search_options.result_count == 10
        edited = await graph.ainvoke(
            resume(1, action="confirm_search", search_options={"result_count": 20}), configuration()
        )
        assert edited["current_stage"] == "confirm"
        assert edited["search_summary"].profile.search_options.result_count == 20
        assert not edited["search_summary"].confirmed
        assert edited["run_id"] is None
        assert not search.calls
        result = await graph.ainvoke(resume(2, action="confirm_search"), configuration())
        assert result["stop_reason"] == "target_reached"
        assert len(result["recommendation"].jobs) == 20
        assert result["confirmed_profile"].search_options.result_count == 20

    asyncio.run(scenario())


def test_resume_only_and_missing_fields_are_asked_in_at_most_three_questions() -> None:
    async def scenario() -> None:
        graph, provider, search, _ = setup()
        state = await graph.ainvoke(
            initial(
                description="",
                resume={"name": "resume.txt", "text": "Skills: Python"},
                target_directions=[],
                preferences={},
            ),
            configuration(),
        )
        questions = state["clarification_questions"]
        assert len(questions) == 3
        assert state["current_stage"] == "clarify"
        values = {
            "target_directions": ["data analyst", "backend engineer"],
            "preferences.location": "不限",
            "preferences.employment_type": "不限",
        }
        answers = [{"question_id": q.question_id, "value": values[q.field]} for q in questions]
        state = await graph.ainvoke(resume(1, answers=answers), configuration())
        assert state["search_summary"].ready
        assert state["profile"].source.resume
        assert state["profile"].preferences.location_unrestricted
        assert state["profile"].preferences.employment_type_unrestricted
        assert provider.calls.count("ProfileExtraction") == 1
        assert not search.calls

    asyncio.run(scenario())


def test_two_unsuccessful_required_attempts_offer_direct_editing() -> None:
    async def scenario() -> None:
        graph, provider, _, _ = setup()
        state = await graph.ainvoke(initial(target_directions=[]), configuration())
        for revision in (1, 2):
            assert state["current_stage"] == "clarify"
            state = await graph.ainvoke(resume(revision), configuration())
        assert state["current_stage"] == "confirm"
        assert not state["search_summary"].ready
        assert state["direct_edit_fields"] == ["target_directions"]
        assert provider.calls.count("QuestionGeneration") == 2
        state = await graph.ainvoke(
            resume(3, profile_updates={"target_directions": ["data analyst"]}), configuration()
        )
        assert state["search_summary"].ready
        assert not state["search_summary"].confirmed

    asyncio.run(scenario())


def test_three_optional_rounds_and_skipped_fields_never_repeat() -> None:
    async def scenario() -> None:
        graph, provider, _, _ = setup(FakeProvider(optional=True))
        state = await graph.ainvoke(initial(), configuration())
        asked: list[str] = []
        for revision in (1, 2, 3):
            question = state["clarification_questions"][0]
            assert not question.required
            asked.append(question.field)
            state = await graph.ainvoke(
                resume(revision, skipped_question_ids=[question.question_id]), configuration()
            )
            submitted = state["conversation"][-2]
            assert submitted.responses[0].label == question.question
            assert submitted.responses[0].status == "skipped"
            assert submitted.responses[0].value == "Skipped"
        assert len(set(asked)) == 3
        assert state["current_stage"] == "confirm"
        assert state["optional_rounds"] == 3
        assert provider.calls.count("QuestionGeneration") == 3

    asyncio.run(scenario())


def test_four_directions_can_be_confirmed_and_searched_without_dropping_choices() -> None:
    async def scenario() -> None:
        graph, _, search, _ = setup()
        directions = ["data analyst", "backend engineer", "designer", "product manager"]
        state = await graph.ainvoke(initial(target_directions=directions), configuration())
        assert state["profile"].target_directions == directions
        assert state["current_stage"] == "confirm"
        assert state["search_summary"].ready
        assert "target_directions" not in state["profile"].missing_required_fields
        assert not search.calls
        result = await graph.ainvoke(resume(4, action="confirm_search"), configuration())
        assert result["current_stage"] == "completed"
        assert result["profile"].target_directions == directions
        assert {request.target_direction for batch in search.calls for request in batch} == set(
            directions
        )

    asyncio.run(scenario())


def test_unsupported_location_and_no_material_cannot_search() -> None:
    async def scenario() -> None:
        graph, provider, search, _ = setup()
        state = await graph.ainvoke(initial(description="", preferences={}), configuration())
        assert state["current_stage"] == "failed"
        assert not provider.calls
        assert state["input_data"]["description"] == ""
        state = await graph.ainvoke(
            initial(preferences={"location": "Berlin", "employment_type": "internship"}),
            configuration("s2"),
        )
        assert state["profile"].missing_required_fields == ["preferences.location"]
        assert not search.calls

    asyncio.run(scenario())


def test_free_text_correction_overrides_answers_but_editor_patch_has_final_priority() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        provider.changes = [
            {"field": "preferences.location", "value": "Shanghai"},
            {"field": "skills", "value": ["SQL"], "mode": "merge"},
        ]
        graph, _, search, _ = setup(provider)
        await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(
            resume(
                2,
                action="confirm_search",
                message="Actually Shanghai and also SQL",
                profile_updates={"preferences.location": "Beijing"},
            ),
            configuration(),
        )
        assert state["profile"].preferences.location == "Beijing"
        assert state["profile"].skills == ["Python", "SQL"]
        assert state["current_stage"] == "confirm"
        assert state["revision"] == state["search_summary"].revision == 3
        assert not state["search_summary"].confirmed
        assert not search.calls
        assert provider.calls.count("AnswerInterpretation") == 1
        provider.changes = []
        provider.intent = "confirm_search"
        state = await graph.ainvoke(resume(3, message="确认搜索"), configuration())
        assert state["current_stage"] == "completed"
        assert all(
            request.location_ref is not None and request.location_ref.id == "cn:530"
            for requests in search.calls
            for request in requests
        )
        assert provider.calls.count("AnswerInterpretation") == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("retry_thread", ["s1", "s1:2"])
def test_profile_failure_retains_input_and_clears_errors_on_retry(retry_thread: str) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        provider.fail = "ProfileExtraction"
        graph, _, _, _ = setup(provider)
        state = await graph.ainvoke(initial(), configuration())
        assert state["current_stage"] == "failed" and state["retryable"]
        assert state["input_data"] == initial()["input_data"]
        provider.fail = None
        result = await graph.ainvoke(
            {**state, "command": resume(1, action="retry").resume, "revision": 2},
            configuration(retry_thread),
        )
        assert result["current_stage"] == "confirm"
        assert result["revision"] == result["search_summary"].revision == 2
        assert result["errors"] == []
        assert result["command"] is None
        assert provider.calls.count("ProfileExtraction") == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("retry_thread", ["s1", "s1:3"])
def test_failed_search_retry_clears_reducer_errors_without_duplicate_history(
    retry_thread: str,
) -> None:
    async def scenario() -> None:
        search = FakeSearch(
            [
                SearchResult(
                    errors=[
                        WorkflowError(code="SOURCE_BLOCKED", message="blocked", stage="search")
                    ],
                    warnings=["first attempt warning"],
                    outcomes=[
                        SourceOutcome(
                            target_direction="data analyst", source="jobsdb", status="blocked"
                        )
                    ],
                ),
                SearchResult(raw_jobs=[raw(index) for index in range(5)]),
            ]
        )
        graph, _, _, _ = setup(search=search)
        await graph.ainvoke(initial(), configuration())
        failed = await graph.ainvoke(resume(1, action="confirm_search"), configuration())
        assert failed["current_stage"] == "failed"
        assert failed["errors"] and failed["warnings"]
        history = failed["conversation"]
        retried = await graph.ainvoke(
            {**failed, "command": resume(2, action="retry").resume, "revision": 3},
            configuration(retry_thread),
        )
        assert retried["current_stage"] == "confirm"
        assert retried["errors"] == retried["warnings"] == []
        assert retried["command"] is None
        assert retried["recommendation"] is None
        assert retried["conversation"][: len(history)] == history
        assert len(retried["conversation"]) == len(history) + 2
        assert len({message.message_id for message in retried["conversation"]}) == len(
            retried["conversation"]
        )
        completed = await graph.ainvoke(
            resume(3, action="confirm_search"), configuration(retry_thread)
        )
        assert completed["current_stage"] == "completed"
        assert completed["errors"] == []
        assert "first attempt warning" not in completed["warnings"]
        assert completed["command"] is None
        assert completed["revision"] == completed["search_summary"].revision == 4
        assert [batch[0].page for batch in search.calls[:3]] == [1, 1, 2]
        assert completed["stop_reason"] == "budget_exhausted"
        assert {item.job.source_url for item in completed["recommendation"].jobs} == {
            f"https://example.test/jobs/{index}" for index in range(5)
        }

    asyncio.run(scenario())


def test_source_failure_is_nonfatal_with_successful_results() -> None:
    async def scenario() -> None:
        found = SearchResult(
            raw_jobs=[raw(i) for i in range(6)],
            errors=[WorkflowError(code="SOURCE_BLOCKED", message="blocked", stage="search")],
            outcomes=[
                SourceOutcome(target_direction="data analyst", source="jobsdb", status="ok"),
                SourceOutcome(target_direction="data analyst", source="liepin", status="blocked"),
            ],
        )
        graph, _, search, assessment_services = setup(search=FakeSearch([found]))
        await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(resume(action="confirm_search"), configuration())
        assert state["current_stage"] == "completed"
        assert not state.get("errors")
        assert len(state["recommendation"].jobs) == 6
        assert {(outcome.source, outcome.status) for outcome in state["source_outcomes"]} == {
            ("jobsdb", "ok"),
            ("liepin", "blocked"),
        }
        assert state["stop_reason"] == "budget_exhausted"
        assert all(job.source_documents for job in assessment_services[0].calls[0][1])

    asyncio.run(scenario())


def test_total_source_failure_is_not_reported_as_empty_success() -> None:
    async def scenario() -> None:
        search = FakeSearch(
            [
                SearchResult(
                    outcomes=[
                        SourceOutcome(
                            target_direction="data analyst", source="jobsdb", status="blocked"
                        )
                    ]
                )
            ]
        )
        graph, _, _, _ = setup(search=search)
        await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(resume(action="confirm_search"), configuration())
        assert state["current_stage"] == "failed"
        assert state["errors"][0].code == "search_unavailable"

    asyncio.run(scenario())


def test_target_stops_completed_analysis_and_no_implicit_skill_keywords() -> None:
    async def scenario() -> None:
        search = FakeSearch([SearchResult(raw_jobs=[raw(i) for i in range(30)])])
        graph, _, _, instances = setup(search=search)
        await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(resume(action="confirm_search"), configuration())
        assert len(state["analyzed_job_ids"]) == 10
        assert len(instances[0].calls[0][1]) == 10
        assert all(
            request.keywords == ["data analyst"] for batch in search.calls for request in batch
        )
        assert instances[0].calls[0][3] is not None

    asyncio.run(scenario())


def test_assessment_instances_are_session_scoped() -> None:
    async def scenario() -> None:
        graph, _, _, instances = setup(search=FakeSearch([SearchResult(raw_jobs=[raw()])]))
        await graph.ainvoke(initial(), configuration())
        second = initial()
        second["session_id"] = "s2"
        await graph.ainvoke(second, configuration("s2"))
        await asyncio.gather(
            graph.ainvoke(resume(action="confirm_search"), configuration()),
            graph.ainvoke(resume(action="confirm_search"), configuration("s2")),
        )
        assert len(instances) == 2
        assert {frozenset(call[0] for call in service.calls) for service in instances} == {
            frozenset({"s1"}),
            frozenset({"s2"}),
        }

    asyncio.run(scenario())


def test_cleanup_session_releases_only_requested_cache_and_is_idempotent() -> None:
    import gc
    import inspect
    import weakref

    async def scenario() -> None:
        instances: list[weakref.ReferenceType[FakeAssessment]] = []

        def factory(_: LLMProvider) -> FakeAssessment:
            instance = FakeAssessment()
            instances.append(weakref.ref(instance))
            return instance

        checkpointer = InMemorySaver()
        graph = build_live_graph(
            checkpointer, FakeProvider(), FakeSearch(), assessment_factory=factory
        )
        for session in ("s1", "s2"):
            state = initial()
            state["session_id"] = session
            await graph.ainvoke(state, configuration(session))
            await graph.ainvoke(
                resume(action="confirm_search"), configuration(session), interrupt_before=["plan"]
            )
        assert all(reference() is not None for reference in instances)
        cleanup = getattr(graph, "cleanup_session", None)
        assert callable(cleanup)
        assert inspect.iscoroutinefunction(cleanup)
        await cleanup("s1")
        await cleanup("s1")
        await cleanup("unknown")
        await checkpointer.adelete_thread("s1")
        gc.collect()
        assert instances[0]() is None
        assert instances[1]() is not None
        assert not (await graph.aget_state(configuration("s1"))).values
        await graph.ainvoke(None, configuration("s2"))
        gc.collect()
        assert instances[1]() is not None
        await cleanup("s2")
        gc.collect()
        assert instances[1]() is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "rotate_threads,rebuild_graph", [(False, False), (True, False), (True, True)]
)
def test_confirmed_search_resets_candidate_budget_but_reuses_session_jd_cache(
    rotate_threads: bool,
    rebuild_graph: bool,
) -> None:
    import json

    from jobscout.services.job_assessment_service import (
        JDAnalysisBatch,
        JobAssessmentService,
        MatchingBatch,
    )

    class AssessmentProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.jd_calls = 0
            self.match_calls = 0
            self.match_profiles: list[list[str]] = []

        async def structured[SchemaT: BaseModel](
            self,
            schema: type[SchemaT],
            messages: list[dict[str, str]],
            *,
            deadline: float | None = None,
        ) -> SchemaT:
            payload = json.loads(messages[-1]["content"])
            if schema is JDAnalysisBatch:
                self.jd_calls += 1
                response = await super().structured(schema, messages, deadline=deadline)
                data = response.model_dump()
                for row, job in zip(data["jobs"], payload["jobs"], strict=True):
                    row["requirements"] = [
                        {
                            "requirement_id": "python",
                            "text": "Python",
                            "category": "skill",
                            "source_quotes": [
                                {
                                    "document_id": job["documents"][0]["document_id"],
                                    "excerpt": "Python",
                                }
                            ],
                        }
                    ]
                return schema.model_validate(data)
            if schema is MatchingBatch:
                self.match_calls += 1
                self.match_profiles.append(
                    [
                        fact["text"]
                        for fact in payload["profile_facts"].values()
                        if fact["field"] == "skills"
                    ]
                )
                return schema.model_validate(
                    {
                        "jobs": [
                            {
                                "job_id": job["job_id"],
                                "matches": [
                                    {
                                        "requirement_id": requirement["requirement_id"],
                                        "level": "not_documented",
                                    }
                                    for requirement in job["requirements"]
                                ],
                            }
                            for job in payload["jobs"]
                        ]
                    }
                )
            return await super().structured(schema, messages, deadline=deadline)

    async def scenario() -> None:
        provider = AssessmentProvider()
        search = FakeSearch(
            [
                SearchResult(raw_jobs=[raw(i) for i in range(20)]),
                SearchResult(raw_jobs=[raw(i) for i in range(100, 120)]),
            ]
        )
        services: list[JobAssessmentService] = []

        def factory(model: LLMProvider) -> JobAssessmentService:
            service = JobAssessmentService(model)
            services.append(service)
            return service

        saver = InMemorySaver()
        graph = build_live_graph(saver, provider, search, assessment_factory=factory)
        await graph.ainvoke(initial(search_options={"result_count": 20}), configuration())
        state = await graph.ainvoke(resume(1, action="confirm_search"), configuration())
        state = (await graph.aget_state(configuration())).values
        assert state["jd_cache"]["session_id"] == "s1"
        json.dumps(state["jd_cache"])
        first_ids = set(state["analyzed_job_ids"])
        assert services[0].analyzed_count == 20
        assert provider.jd_calls == provider.match_calls == 8
        for skills in (["SQL"], ["Java"]):
            if rebuild_graph:
                cleanup = getattr(graph, "cleanup_session", None)
                assert callable(cleanup)
                await cleanup("s1")
                graph = build_live_graph(saver, provider, search, assessment_factory=factory)
            command = resume(
                state["revision"], action="edit_conditions", profile_updates={"skills": skills}
            ).resume
            active_config = configuration(f"s1:{state['revision'] + 1}" if rotate_threads else "s1")
            state = await graph.ainvoke(
                cast(AgentState, {**state, "command": command, "revision": state["revision"] + 1}),
                active_config,
            )
            state = await graph.ainvoke(
                resume(state["revision"], action="confirm_search"), active_config
            )
            assert state["current_stage"] == "completed"
            assert len(state["analyzed_job_ids"]) == services[-1].analyzed_count == 20
            assert not first_ids.intersection(state["analyzed_job_ids"])
            assert state["profile"].skills == skills
        assert len(services) == (3 if rebuild_graph else 1)
        assert len(services[-1].cache) == 40
        assert provider.jd_calls == 16
        assert provider.match_calls == 24
        assert provider.match_profiles == [["Python"]] * 8 + [["SQL"]] * 8 + [["Java"]] * 8
        cleanup = getattr(graph, "cleanup_session", None)
        assert callable(cleanup)
        await cleanup("s1")
        assert all(service.cache == {} and service.analyzed_count == 0 for service in services)
        await cleanup("s1")

    asyncio.run(scenario())


def test_checkpoint_cache_from_another_session_is_ignored(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    async def scenario() -> None:
        saver = InMemorySaver()
        provider = FakeProvider()
        search = FakeSearch([SearchResult(raw_jobs=[raw(index) for index in range(5)])])
        graph = build_live_graph(saver, provider, search)
        await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(resume(1, action="confirm_search"), configuration())
        snapshot = {**state["jd_cache"], "session_id": "another-session"}
        cleanup = getattr(graph, "cleanup_session", None)
        assert callable(cleanup)
        await cleanup("s1")
        graph = build_live_graph(saver, provider, search)
        command = resume(2, action="edit_conditions").resume
        await graph.ainvoke(
            cast(AgentState, {**state, "jd_cache": snapshot, "command": command, "revision": 3}),
            configuration("s1:3"),
        )
        completed = await graph.ainvoke(resume(3, action="confirm_search"), configuration("s1:3"))
        assert completed["current_stage"] == "completed"
        assert completed["jd_cache"]["session_id"] == "s1"
        assert any(record.message == "workflow_cache_rejected" for record in caplog.records)

    caplog.set_level(logging.WARNING, logger="jobscout.graph.live")
    asyncio.run(scenario())


def test_stage_logs_only_contain_safe_metadata(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from jobscout.schemas.model import ModelUsage

    class TelemetryProvider(FakeProvider):
        @property
        def usage(self) -> ModelUsage:
            return ModelUsage(requests=len(self.calls), total_tokens=12)

    async def scenario() -> None:
        provider = TelemetryProvider()
        source = raw(1).model_copy(
            update={
                "description": "CONFIDENTIAL_JOB_TEXT",
                "source_url": "https://example.test/SECRET_SOURCE_LINK",
            }
        )
        search = FakeSearch(
            [
                SearchResult(
                    raw_jobs=[source],
                    outcomes=[
                        SourceOutcome(
                            target_direction="PRIVATE_DIRECTION",
                            source="PRIVATE_SOURCE",
                            status="ok",
                        )
                    ],
                )
            ]
        )
        graph, _, _, _ = setup(provider, search)
        await graph.ainvoke(
            initial(description="PRIVATE_RESUME_SENTINEL and API_KEY_SENTINEL"), configuration()
        )
        await graph.ainvoke(resume(1, action="confirm_search"), configuration())
        provider.fail = "ProfileExtraction"
        failed = initial(description="PRIVATE_FAILURE_INPUT")
        failed["session_id"] = "s-failure"
        await graph.ainvoke(failed, configuration("s-failure"))
        records = [
            record
            for record in caplog.records
            if record.name == "jobscout.graph.live" and record.message == "workflow_stage"
        ]
        assert {vars(record)["stage"] for record in records} >= {
            "extract",
            "validate",
            "search_agent",
            "failed",
        }
        assert all(
            vars(record)["elapsed_seconds"] >= 0 and not record.exc_info for record in records
        )
        assert any(vars(record)["error_codes"] == ["model_output"] for record in records)
        assert any(vars(record)["source_counts"].get("ok", 0) > 0 for record in records)
        assert any(
            vars(record)["model_usage_snapshot"].get("requests", 0) > 0 for record in records
        )
        serialized = repr([vars(record) for record in records])
        for secret in (
            "PRIVATE_RESUME_SENTINEL",
            "API_KEY_SENTINEL",
            "CONFIDENTIAL_JOB_TEXT",
            "SECRET_SOURCE_LINK",
            "PRIVATE_DIRECTION",
            "PRIVATE_SOURCE",
            "PRIVATE_FAILURE_INPUT",
        ):
            assert secret not in serialized

    caplog.set_level(logging.INFO, logger="jobscout.graph.live")
    asyncio.run(scenario())


def test_unavailable_analysis_preserves_source_vacancies_in_graph_results() -> None:
    async def scenario() -> None:
        search = FakeSearch([SearchResult(raw_jobs=[raw(i) for i in range(5)])])
        graph = build_live_graph(InMemorySaver(), FakeProvider(), search)
        await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(resume(action="confirm_search"), configuration())
        assert state["current_stage"] == "completed"
        assert {item.job.source_url for item in state["recommendation"].jobs} == {
            raw(index).source_url for index in range(5)
        }
        assert all(item.analysis_status == "unavailable" for item in state["recommendation"].jobs)
        assert all(item.matching_reasons == [] for item in state["recommendation"].jobs)
        assert state["recommendation"].introduction

    asyncio.run(scenario())


def test_completed_edit_restart_preserves_source_quotes_and_requires_confirmation() -> None:
    async def scenario() -> None:
        graph, provider, search, _ = setup()
        await graph.ainvoke(initial(), configuration())
        completed = await graph.ainvoke(resume(action="confirm_search"), configuration())
        before = len(search.calls)
        command = resume(
            completed["revision"],
            action="edit_conditions",
            profile_updates={"preferences.location": "Shanghai"},
        ).resume
        restarted = {
            **completed,
            "command": command,
            "current_stage": "edit_conditions",
            "revision": completed["revision"] + 1,
        }
        state = await graph.ainvoke(restarted, configuration())
        assert state["current_stage"] == "confirm"
        assert state["recommendation"] is None
        assert state["run_id"] is None
        assert state["progress_seq"] == 0
        assert state["progress"] == {}
        assert state["stop_reason"] is None
        assert state["confirmed_profile"] is None
        assert state["revision"] == state["search_summary"].revision == 3
        assert not state["search_summary"].confirmed
        assert state["profile"].preferences.location == "Shanghai"
        assert (
            state["profile_documents"][: len(completed["profile_documents"])]
            == completed["profile_documents"]
        )
        assert state["conversation"][: len(completed["conversation"])] == completed["conversation"]
        assert state["source_outcomes"] == []
        assert state["errors"] == []
        assert state["warnings"] == []
        assert state["command"] is None
        assert provider.calls.count("ProfileExtraction") == 1
        assert len(search.calls) == before
        final = await graph.ainvoke(resume(3, action="confirm_search"), configuration())
        assert final["revision"] == final["search_summary"].revision == 4
        assert final["current_stage"] == "completed"
        assert all(
            request.location_ref is not None and request.location_ref.id == "cn:538"
            for batch in search.calls[before:]
            for request in batch
        )

    asyncio.run(scenario())


def test_conflicts_require_confirmation_and_newline_directions_are_split() -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            extraction={
                "preferences": {"location": "Hong Kong"},
                "conflicts": ["preferences.location"],
            }
        )
        graph, _, _, _ = setup(provider)
        state = await graph.ainvoke(
            initial(target_directions=[], preferences={"employment_type": "internship"}),
            configuration(),
        )
        assert set(q.field for q in state["clarification_questions"]) == {
            "target_directions",
            "preferences.location",
        }
        answers = [
            {
                "question_id": q.question_id,
                "value": "data analyst\nbackend engineer"
                if q.field == "target_directions"
                else "Hong Kong",
            }
            for q in state["clarification_questions"]
        ]
        state = await graph.ainvoke(resume(answers=answers), configuration())
        assert state["profile"].target_directions == ["data analyst", "backend engineer"]
        assert not state["profile"].conflicts
        assert state["search_summary"].ready
        assert "data analyst\nbackend engineer" in state["conversation"][-2].responses[0].value

    asyncio.run(scenario())


def test_conversation_keeps_free_text_and_displays_choice_labels_without_internal_fields() -> None:
    class ChoiceProvider(FakeProvider):
        async def structured[SchemaT: BaseModel](
            self,
            schema: type[SchemaT],
            messages: list[dict[str, str]],
            *,
            deadline: float | None = None,
        ) -> SchemaT:
            if schema is QuestionGeneration:
                return schema.model_validate(
                    {
                        "questions": [
                            {
                                "field": "target_directions",
                                "question": "What kind of roles are you looking for?",
                                "reason": "Confirm your job directions.",
                                "control_type": "multiple_choice",
                                "options": [
                                    {"id": "data", "label": "Data Analyst"},
                                    {"id": "backend", "label": "Backend Engineer"},
                                ],
                            },
                            {
                                "field": "preferences.location",
                                "question": "Where would you like to work?",
                                "reason": "Confirm your work location.",
                                "control_type": "single_choice",
                                "options": [{"id": "anywhere", "label": "Any location"}],
                            },
                            {
                                "field": "preferences.employment_type",
                                "question": "What type of employment are you looking for?",
                                "reason": "Confirm your employment type.",
                                "control_type": "single_choice",
                                "options": [{"id": "full", "label": "Full-time"}],
                            },
                        ]
                    }
                )
            return await super().structured(schema, messages, deadline=deadline)

    async def scenario() -> None:
        provider = ChoiceProvider()
        provider.changes = [{"field": "skills", "value": ["SQL"], "mode": "merge"}]
        graph, _, _, _ = setup(provider)
        state = await graph.ainvoke(initial(target_directions=[], preferences={}), configuration())
        questions = state["clarification_questions"]
        values: list[str | list[str]] = [["data", "backend"], "anywhere", "full"]
        state = await graph.ainvoke(
            resume(
                message="I also know SQL",
                answers=[
                    {"question_id": question.question_id, "value": value}
                    for question, value in zip(questions, values, strict=True)
                ],
            ),
            configuration(),
        )
        submitted = state["conversation"][-2]
        assert submitted.text == "I also know SQL"
        assert [response.model_dump() for response in submitted.responses] == [
            {
                "label": "What kind of roles are you looking for?",
                "value": ["Data Analyst", "Backend Engineer"],
                "status": "answered",
            },
            {
                "label": "Where would you like to work?",
                "value": "Any location",
                "status": "answered",
            },
            {
                "label": "What type of employment are you looking for?",
                "value": "Full-time",
                "status": "answered",
            },
        ]
        assert "target_directions" not in submitted.model_dump_json()
        assert "preferences.location" not in submitted.model_dump_json()
        assert state["profile_documents"][-1].text.splitlines() == [
            "I also know SQL",
            "Data Analyst",
            "Backend Engineer",
            "Any location",
            "Full-time",
        ]

    asyncio.run(scenario())


def test_required_questions_are_retained_and_empty_choices_allow_text() -> None:
    class EmptyChoiceProvider(FakeProvider):
        async def structured[SchemaT: BaseModel](
            self,
            schema: type[SchemaT],
            messages: list[dict[str, str]],
            *,
            deadline: float | None = None,
        ) -> SchemaT:
            return schema.model_validate(
                {
                    "questions": [
                        {
                            "field": "target_directions",
                            "question": "What kind of roles are you looking for?",
                            "reason": "Confirm your job directions.",
                            "control_type": "multiple_choice",
                            "options": [],
                        }
                    ]
                }
            )

    async def scenario() -> None:
        service = ConversationService(EmptyChoiceProvider())
        fields = ["target_directions", "preferences.location", "preferences.employment_type"]
        questions = await service.questions(UserProfile(profile_id="p"), fields, [], 1)
        assert [question.field for question in questions] == fields
        assert questions[0].control_type == "text"
        assert all(question.required for question in questions)
        assert all("preferences." not in question.question for question in questions)

    asyncio.run(scenario())


@pytest.mark.parametrize("retry_thread", ["s1", "s1:3"])
def test_retry_replays_answers_after_interpretation_failure_without_duplicate_messages(
    retry_thread: str,
) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        provider.changes = [{"field": "skills", "value": ["SQL"], "mode": "merge"}]
        graph, _, _, _ = setup(provider)
        state = await graph.ainvoke(initial(target_directions=[], preferences={}), configuration())
        values = {
            "target_directions": "data analyst",
            "preferences.location": "Hong Kong",
            "preferences.employment_type": "internship",
        }
        answers = [
            {"question_id": question.question_id, "value": values[question.field]}
            for question in state["clarification_questions"]
        ]
        history = state["conversation"]
        provider.fail = "AnswerInterpretation"
        failed = await graph.ainvoke(
            resume(answers=answers, message="I also know SQL"), configuration()
        )
        assert failed["current_stage"] == "failed"
        assert failed["conversation"] == history
        assert failed["profile"].target_directions == []
        provider.fail = None
        retried = await graph.ainvoke(
            {**failed, "command": resume(2, action="retry").resume, "revision": 3},
            configuration(retry_thread),
        )
        assert retried["search_summary"].ready
        assert retried["search_summary"].revision == 3
        assert retried["profile"].target_directions == ["data analyst"]
        assert retried["profile"].skills == ["Python", "SQL"]
        submitted = [
            message for message in retried["conversation"] if message.text == "I also know SQL"
        ]
        assert len(submitted) == 1
        assert len(submitted[0].responses) == 3
        assert (
            len(
                [
                    document
                    for document in retried["profile_documents"]
                    if ":answer:" in document.document_id
                ]
            )
            == 1
        )
        assert retried["failed_resume_payload"] is None
        assert retried["errors"] == []
        assert provider.calls.count("AnswerInterpretation") == 2
        assert provider.calls.count("ProfileExtraction") == 1

    asyncio.run(scenario())


def test_invalid_question_ids_do_not_mutate_profile() -> None:
    async def scenario() -> None:
        graph, _, search, _ = setup()
        before = await graph.ainvoke(initial(target_directions=[]), configuration())
        state = await graph.ainvoke(
            resume(answers=[{"question_id": "unknown", "value": "data analyst"}]), configuration()
        )
        assert state["current_stage"] == "failed"
        assert state["profile"] == before["profile"]
        assert not search.calls

    asyncio.run(scenario())


def test_model_generated_directions_cannot_override_explicit_selection() -> None:
    async def scenario() -> None:
        graph, _, _, _ = setup(FakeProvider(extraction={"target_directions": ["unrelated role"]}))
        state = await graph.ainvoke(initial(), configuration())
        assert state["profile"].target_directions == ["data analyst"]

    asyncio.run(scenario())


def test_retrieval_deadline_cancels_service(monkeypatch: pytest.MonkeyPatch) -> None:
    import jobscout.graph.live as live

    class SlowSearch(FakeSearch):
        cancelled = False

        async def search_many_async(
            self, requests: Sequence[SearchRequest], *, timeout: float = 60
        ) -> SearchResult:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return SearchResult()

    async def scenario() -> None:
        search = SlowSearch()
        graph, _, _, _ = setup(search=search)
        await graph.ainvoke(initial(), configuration())
        start = asyncio.get_running_loop().time()
        state = await graph.ainvoke(resume(action="confirm_search"), configuration())
        assert asyncio.get_running_loop().time() - start < 1
        assert state["stop_reason"] == "budget_exhausted"
        assert state["recommendation"].jobs == []
        assert search.cancelled

    monkeypatch.setattr(live, "OPERATION_SECONDS", 0.02)
    asyncio.run(scenario())


def test_operation_deadline_includes_planning(monkeypatch: pytest.MonkeyPatch) -> None:
    import jobscout.graph.live as live

    class SlowProvider(FakeProvider):
        async def tool_turn(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            *,
            deadline: float | None = None,
        ) -> Any:
            await asyncio.sleep(10)
            return await super().tool_turn(messages, tools, deadline=deadline)

    async def scenario() -> None:
        graph, _, search, _ = setup(SlowProvider())
        await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(resume(action="confirm_search"), configuration())
        assert state["stop_reason"] == "budget_exhausted"
        assert state["recommendation"].jobs == []
        assert not search.calls

    monkeypatch.setattr(live, "OPERATION_SECONDS", 0.02)
    asyncio.run(scenario())


@pytest.mark.parametrize("clarifying", [False, True])
def test_resume_revision_is_checkpointed_before_model_interpretation(clarifying: bool) -> None:
    class BlockingProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def structured[SchemaT: BaseModel](
            self,
            schema: type[SchemaT],
            messages: list[dict[str, str]],
            *,
            deadline: float | None = None,
        ) -> SchemaT:
            if schema is AnswerInterpretation:
                self.started.set()
                await self.release.wait()
            return await super().structured(schema, messages, deadline=deadline)

    async def scenario() -> None:
        provider = BlockingProvider()
        graph, _, _, _ = setup(provider)
        await graph.ainvoke(
            initial(target_directions=[] if clarifying else ["data analyst"]), configuration()
        )
        operation = asyncio.create_task(
            graph.ainvoke(resume(1, message="I am still considering the options"), configuration())
        )
        try:
            await asyncio.wait_for(provider.started.wait(), 1)
            snapshot = (await graph.aget_state(configuration())).values
            assert snapshot["revision"] == 2
            assert snapshot["outcome"] == "running"
            assert snapshot["recommendation"] is None
            assert snapshot["confirmed_profile"] is None
            if not clarifying:
                assert snapshot["search_summary"].revision == 2
                assert not snapshot["search_summary"].confirmed
        finally:
            provider.release.set()
            state = await operation
        assert state["revision"] == 2
        if state.get("search_summary") is not None:
            assert state["search_summary"].revision == 2

    asyncio.run(scenario())


def test_model_changes_cannot_write_server_fields() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        provider.changes = [{"field": "confirmed_profile", "value": "override"}]
        graph, _, search, _ = setup(provider)
        original = await graph.ainvoke(initial(), configuration())
        state = await graph.ainvoke(resume(1, message="Review this document"), configuration())
        assert state["current_stage"] == "failed"
        assert state["revision"] == 2
        assert state["profile"] == original["profile"]
        assert state["confirmed_profile"] is None
        assert state["recommendation"] is None
        assert not search.calls

    asyncio.run(scenario())


def test_cancellation_propagates_without_late_completion() -> None:
    class BlockingSearch(FakeSearch):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.cancelled = False

        async def search_many_async(
            self, requests: Sequence[SearchRequest], *, timeout: float = 60
        ) -> SearchResult:
            self.started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return SearchResult()

    async def scenario() -> None:
        search = BlockingSearch()
        graph, _, _, _ = setup(search=search)
        await graph.ainvoke(initial(), configuration())
        task = asyncio.create_task(graph.ainvoke(resume(action="confirm_search"), configuration()))
        await search.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert search.cancelled
        assert (await graph.aget_state(configuration())).values["current_stage"] != "completed"

    asyncio.run(scenario())
