"""Search decisions are exercised against observations and immutable confirmed constraints."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from jobscout.schemas.job import JobPosting
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.schemas.search import SearchRequest
from jobscout.services.job_assessment_service import AssessmentDiagnostic
from jobscout.services.job_retrieval.models import (
    RawJob,
    SearchResult,
    SourceOutcome,
    workflow_error,
)
from jobscout.services.llm_service import ModelServiceError, ToolCall, ToolTurn
from jobscout.services.replay_service import ReplayProvider, replay_catalog
from jobscout.services.search_agent import SearchAgent


def profile(count: int = 10) -> UserProfile:
    return UserProfile.model_validate(
        {
            "profile_id": "applicant",
            "target_directions": ["Data Analyst"],
            "search_options": {"result_count": count},
            "preferences": {
                "location": "Hong Kong",
                "employment_type": "internship",
                "locations": {
                    "raw_text": "Hong Kong",
                    "included": [replay_catalog().find("Hong Kong")[0].model_dump()],
                },
                "employment": {"raw_text": "internship", "included": ["internship"]},
            },
        }
    )


def raw(index: int, *, source: str = "jobsdb") -> RawJob:
    return RawJob(
        source=source,
        source_url=f"https://{source}.example/jobs/{index}",
        fetched_at=datetime.now(UTC),
        source_job_id=f"{source}-{index}",
        target_direction="Data Analyst",
        title=f"Data Analyst {index}",
        company=f"Company {index}",
        location="Hong Kong",
        employment_type="internship",
        description="Analyze data using Python.",
        raw_payload={},
    )


class SnapshotSearch:
    supported_sources = ["jobsdb"]

    def __init__(self, count: int = 12) -> None:
        self.rows = [raw(index) for index in range(count)]
        self.requests: list[SearchRequest] = []
        self.details: list[str] = []

    async def search_many_async(
        self, requests: Sequence[SearchRequest], *, timeout: float = 60
    ) -> SearchResult:
        self.requests.extend(requests)
        request = requests[0]
        return SearchResult(
            raw_jobs=self.rows if request.page == 1 else [],
            outcomes=[
                SourceOutcome(
                    source=request.sources[0],
                    target_direction=request.target_direction,
                    status="ok" if request.page == 1 and self.rows else "empty",
                    returned_count=len(self.rows) if request.page == 1 else 0,
                )
            ],
        )

    async def fetch_details(
        self, jobs: Sequence[JobPosting], *, timeout: float = 30
    ) -> list[JobPosting]:
        self.details.extend(job.job_id for job in jobs)
        return [job.model_copy(update={"description_is_excerpt": False}) for job in jobs]


class Assessment:
    def __init__(self, *, pending: bool = False) -> None:
        self.pending = pending
        self.feedback: list[dict[str, str]] = []

    async def assess(
        self,
        profile: UserProfile,
        jobs: list[JobPosting],
        documents: dict[str, str],
        session_id: str,
        deadline: float | None = None,
        repair_feedback: dict[str, str] | None = None,
        on_batch: Callable[[RecommendationResult], Awaitable[None]] | None = None,
    ) -> RecommendationResult:
        self.feedback.append(repair_feedback or {})
        rows = [
            RecommendationItem(
                job=job,
                verification_status="pending" if self.pending else "confirmed",
                unknown_conditions=["location"] if self.pending else [],
            )
            for job in jobs
        ]
        return RecommendationResult(
            session_id=session_id,
            generated_at=datetime.now(UTC),
            jobs=[] if self.pending else rows,
            pending_jobs=rows if self.pending else [],
        )


async def run(
    provider: Any, search: Any, assessment: Any, applicant: UserProfile | None = None, **kwargs: Any
) -> dict[str, Any]:
    return await SearchAgent(provider, search, assessment).run(
        applicant or profile(),
        {},
        "session",
        deadline=asyncio.get_running_loop().time() + 30,
        **kwargs,
    )


@pytest.mark.parametrize("target", [5, 10, 20])
def test_requested_target_is_reached_by_relevant_vacancies(target: int) -> None:
    async def scenario() -> None:
        events: list[dict[str, Any]] = []

        async def progress(update: dict[str, Any]) -> None:
            events.append(update)

        result = await run(
            ReplayProvider(),
            SnapshotSearch(30),
            Assessment(),
            profile(target),
            on_progress=progress,
        )
        assert result["stop_reason"] == "target_reached"
        assert len(result["recommendation"].jobs) == target
        assert len({item.job.job_id for item in result["recommendation"].jobs}) == target
        assert result["progress"]["discovered_count"] == 30
        assert len(result["analyzed_job_ids"]) <= 3 * target
        assert [event["progress_seq"] for event in events] == list(range(1, len(events) + 1))
        assert all(
            item.analysis_status == "complete"
            for event in events
            for item in event["recommendation"].jobs
        )

    asyncio.run(scenario())


def test_pending_verification_never_counts_toward_target() -> None:
    async def scenario() -> None:
        result = await run(
            ReplayProvider(), SnapshotSearch(8), Assessment(pending=True), profile(5)
        )
        assert result["stop_reason"] == "source_exhausted"
        assert result["recommendation"].jobs == []
        assert len(result["recommendation"].pending_jobs) == 5
        assert result["progress"]["matched_count"] == 0

    asyncio.run(scenario())


class ScriptedProvider(ReplayProvider):
    def __init__(
        self, scripts: list[Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]]
    ) -> None:
        self.scripts = scripts
        self.decisions = 0
        self.observations: list[dict[str, Any]] = []

    async def tool_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        deadline: float | None = None,
    ) -> ToolTurn:
        observation = json.loads(messages[-1]["content"])
        self.observations.append(observation)
        index = self.decisions
        self.decisions += 1
        if index < len(self.scripts):
            name, arguments = self.scripts[index](observation)
            return ToolTurn(calls=[ToolCall(id=str(index), name=name, arguments=arguments)])
        return await super().tool_turn(messages, tools, deadline=deadline)


def query(**changes: Any) -> tuple[str, dict[str, Any]]:
    return "search_jobs", {
        "direction": "Data Analyst",
        "source": "jobsdb",
        "keywords": ["Data Analyst"],
        **changes,
    }


@pytest.mark.parametrize("improves", [False, True])
def test_full_shortlist_compares_later_candidates_and_finishes_after_a_plateau(
    improves: bool,
) -> None:
    class FitAssessment(Assessment):
        better_id: str | None = None

        async def assess(self, *args: Any, **kwargs: Any) -> RecommendationResult:
            result = await super().assess(*args, **kwargs)
            better = improves and len(self.feedback) == 3
            for row in result.jobs:
                row.recommendation_fit = "recommended" if better else "possible"
                if better:
                    self.better_id = row.job.job_id
            return result

    def assess_next(observation: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        candidates = [
            row["job_id"] for row in observation["candidates"] if not row["analysis_attempts"]
        ]
        return "assess_candidates", {
            "job_ids": candidates[:5] if not observation["matched_count"] else candidates[:1]
        }

    async def scenario() -> None:
        search, assessment = SnapshotSearch(15), FitAssessment()
        provider = ScriptedProvider(
            [lambda _: query(), *[assess_next for _ in range(8)], lambda _: query(page=2)]
        )
        result = await run(provider, search, assessment, profile(5))
        assert result["stop_reason"] == "results_ready"
        assert result["agent_error_code"] is None
        assert len(assessment.feedback) == (5 if improves else 3)
        assert provider.decisions == len(assessment.feedback) + 1
        assert len(search.requests) == 1
        assert len(result["recommendation"].jobs) == 5
        assert result["progress"]["discovered_count"] == 15
        assert result["progress"]["analyzed_count"] == (9 if improves else 7)
        assert all(row.review_status == "reviewed" for row in result["recommendation"].jobs)
        if improves:
            assert result["recommendation"].jobs[0].job.job_id == assessment.better_id
        else:
            assert all(
                row.recommendation_fit == "possible" for row in result["recommendation"].jobs
            )

    asyncio.run(scenario())


def test_useful_results_can_finish_below_display_limit_without_exhausting_sources() -> None:
    async def scenario() -> None:
        search = SnapshotSearch(2)
        provider = ScriptedProvider(
            [
                lambda _: ("finish_search", {"reason": "results_ready"}),
                lambda _: query(),
                lambda o: (
                    "assess_candidates",
                    {"job_ids": [row["job_id"] for row in o["candidates"]]},
                ),
                lambda _: ("finish_search", {"reason": "results_ready"}),
            ]
        )
        result = await run(provider, search, Assessment(), profile(20))
        assert result["stop_reason"] == "results_ready"
        assert result["agent_error_code"] is None
        assert {item.job.source_url for item in result["recommendation"].jobs} == {
            "https://jobsdb.example/jobs/0",
            "https://jobsdb.example/jobs/1",
        }
        assert len(search.requests) == 1
        assert provider.observations[-1]["unexhausted_pairs"]

    asyncio.run(scenario())


def test_decision_context_keeps_latest_feedback_without_replaying_old_snapshots() -> None:
    class RecordingProvider(ScriptedProvider):
        def __init__(self) -> None:
            super().__init__(
                [
                    lambda _: query(),
                    *[lambda _: query() for _ in range(5)],
                    lambda _: ("finish_search", {"reason": "results_ready"}),
                ]
            )
            self.inputs: list[list[dict[str, Any]]] = []

        async def tool_turn(
            self, messages: list[dict[str, Any]], *args: Any, **kwargs: Any
        ) -> ToolTurn:
            self.inputs.append(messages)
            return await super().tool_turn(messages, *args, **kwargs)

    async def scenario() -> None:
        provider, search = RecordingProvider(), SnapshotSearch(1)
        applicant = profile()
        applicant.projects = ["PRIVATE_PROFILE_SENTINEL " * 100]
        result = await run(provider, search, Assessment(), applicant)
        assert result["stop_reason"] == "results_ready"
        assert len(search.requests) == 1
        assert max(len(messages) for messages in provider.inputs) == 5
        assert all(
            "PRIVATE_PROFILE_SENTINEL" not in json.dumps(messages) for messages in provider.inputs
        )
        assert json.loads(provider.inputs[-1][-2]["content"])["error"] == "already_completed"
        assert (
            result["recommendation"].pending_jobs[0].job.source_url
            == "https://jobsdb.example/jobs/0"
        )

    asyncio.run(scenario())


def test_overlapping_interests_do_not_allocate_slots_or_change_fit_order() -> None:
    from tests.test_job_assessment_service import job

    agent = SearchAgent(ReplayProvider(), SnapshotSearch(), Assessment())
    agent.profile, agent.target = profile(), 5
    agent.profile.target_directions = ["Frontend", "Software engineering"]
    items = [
        RecommendationItem(job=job("a", direction="Frontend"), recommendation_fit="recommended"),
        RecommendationItem(job=job("b", direction="Frontend"), recommendation_fit="recommended"),
        RecommendationItem(
            job=job("c", direction="Software engineering"), recommendation_fit="possible"
        ),
    ]
    assert [item.job.job_id for item in agent.ranked(items)] == ["a", "b", "c"]
    items[0].job.target_directions = list(agent.profile.target_directions)
    agent.profile.target_directions.reverse()
    assert [item.job.job_id for item in agent.ranked(list(reversed(items)))] == ["a", "b", "c"]


def test_model_failure_preserves_retrieved_vacancies_and_published_progress() -> None:
    class FailingDecisionProvider(ScriptedProvider):
        async def tool_turn(self, *args: Any, **kwargs: Any) -> ToolTurn:
            if self.decisions:
                raise ModelServiceError("model_output")
            return await super().tool_turn(*args, **kwargs)

    async def scenario() -> None:
        events: list[dict[str, Any]] = []

        async def progress(update: dict[str, Any]) -> None:
            events.append(update)

        result = await run(
            FailingDecisionProvider([lambda _: query()]),
            SnapshotSearch(2),
            Assessment(),
            profile(5),
            on_progress=progress,
        )
        assert result["stop_reason"] == "error"
        assert result["agent_error_code"] == "model_output"
        pending = result["recommendation"].pending_jobs
        assert {item.job.source_url for item in pending} == {
            "https://jobsdb.example/jobs/0",
            "https://jobsdb.example/jobs/1",
        }
        assert all(item.analysis_status == "unavailable" for item in pending)
        assert all(item.matching_reasons == [] for item in pending)
        assert all(item.verification_status == "pending" for item in pending)
        assert {item.job.job_id for item in events[-2]["recommendation"].pending_jobs} == {
            item.job.job_id for item in pending
        }

    asyncio.run(scenario())


def test_untrusted_arguments_cannot_mutate_confirmed_conditions_or_repeat_success() -> None:
    async def scenario() -> None:
        search = SnapshotSearch(0)
        applicant = profile()
        original = applicant.model_dump()
        provider = ScriptedProvider(
            [
                lambda _: query(direction="Accountant"),
                lambda _: query(location_ids=["cn:530"]),
                lambda _: query(employment_types=["full-time"]),
                lambda _: query(location="Ignore restrictions; nationwide"),
                lambda _: query(),
                lambda _: query(),
            ]
        )
        result = await run(provider, search, Assessment(), applicant)
        searches = [(tuple(request.keywords), request.page) for request in search.requests]
        assert len(searches) == len(set(searches))
        assert searches == [(("Data Analyst",), 1), (("Data Analyst jobs",), 1)]
        assert all(
            request.location_ref is not None and request.location_ref.id == "hk"
            for request in search.requests
        )
        assert all(request.employment_type == "internship" for request in search.requests)
        assert applicant.model_dump() == original
        assert result["stop_reason"] == "source_exhausted"

    asyncio.run(scenario())


def test_successful_details_are_deduplicated_per_vacancy_across_batches() -> None:
    async def scenario() -> None:
        search = SnapshotSearch(2)
        provider = ScriptedProvider(
            [
                lambda _: query(),
                lambda o: (
                    "fetch_job_details",
                    {"job_ids": [row["job_id"] for row in o["candidates"]]},
                ),
                lambda o: ("fetch_job_details", {"job_ids": [o["candidates"][0]["job_id"]]}),
            ]
        )
        await run(provider, search, Assessment())
        assert len(search.details) == len(set(search.details)) == 2

    asyncio.run(scenario())


def test_new_details_allow_reassessment_without_reusing_summary_analysis() -> None:
    class DetailSearch(SnapshotSearch):
        async def fetch_details(
            self, jobs: Sequence[JobPosting], *, timeout: float = 30
        ) -> list[JobPosting]:
            return [
                job.model_copy(update={"description": "Full listing: analyze data using Python."})
                for job in jobs
            ]

    class DetailAssessment(Assessment):
        async def assess(self, *args: Any, **kwargs: Any) -> RecommendationResult:
            self.pending = not args[1][0].description.startswith("Full listing:")
            return await super().assess(*args, **kwargs)

    async def scenario() -> None:
        provider = ScriptedProvider(
            [
                lambda _: query(),
                lambda o: ("assess_candidates", {"job_ids": [o["candidates"][0]["job_id"]]}),
                lambda o: ("fetch_job_details", {"job_ids": [o["candidates"][0]["job_id"]]}),
                lambda o: ("assess_candidates", {"job_ids": [o["candidates"][0]["job_id"]]}),
                lambda _: ("finish_search", {"reason": "results_ready"}),
            ]
        )
        assessment = DetailAssessment()
        result = await run(provider, DetailSearch(1), assessment)
        assert len(assessment.feedback) == 2
        assert [item.job.source_url for item in result["recommendation"].jobs] == [
            "https://jobsdb.example/jobs/0"
        ]
        assert result["recommendation"].pending_jobs == []
        assert result["recommendation"].jobs[0].job.description.startswith("Full listing:")
        assert provider.observations[3]["candidates"][0]["analysis_attempts"] == 1

    asyncio.run(scenario())


def test_cross_source_duplicates_preserve_all_source_documents() -> None:
    class Sources(SnapshotSearch):
        supported_sources = ["first", "second"]

        async def search_many_async(
            self, requests: Sequence[SearchRequest], *, timeout: float = 60
        ) -> SearchResult:
            request = requests[0]
            self.requests.extend(requests)
            return SearchResult(
                raw_jobs=[raw(1, source=request.sources[0])] if request.page == 1 else []
            )

    async def scenario() -> None:
        provider = ScriptedProvider(
            [lambda _: query(source="first"), lambda _: query(source="second")]
        )
        result = await run(provider, Sources(0), Assessment())
        assert len(result["recommendation"].jobs) == 1
        job = result["recommendation"].jobs[0].job
        assert set(job.source_links) == {
            "https://first.example/jobs/1",
            "https://second.example/jobs/1",
        }
        assert {document.source for document in job.source_documents} == {"first", "second"}
        assert result["progress"]["discovered_count"] == 1
        assert result["progress"]["matched_count"] == 1

    asyncio.run(scenario())


def test_transient_query_retry_is_bounded_and_failure_observation_is_available() -> None:
    class FlakySearch(SnapshotSearch):
        async def search_many_async(
            self, requests: Sequence[SearchRequest], *, timeout: float = 60
        ) -> SearchResult:
            self.requests.extend(requests)
            return SearchResult(
                errors=[workflow_error("SEARCH_TIMEOUT", "Transient timeout")],
                outcomes=[
                    SourceOutcome(
                        source="jobsdb", target_direction="Data Analyst", status="unavailable"
                    )
                ],
            )

    async def scenario() -> None:
        provider = ScriptedProvider([lambda _: query(), lambda _: query(), lambda _: query()])
        search = FlakySearch()
        result = await run(provider, search, Assessment())
        assert len(search.requests) == 2
        assert provider.observations[1]["queries"][0]["outcomes"][0]["status"] == "unavailable"
        assert result["stop_reason"] == "error"

    asyncio.run(scenario())


def test_stop_finishes_active_reviews_without_searching_again() -> None:
    class BlockingAssessment(Assessment):
        cancelled = False
        finished = False

        async def assess(
            self,
            profile: UserProfile,
            jobs: list[JobPosting],
            documents: dict[str, str],
            session_id: str,
            deadline: float | None = None,
            repair_feedback: dict[str, str] | None = None,
            on_batch: Callable[[RecommendationResult], Awaitable[None]] | None = None,
        ) -> RecommendationResult:
            completed = await super().assess(profile, jobs[:1], documents, session_id)
            assert on_batch is not None
            await on_batch(completed)
            try:
                await asyncio.sleep(0)
                remaining = await super().assess(profile, jobs[1:], documents, session_id)
                await on_batch(remaining)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            self.finished = True
            return completed.model_copy(update={"jobs": [*completed.jobs, *remaining.jobs]})

    async def scenario() -> None:
        event = asyncio.Event()
        assessment = BlockingAssessment()
        search = SnapshotSearch(5)

        async def progress(update: dict[str, Any]) -> None:
            if update["progress"]["matched_count"] == 1:
                event.set()

        result = await run(
            ReplayProvider(), search, assessment, stop_event=event, on_progress=progress
        )
        assert result["stop_reason"] == "user_stopped"
        assert assessment.finished
        assert not assessment.cancelled
        assert len(search.requests) == 1
        assert result["progress"]["retrieval_stopped"]
        assert {item.job.source_url for item in result["recommendation"].jobs} == {
            f"https://jobsdb.example/jobs/{index}" for index in range(5)
        }
        assert all(item.review_status == "reviewed" for item in result["recommendation"].jobs)
        assert result["recommendation"].pending_jobs == []

    asyncio.run(scenario())


def test_stop_before_assessment_reviews_published_vacancies() -> None:
    async def scenario() -> None:
        event = asyncio.Event()
        search = SnapshotSearch(5)

        async def progress(update: dict[str, Any]) -> None:
            if update["progress"]["pending_count"] == 5:
                event.set()

        result = await run(
            ReplayProvider(), search, Assessment(), stop_event=event, on_progress=progress
        )
        assert result["stop_reason"] == "user_stopped"
        assert len(search.requests) == 1
        assert set(search.details) == {item.job.job_id for item in result["recommendation"].jobs}
        assert {item.job.source_url for item in result["recommendation"].jobs} == {
            f"https://jobsdb.example/jobs/{index}" for index in range(5)
        }
        assert all(item.review_status == "reviewed" for item in result["recommendation"].jobs)
        assert result["recommendation"].pending_jobs == []

    asyncio.run(scenario())


def test_subsequent_search_does_not_restore_a_confirmed_condition_mismatch() -> None:
    class MismatchAssessment(Assessment):
        diagnostics: dict[str, AssessmentDiagnostic]

        async def assess(self, *args: Any, **kwargs: Any) -> RecommendationResult:
            jobs = args[1]
            self.diagnostics = {
                job.job_id: AssessmentDiagnostic(
                    code="condition_mismatch",
                    stage="conditions",
                    detail="The listing explicitly requires another employment type.",
                    retryable=False,
                )
                for job in jobs
            }
            return RecommendationResult(session_id="session", generated_at=datetime.now(UTC))

    async def scenario() -> None:
        provider = ScriptedProvider(
            [
                lambda _: query(),
                lambda o: ("assess_candidates", {"job_ids": [o["candidates"][0]["job_id"]]}),
                lambda _: query(keywords=["Data Analyst jobs"]),
            ]
        )
        result = await run(provider, SnapshotSearch(1), MismatchAssessment())
        assert result["recommendation"].jobs == []
        assert result["recommendation"].pending_jobs == []
        assert provider.observations[3]["pending_count"] == 0
        assert provider.observations[3]["candidates"][0]["analysis_diagnostic"]["code"] == (
            "condition_mismatch"
        )

    asyncio.run(scenario())


def test_screening_activity_tracks_all_candidates_without_exposing_diagnostics() -> None:
    class MixedAssessment:
        diagnostics: dict[str, AssessmentDiagnostic]

        async def assess(
            self,
            applicant: UserProfile,
            jobs: list[JobPosting],
            documents: dict[str, str],
            session_id: str,
            on_batch: Callable[[RecommendationResult], Awaitable[None]] | None = None,
            **kwargs: Any,
        ) -> RecommendationResult:
            rows = {int(job.title.rsplit(" ", 1)[1]): job for job in jobs}
            self.diagnostics = {
                rows[7].job_id: AssessmentDiagnostic(
                    code="model_failure",
                    stage="private-stage",
                    detail="private-model-diagnostic",
                    retryable=True,
                ),
                rows[8].job_id: AssessmentDiagnostic(
                    code="condition_mismatch",
                    stage="private-stage",
                    detail="private-model-diagnostic",
                    retryable=False,
                ),
            }
            result = RecommendationResult(
                session_id=session_id,
                generated_at=datetime.now(UTC),
                jobs=[
                    RecommendationItem(
                        job=rows[index],
                        recommendation_fit="recommended",
                        verification_status="confirmed",
                    )
                    for index in range(6)
                ],
                pending_jobs=[
                    RecommendationItem(
                        job=rows[6], verification_status="pending", unknown_conditions=["location"]
                    )
                ],
            )
            assert on_batch is not None
            await on_batch(result.model_copy(update={"jobs": result.jobs[:1], "pending_jobs": []}))
            return result

    async def scenario() -> None:
        updates: list[dict[str, Any]] = []

        async def progress(update: dict[str, Any]) -> None:
            updates.append(update["progress"])

        search = SnapshotSearch(11)
        search.rows[9] = search.rows[9].model_copy(update={"employment_type": "full-time"})
        provider = ScriptedProvider(
            [
                lambda _: query(),
                lambda o: (
                    "assess_candidates",
                    {
                        "job_ids": [
                            job["job_id"]
                            for job in o["candidates"]
                            if int(job["title"].rsplit(" ", 1)[1]) < 9
                        ]
                    },
                ),
                lambda _: ("finish_search", {"reason": "results_ready"}),
            ]
        )
        result = await run(provider, search, MixedAssessment(), profile(5), on_progress=progress)
        latest = {row["title"]: row for row in result["progress"]["activity"]}
        assert set(latest) == {f"Data Analyst {index}" for index in range(11)}
        assert latest["Data Analyst 6"]["status"] == "unverified"
        assert latest["Data Analyst 7"]["status"] == "failed"
        assert latest["Data Analyst 8"]["status"] == "excluded"
        assert latest["Data Analyst 9"]["status"] == "excluded"
        assert latest["Data Analyst 10"]["status"] == "not_reviewed"
        final_ids = {item.job.job_id for item in result["recommendation"].jobs}
        assert {
            row["job_id"] for row in latest.values() if row["status"] == "reviewed"
        } == final_ids
        assert {row["job_id"] for row in latest.values() if row["status"] == "not_shortlisted"} == {
            latest[f"Data Analyst {index}"]["job_id"] for index in range(6)
        } - final_ids
        assert any(
            {row["status"] for row in update["activity"]} >= {"reviewing", "reviewed"}
            for update in updates
        )
        assert any(
            {row["title"] for row in update["activity"] if row["status"] == "queued"}
            >= {"Data Analyst 0", "Data Analyst 10"}
            for update in updates
        )
        assert "private-model-diagnostic" not in json.dumps(updates)
        assert "private-stage" not in json.dumps(updates)
        candidate_states = [
            row
            for update in updates
            for row in update["activity"]
            if row["title"] == "Data Analyst 0"
        ]
        found = next(row for row in candidate_states if row["status"] == "queued")
        reviewing = next(row for row in candidate_states if row["status"] == "reviewing")
        reviewed = next(row for row in candidate_states if row["status"] == "reviewed")
        assert found["sequence"] < reviewing["sequence"] < reviewed["sequence"]
        assert len({row["sequence"] for row in candidate_states if row["status"] == "queued"}) == 1

    asyncio.run(scenario())


def test_independent_review_is_not_a_gate_for_job_visibility() -> None:
    class RejectOnce(ScriptedProvider):
        reviews = 0

        async def structured[T: BaseModel](
            self, schema: type[T], messages: list[dict[str, str]], *, deadline: float | None = None
        ) -> T:
            if schema.__name__ == "QualityReview":
                self.reviews += 1
                item = json.loads(messages[-1]["content"])["recommendation"]
                return schema.model_validate(
                    {
                        "job_id": item["job"]["job_id"],
                        "accepted": self.reviews > 1,
                        "defects": [] if self.reviews > 1 else ["incorrect_strength"],
                        "repair": "Correct unsupported match strength.",
                    }
                )
            return await super().structured(schema, messages, deadline=deadline)

    async def scenario() -> None:
        provider = RejectOnce(
            [
                lambda _: query(),
                lambda o: ("assess_candidates", {"job_ids": [o["candidates"][0]["job_id"]]}),
                lambda o: ("assess_candidates", {"job_ids": [o["candidates"][0]["job_id"]]}),
            ]
        )
        assessment = Assessment()
        result = await run(provider, SnapshotSearch(1), assessment)
        assert len(result["recommendation"].jobs) == 1
        assert result["recommendation"].jobs[0].job.source_url == "https://jobsdb.example/jobs/0"
        assert assessment.feedback == [{}]
        assert provider.reviews == 0
        assert result["progress"]["analyzed_count"] == 1

    asyncio.run(scenario())
