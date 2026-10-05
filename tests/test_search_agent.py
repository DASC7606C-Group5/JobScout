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


def test_cross_source_duplicates_preserve_all_source_evidence() -> None:
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


def test_stop_cancels_unfinished_batch_and_keeps_published_vacancies() -> None:
    class BlockingAssessment(Assessment):
        cancelled = False

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
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            raise AssertionError("Unfinished work must be cancelled")

    async def scenario() -> None:
        event = asyncio.Event()
        assessment = BlockingAssessment()
        saved_ids: list[str] = []

        async def progress(update: dict[str, Any]) -> None:
            if update["progress"]["matched_count"] == 1:
                saved_ids.extend(item.job.job_id for item in update["recommendation"].jobs)
                event.set()

        result = await run(
            ReplayProvider(), SnapshotSearch(5), assessment, stop_event=event, on_progress=progress
        )
        assert result["stop_reason"] == "user_stopped"
        assert assessment.cancelled
        assert [item.job.job_id for item in result["recommendation"].jobs] == saved_ids[:1]
        assert result["progress"]["matched_count"] == 1
        assert {item.job.source_url for item in result["recommendation"].pending_jobs} == {
            f"https://jobsdb.example/jobs/{index}" for index in range(1, 5)
        }

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
