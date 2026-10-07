"""Let the model choose search tools from their results, within time and call limits."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from jobscout.schemas.execution import SearchActivity
from jobscout.schemas.job import JobPosting
from jobscout.schemas.job_status import JobStatus, ReviewIssue, issue_status
from jobscout.schemas.model import ModelUsage
from jobscout.schemas.profile import LocationRef, UserProfile
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.schemas.search import SearchRequest
from jobscout.services.job_assessment_service import MAX_CANDIDATES, AssessmentDiagnostic
from jobscout.services.job_processing_service import process_jobs
from jobscout.services.job_retrieval.models import SearchResult, SourceOutcome
from jobscout.services.job_retrieval.planning import select_sources
from jobscout.services.llm_service import LLMProvider, ModelServiceError, ToolTurn
from jobscout.services.notice_service import finalize_recommendation, source_label
from jobscout.services.prompts import SEARCH_PROMPT
from jobscout.services.ranking import recommendation_key
from jobscout.services.recommendation_service import eligibility_exclusions, eligible_jobs
from jobscout.services.tool_registry import (
    CandidateSelection,
    FinishSearch,
    LocationLookup,
    SearchJobs,
    ToolRegistry,
)

MAX_DECISIONS = 12
MAX_SEARCH_SECONDS = 300.0
MAX_UNIMPROVED_REVIEWS = 2
_LOGGER = logging.getLogger(__name__)
_RETRYABLE_SEARCH_ERRORS = {
    "SEARCH_TIMEOUT",
    "SEARCH_SOURCE_FAILED",
    "SEARCH_TRANSPORT",
    "SEARCH_HTTP",
    "SEARCH_NETWORK",
}
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


class SearchService(Protocol):
    async def search_many_async(
        self, requests: Sequence[SearchRequest], *, timeout: float = 60
    ) -> SearchResult: ...


class SearchEnded(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


class SearchAgent:
    """One instance per confirmed run; all mutable decisions and usage belong to that run."""

    def __init__(self, provider: LLMProvider, search: SearchService, assessment: Any) -> None:
        self.provider = provider
        self.search = search
        self.assessment = assessment
        self.registry = ToolRegistry()
        self.jobs: dict[str, JobPosting] = {}
        self.raw_jobs: list[dict[str, Any]] = []
        self.completed_details: set[str] = set()
        self.detail_attempts: dict[str, int] = {}
        self.matched: dict[str, RecommendationItem] = {}
        self.pending: dict[str, RecommendationItem] = {}
        self.attempts: dict[str, int] = {}
        self.assessed_ids: set[str] = set()
        self.analysis_diagnostics: dict[str, AssessmentDiagnostic] = {}
        self.outcomes: list[SourceOutcome] = []
        self.events: list[dict[str, Any]] = []
        self.query_history: list[dict[str, Any]] = []
        self.successful_tools: set[str] = set()
        self.tool_attempts: dict[str, int] = {}
        self.progress_seq = 0
        self.decision_count = 0
        self.duplicate_count = 0
        self.retrieval_round = 0
        self.source_errors: list[Any] = []
        self.notices: list[Any] = []
        self.warnings: list[str] = []
        self.shortlist_quality: tuple[tuple[int, bool, int], ...] | None = None
        self.unimproved_reviews = 0
        self.finished = False
        self.activity_entries: dict[str, SearchActivity] = {}

    async def run(
        self,
        profile: UserProfile,
        profile_documents: dict[str, str],
        session_id: str,
        *,
        deadline: float,
        run_id: str | None = None,
        stop_event: asyncio.Event | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        self.profile = profile.model_copy(deep=True)
        self.profile_documents = dict(profile_documents)
        self.session_id = session_id
        self.run_id = run_id or uuid4().hex
        self.stop_event = stop_event or asyncio.Event()
        self.on_progress = on_progress
        self.started = asyncio.get_running_loop().time()
        self.deadline = min(deadline, self.started + MAX_SEARCH_SECONDS)
        self.target = profile.search_options.result_count
        self.candidate_limit = MAX_CANDIDATES
        self.sources = sorted(
            getattr(
                self.search,
                "adapters",
                {
                    "zhaopin": None,
                    "liepin": None,
                    "shixiseng": None,
                    "jobsdb": None,
                },
            )
        )
        locations_to_route: list[LocationRef | None] = list(profile.preferences.locations.included)
        employment_to_route: list[str] = list(profile.preferences.employment.included)
        if not locations_to_route:
            locations_to_route.append(None)
        if not employment_to_route:
            employment_to_route.append("")
        regional_sources = {
            source
            for location in locations_to_route
            for employment in employment_to_route
            for source in select_sources(
                SearchRequest(
                    target_direction=profile.target_directions[0],
                    location_ref=location,
                    location_unrestricted=profile.preferences.locations.unrestricted,
                    employment_type=employment,
                    employment_type_unrestricted=profile.preferences.employment.unrestricted,
                )
            )
        }
        self.sources = list(
            getattr(
                self.search,
                "supported_sources",
                [source for source in self.sources if source in regional_sources],
            )
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": SEARCH_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "confirmed_profile": profile.model_dump(
                            mode="json", include={"target_directions", "skills", "preferences"}
                        ),
                        "applicant_experience": {
                            field: [text[:600] for text in getattr(profile, field)[:3]]
                            for field in ("education", "internships", "projects")
                        },
                        "available_sources": self.sources,
                        "result_limit": self.target,
                        "maximum_candidates": self.candidate_limit,
                        "maximum_decisions": MAX_DECISIONS,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        recent_messages: list[dict[str, Any]] = []
        reason = "budget_exhausted"
        error_code: str | None = None
        scope = getattr(self.provider, "usage_scope", None)
        usage_context = scope() if scope is not None else nullcontext(ModelUsage())
        with usage_context as usage:
            try:
                await self.publish("search_started", "Searching the confirmed criteria.")
                for decision in range(MAX_DECISIONS):
                    self.decision_count = decision + 1
                    self.check_budget()
                    if self.stop_event.is_set():
                        raise SearchEnded("user_stopped")
                    current_messages = [
                        *messages,
                        *recent_messages,
                        {
                            "role": "user",
                            "content": json.dumps(self.observation(), ensure_ascii=False),
                        },
                    ]
                    method = getattr(self.provider, "tool_turn", None)
                    if method is None:
                        raise ModelServiceError("model_configuration")
                    turn: ToolTurn = await self.interruptible(
                        method(current_messages, self.registry.schemas(), deadline=self.deadline),
                        stop_retrieval=True,
                    )
                    recent_messages = [turn.assistant_message()]
                    for call in turn.calls:
                        self.check_budget()
                        if self.stop_event.is_set():
                            raise SearchEnded("user_stopped")
                        try:
                            arguments = self.registry.validate(call.name, call.arguments)
                            reply = await self.interruptible(
                                self.execute(call.name, arguments),
                                stop_retrieval=call.name == "search_jobs",
                            )
                        except ValueError:
                            reply = {
                                "error": "invalid_tool_arguments",
                                "instruction": "Use only confirmed values and existing job IDs.",
                            }
                        except ModelServiceError as error:
                            reply = {"error": error.code}
                        except SearchEnded:
                            raise
                        except asyncio.CancelledError:
                            raise
                        except Exception as error:
                            _LOGGER.warning(
                                "search_tool_failed tool=%s error=%s",
                                call.name,
                                type(error).__name__,
                            )
                            reply = {"error": "tool_unavailable"}
                        recent_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": json.dumps(
                                    {
                                        key: value
                                        for key, value in reply.items()
                                        if key != "observation"
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        )
            except SearchEnded as ended:
                reason = ended.reason
                if self.stop_event.is_set():
                    reason = "user_stopped"
                    self.deadline = max(
                        self.deadline, asyncio.get_running_loop().time() + MAX_SEARCH_SECONDS
                    )
                    try:
                        await self.finish_reviews()
                    except SearchEnded:
                        pass
            except ModelServiceError as error:
                reason = (
                    "budget_exhausted"
                    if error.code == "model_timeout"
                    and asyncio.get_running_loop().time() >= self.deadline
                    else "error"
                )
                error_code = error.code
            except asyncio.CancelledError:
                raise
            finally:
                self.usage = usage.model_dump()
        if (
            reason == "source_exhausted"
            and not self.jobs
            and (self.outcomes or self.source_errors)
            and not any(outcome.status in {"ok", "empty", "partial"} for outcome in self.outcomes)
        ):
            reason = "error"
            error_code = "search_unavailable"
        if (
            reason not in {"target_reached", "results_ready", "user_stopped", "error"}
            and not self.matched
            and not self.pending
            and any(issue.retryable for issue in self.analysis_diagnostics.values())
        ):
            reason = "error"
            error_code = "model_output"
        self.finished = True
        await self.publish("search_finished", self.finish_message(reason), stop_reason=reason)
        return {
            "run_id": self.run_id,
            "progress_seq": self.progress_seq,
            "progress": self.progress(),
            "stop_reason": reason,
            "recommendation": self.result(reason, final=True),
            "source_outcomes": self.outcomes,
            "source_errors": self.source_errors,
            "notices": self.notices,
            "warnings": self.warnings,
            "normalized_jobs": list(self.jobs.values()),
            "analyzed_job_ids": list(self.attempts),
            "retrieval_round": self.retrieval_round,
            "model_usage": self.usage,
            "agent_error_code": error_code,
        }

    def check_budget(self) -> None:
        if asyncio.get_running_loop().time() >= self.deadline:
            raise SearchEnded("budget_exhausted")

    async def interruptible(self, action: Awaitable[Any], *, stop_retrieval: bool = False) -> Any:
        """Cancellation always joins children, preventing late writes or orphaned I/O."""
        task = asyncio.ensure_future(action)
        stopped = asyncio.create_task(self.stop_event.wait()) if stop_retrieval else None
        children = {task}
        if stopped is not None:
            children.add(stopped)
        try:
            done, _ = await asyncio.wait(
                children,
                timeout=max(0, self.deadline - asyncio.get_running_loop().time()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stopped is not None and stopped in done and self.stop_event.is_set():
                raise SearchEnded("user_stopped")
            if task not in done:
                raise SearchEnded("budget_exhausted")
            return await task
        finally:
            for child in children:
                if not child.done():
                    child.cancel()
            await asyncio.gather(*children, return_exceptions=True)

    async def finish_reviews(self) -> None:
        """Drain the visible review queue after retrieval is ended early."""
        await self.publish(
            "retrieval_stopped",
            "Search ended early; continuing job reviews.",
            stop_reason="user_stopped",
        )
        while True:
            self.check_budget()
            visible = self.result()
            remaining = [
                item.job.job_id
                for item in [*visible.jobs, *visible.pending_jobs]
                if item.review_status in {"queued", "not_reviewed"}
                and self.attempts.get(item.job.job_id, 0) < 2
                and (item.job.job_id in self.attempts or len(self.attempts) < self.candidate_limit)
            ][:10]
            if not remaining:
                return
            try:
                await self.interruptible(
                    self.execute("fetch_job_details", CandidateSelection(job_ids=remaining))
                )
            except SearchEnded:
                raise
            except Exception as error:
                _LOGGER.warning("job_details_failed_after_retrieval error=%s", type(error).__name__)
            try:
                reply = await self.interruptible(self.assess(remaining))
                if reply.get("error") == "analysis_limit_or_completed":
                    return
            except SearchEnded:
                raise
            except Exception as error:
                _LOGGER.warning("job_review_failed_after_retrieval error=%s", type(error).__name__)

    async def execute(self, name: str, arguments: Any) -> dict[str, Any]:
        fingerprint = arguments.model_dump()
        if isinstance(arguments, SearchJobs):
            fingerprint["keywords"] = sorted(
                {" ".join(value.casefold().split()) for value in arguments.keywords}
            )
            fingerprint["location_ids"] = sorted(set(arguments.location_ids))
            fingerprint["employment_types"] = sorted(set(arguments.employment_types))
        elif isinstance(arguments, LocationLookup):
            fingerprint["text"] = " ".join(arguments.text.casefold().split())
        key = name + ":" + json.dumps(fingerprint, sort_keys=True)
        if name in {"search_jobs", "fetch_job_details", "lookup_locations"}:
            if key in self.successful_tools:
                return {"error": "already_completed", "observation": self.observation()}
            if self.tool_attempts.get(key, 0) >= 2:
                return {"error": "retry_limit"}
            self.tool_attempts[key] = self.tool_attempts.get(key, 0) + 1
        if isinstance(arguments, SearchJobs):
            result = await self.search_jobs(arguments)
        elif isinstance(arguments, LocationLookup):
            from jobscout.services.location_service import get_location_catalog

            catalog = getattr(self.provider, "location_catalog", None) or get_location_catalog()
            locations = await catalog.lookup(arguments.text, deadline=self.deadline)
            result = {"locations": [item.model_dump(mode="json") for item in locations]}
        elif isinstance(arguments, FinishSearch):
            if not self.query_history:
                return {"error": "search_not_started"}
            if arguments.reason == "results_ready" and not (self.matched or self.pending):
                return {"error": "no_results", "observation": self.observation()}
            if arguments.reason == "target_reached" and self.useful_count() < self.target:
                return {"error": "target_not_reached"}
            if arguments.reason == "source_exhausted" and (
                not self.query_history
                or self.unexhausted_pairs()
                or any(job_id not in self.attempts for job_id in self.jobs)
                and len(self.attempts) < self.candidate_limit
            ):
                return {"error": "unfinished_search", "observation": self.observation()}
            raise SearchEnded(arguments.reason)
        elif isinstance(arguments, CandidateSelection):
            if len(set(arguments.job_ids)) != len(arguments.job_ids) or any(
                job_id not in self.jobs for job_id in arguments.job_ids
            ):
                raise ValueError("unknown_job")
            if name == "fetch_job_details":
                method = getattr(self.search, "fetch_details", None)
                if method is None:
                    return {"error": "details_unavailable"}
                await self.publish("fetch_job_details", "Reading the full job listings.")
                selected = [
                    self.jobs[job_id]
                    for job_id in arguments.job_ids
                    if job_id not in self.completed_details
                    and self.detail_attempts.get(job_id, 0) < 2
                ]
                if not selected:
                    return {"error": "already_completed"}
                for job in selected:
                    self.detail_attempts[job.job_id] = self.detail_attempts.get(job.job_id, 0) + 1
                fetched = await method(
                    selected,
                    timeout=min(30, max(0, self.deadline - asyncio.get_running_loop().time())),
                )
                allowed = {job.job_id: job for job in selected}
                for job in fetched:
                    original = allowed.get(job.job_id)
                    if (
                        original is None
                        or job.source_url != original.source_url
                        or job.source != original.source
                    ):
                        raise ValueError("changed_source_identity")
                    self.jobs[job.job_id] = job
                    self.completed_details.add(job.job_id)
                    if any(
                        getattr(original, field) != getattr(job, field)
                        for field in (
                            "description",
                            "description_is_excerpt",
                            "source_documents",
                            "location",
                            "employment_type",
                        )
                    ):
                        self.assessed_ids.discard(job.job_id)
                        self.analysis_diagnostics.pop(job.job_id, None)
                        self.matched.pop(job.job_id, None)
                        self.pending.pop(job.job_id, None)
                        if eligible_jobs(self.profile, [job]):
                            self.pending[job.job_id] = RecommendationItem(
                                job=job.model_copy(deep=True),
                                analysis_status="unavailable",
                                review_status="queued",
                                verification_status="pending",
                                unknown_conditions=["target_direction"],
                            )
                    source_links = {job.source_url, *job.source_links}
                    self.raw_jobs = [
                        job.model_dump(mode="json"),
                        *(
                            row
                            for row in self.raw_jobs
                            if row.get("source_url") not in source_links
                        ),
                    ]
                result = {
                    "updated_job_ids": [job.job_id for job in fetched],
                    "observation": self.observation(),
                }
                if any(job.job_id not in self.completed_details for job in selected):
                    result["error"] = "details_incomplete"
            elif name == "assess_candidates":
                result = await self.assess(arguments.job_ids)
            else:
                raise ValueError("unknown_tool")
        else:
            raise ValueError("invalid_tool")
        if "error" not in result:
            self.successful_tools.add(key)
        return result

    async def search_jobs(self, arguments: SearchJobs) -> dict[str, Any]:
        profile = self.profile
        if (
            arguments.direction not in profile.target_directions
            or arguments.source not in self.sources
        ):
            raise ValueError("unconfirmed_search")
        if any(not phrase.strip() or len(phrase) > 200 for phrase in arguments.keywords):
            raise ValueError("invalid_keywords")
        locations = profile.preferences.locations
        employment = profile.preferences.employment
        included = {location.id: location for location in locations.included}
        if arguments.location_ids and not set(arguments.location_ids).issubset(included):
            raise ValueError("unconfirmed_location")
        location_values: list[LocationRef | None] = (
            [included[key] for key in arguments.location_ids]
            if arguments.location_ids
            else list(included.values())
        )
        if arguments.employment_types and not set(arguments.employment_types).issubset(
            employment.included
        ):
            raise ValueError("unconfirmed_employment")
        employment_values = arguments.employment_types or employment.included
        requests = [
            SearchRequest(
                target_direction=arguments.direction,
                keywords=arguments.keywords,
                location=location.name if location else None,
                location_ref=location,
                location_unrestricted=locations.unrestricted and location is None,
                employment_type=kind or "",
                employment_type_unrestricted=employment.unrestricted and not kind,
                salary_range=profile.preferences.salary_range,
                work_mode=profile.preferences.work_arrangement.source_filter,
                sources=[arguments.source],
                page=arguments.page,
            )
            for location in (location_values or [None])
            for kind in (employment_values or [None])
        ]
        await self.publish(
            "search_jobs",
            f"Searching {source_label(arguments.source)} for {arguments.direction}.",
            source=arguments.source,
        )
        found = await self.search.search_many_async(
            requests, timeout=min(60, max(0, self.deadline - asyncio.get_running_loop().time()))
        )
        self.retrieval_round += 1
        self.outcomes.extend(found.outcomes)
        self.source_errors.extend(found.errors)
        self.notices.extend(found.notices)
        self.warnings.extend(found.warnings)
        previous_ids = set(self.jobs)
        self.raw_jobs.extend(job.model_dump(mode="json") for job in found.raw_jobs)
        self.raw_jobs = self.raw_jobs[:1000]
        normalized, warnings = process_jobs(self.raw_jobs)
        self.warnings.extend(warnings)
        before = len(self.jobs)
        for job in normalized:
            if job.job_id in self.jobs:
                original = self.jobs[job.job_id]
                if job.job_id not in self.completed_details:
                    self.jobs[job.job_id] = job
                if (
                    original.employment_type != job.employment_type
                    or original.freshness_status != job.freshness_status
                ):
                    self.matched.pop(job.job_id, None)
                    self.pending.pop(job.job_id, None)
            elif len(self.jobs) < 250:
                self.jobs[job.job_id] = job
        eligible = {job.job_id for job in eligible_jobs(self.profile, list(self.jobs.values()))}
        for job in self.jobs.values():
            issue = self.analysis_diagnostics.get(job.job_id)
            if job.job_id not in eligible or (
                issue is not None and issue.code == "condition_mismatch"
            ):
                self.pending.pop(job.job_id, None)
                self.matched.pop(job.job_id, None)
            elif job.job_id not in self.matched and job.job_id not in self.pending:
                self.pending[job.job_id] = RecommendationItem(
                    job=job.model_copy(deep=True),
                    analysis_status="unavailable",
                    review_status="queued",
                    verification_status="pending",
                    unknown_conditions=["target_direction"],
                )
        self.duplicate_count += max(0, len(found.raw_jobs) - len(set(self.jobs) - previous_ids))
        query = {
            **arguments.model_dump(),
            "new_jobs": len(self.jobs) - before,
            "returned_jobs": len(found.raw_jobs),
            "candidate_count": sum(outcome.candidate_count for outcome in found.outcomes),
            "errors": [error.code for error in found.errors],
            "outcomes": [outcome.model_dump() for outcome in found.outcomes],
        }
        self.query_history.append(query)
        await self.publish(
            "source_completed",
            f"Found {len(self.jobs) - before} more jobs on {source_label(arguments.source)}.",
            source=arguments.source,
        )
        reply: dict[str, Any] = {
            "query": query,
            "errors": [error.code for error in found.errors],
            "observation": self.observation(),
        }
        if (
            not found.raw_jobs
            and found.errors
            and all(error.code in _RETRYABLE_SEARCH_ERRORS for error in found.errors)
        ):
            reply["error"] = "source_temporary_unavailable"
        return reply

    async def assess(self, job_ids: list[str]) -> dict[str, Any]:
        selected: list[JobPosting] = []
        for job_id in job_ids:
            if (
                job_id in self.assessed_ids
                and job_id not in self.analysis_diagnostics
                or self.attempts.get(job_id, 0) >= 2
                or job_id in self.analysis_diagnostics
                and not self.analysis_diagnostics[job_id].retryable
            ):
                continue
            if job_id not in self.attempts and len(self.attempts) >= self.candidate_limit:
                continue
            self.attempts[job_id] = self.attempts.get(job_id, 0) + 1
            selected.append(self.jobs[job_id])
        if not selected:
            return {"error": "analysis_limit_or_completed", "observation": self.observation()}
        for job in selected:
            for destination in (self.pending, self.matched):
                if job.job_id in destination:
                    destination[job.job_id] = destination[job.job_id].model_copy(
                        update={"review_status": "reviewing", "review_issue": None}
                    )
        await self.publish(
            "assess_candidates", f"Comparing {len(selected)} jobs with your experience."
        )
        processed: set[str] = set()

        async def accept_batch(batch: RecommendationResult) -> None:
            for item, pending in [
                *((item, False) for item in batch.jobs),
                *((item, True) for item in batch.pending_jobs),
            ]:
                job_id = item.job.job_id
                if job_id in processed:
                    continue
                if job_id not in {job.job_id for job in selected}:
                    continue
                original = self.jobs[job_id]
                if item.job.source_url != original.source_url or item.job.source != original.source:
                    continue
                self.check_budget()
                processed.add(job_id)
                self.assessed_ids.add(job_id)
                destination = self.pending if pending else self.matched
                other = self.matched if pending else self.pending
                previous = self.matched.get(job_id) or self.pending.get(job_id)
                other.pop(job_id, None)
                if (
                    previous is not None
                    and previous.analysis_status != "unavailable"
                    and item.analysis_status == "unavailable"
                ):
                    item = previous.model_copy(update={"review_issue": item.review_issue})
                destination[job_id] = item.model_copy(update={"review_status": "reviewed"})
                await self.publish(
                    "analysis_completed", "Finished comparing a job with your experience."
                )

        try:
            result = await self.assessment.assess(
                self.profile.model_copy(deep=True),
                selected,
                self.profile_documents,
                self.session_id,
                deadline=self.deadline,
                on_batch=accept_batch,
                repair_feedback={
                    job.job_id: f"{issue.stage}: {issue.detail}"
                    for job in selected
                    if (issue := self.analysis_diagnostics.get(job.job_id)) is not None
                    and issue.retryable
                },
            )
        except Exception:
            for job in selected:
                for destination in (self.pending, self.matched):
                    if job.job_id in destination and job.job_id not in processed:
                        destination[job.job_id] = destination[job.job_id].model_copy(
                            update={
                                "review_status": "not_reviewed",
                                "review_issue": ReviewIssue(code="failed"),
                            }
                        )
            await self.publish("analysis_failed", "Some job reviews could not be completed.")
            raise
        diagnostics = getattr(self.assessment, "diagnostics", {})
        for job in selected:
            issue = diagnostics.get(job.job_id)
            if isinstance(issue, AssessmentDiagnostic):
                for destination in (self.pending, self.matched):
                    if job.job_id in destination and issue.code != "condition_mismatch":
                        destination[job.job_id] = destination[job.job_id].model_copy(
                            update={"review_issue": issue.review_issue()}
                        )
                self.analysis_diagnostics[job.job_id] = issue
                if issue.code == "condition_mismatch":
                    self.pending.pop(job.job_id, None)
                    self.matched.pop(job.job_id, None)
            else:
                self.analysis_diagnostics.pop(job.job_id, None)
        await accept_batch(result)
        for job in selected:
            for destination in (self.pending, self.matched):
                if job.job_id in destination and job.job_id not in processed:
                    destination[job.job_id] = destination[job.job_id].model_copy(
                        update={"review_status": "not_reviewed"}
                    )
        await self.publish("assessment_updated", "Updated the job screening results.")
        if processed or any(
            issue.code == "condition_mismatch"
            for job in selected
            if (issue := self.analysis_diagnostics.get(job.job_id)) is not None
        ):
            self.check_shortlist_improvement()
        return {
            "analysis_diagnostics": {
                job.job_id: self.analysis_diagnostics[job.job_id].model_dump()
                for job in selected
                if job.job_id in self.analysis_diagnostics
            },
            "observation": self.observation(),
        }

    def check_shortlist_improvement(self) -> None:
        """Allow later candidates to improve a full list, then stop at a plateau."""
        if self.useful_count() < self.target:
            self.shortlist_quality = None
            self.unimproved_reviews = 0
            return
        completeness = {"complete": 0, "partial": 1, "unavailable": 2}
        quality = tuple(
            sorted(
                (
                    recommendation_key(item)[0],
                    recommendation_key(item)[1],
                    completeness[item.analysis_status],
                )
                for item in self.ranked(list(self.matched.values()))
            )
        )
        if self.shortlist_quality is None or quality < self.shortlist_quality:
            self.unimproved_reviews = 0
            self.shortlist_quality = quality
        else:
            self.unimproved_reviews += 1
        if self.unimproved_reviews >= MAX_UNIMPROVED_REVIEWS and not self.stop_event.is_set():
            raise SearchEnded("results_ready")

    def useful_count(self) -> int:
        return sum(
            item.analysis_status != "unavailable"
            and item.recommendation_fit in {"recommended", "possible"}
            for item in self.matched.values()
        )

    def observation(self) -> dict[str, Any]:
        candidates = sorted(
            self.jobs.values(),
            key=lambda job: (
                job.job_id in self.assessed_ids,
                self.attempts.get(job.job_id, 0),
            ),
        )[: self.candidate_limit]
        return {
            "remaining_seconds": round(
                max(0, self.deadline - asyncio.get_running_loop().time()), 2
            ),
            "remaining_decisions": MAX_DECISIONS - self.decision_count,
            "result_limit": self.target,
            "matched_count": len(self.matched),
            "useful_count": self.useful_count(),
            "pending_count": len(self.pending),
            "analyzed_count": len(self.assessed_ids),
            "unimproved_reviews": self.unimproved_reviews,
            "remaining_candidates": max(0, self.candidate_limit - len(self.attempts)),
            "duplicate_count": self.duplicate_count,
            "shortlist": [
                {
                    "job_id": item.job.job_id,
                    "fit": item.recommendation_fit,
                    "reason": item.recommendation_reason,
                    "analysis_status": item.analysis_status,
                }
                for item in self.ranked(list(self.matched.values()))[:5]
            ],
            "queries": [
                {
                    **{
                        key: query[key]
                        for key in ("direction", "source", "keywords", "page", "new_jobs", "errors")
                    },
                    "outcomes": [{"status": outcome["status"]} for outcome in query["outcomes"]],
                }
                for query in self.query_history
            ],
            "unexhausted_pairs": self.unexhausted_pairs(),
            "candidates": [
                {
                    "job_id": job.job_id,
                    "title": job.title,
                    "source": job.source,
                    "direction": job.target_direction,
                    "location": job.location,
                    "employment_type": job.employment_type,
                    "summary": job.description[:700],
                    "salary": job.salary,
                    "needs_details": not job.has_full_description(),
                    "detail_attempts": self.detail_attempts.get(job.job_id, 0),
                    "analysis_attempts": self.attempts.get(job.job_id, 0),
                    "analysis_diagnostic": self.analysis_diagnostics[job.job_id].model_dump()
                    if job.job_id in self.analysis_diagnostics
                    else None,
                }
                for job in candidates
            ],
        }

    def result(self, reason: str | None = None, *, final: bool = False) -> RecommendationResult:
        selected = self.ranked([*self.matched.values(), *self.pending.values()])

        def displayed(items: list[RecommendationItem]) -> list[RecommendationItem]:
            return [
                item.model_copy(
                    update={
                        "review_status": "not_reviewed",
                        "review_issue": ReviewIssue(
                            code="stopped" if reason == "user_stopped" else "search_ended"
                        ),
                    }
                )
                if final and item.review_status in {"queued", "reviewing"}
                else item
                for item in self.ranked(items)
            ]

        return finalize_recommendation(
            RecommendationResult(
                session_id=self.session_id,
                generated_at=datetime.now(UTC),
                jobs=displayed([item for item in selected if item.job.job_id in self.matched]),
                pending_jobs=displayed(
                    [item for item in selected if item.job.job_id in self.pending]
                ),
                introduction=self.finish_message(reason) if reason else "",
            )
        )

    def unexhausted_pairs(self) -> list[dict[str, Any]]:
        pending: list[dict[str, Any]] = []
        for direction in self.profile.target_directions:
            for source in self.sources:
                queries = [
                    query
                    for query in self.query_history
                    if query["direction"] == direction and query["source"] == source
                ]
                if not queries:
                    pending.append(
                        {
                            "direction": direction,
                            "source": source,
                            "next_page": 1,
                            "next_action": "search",
                        }
                    )
                    continue
                variants: dict[tuple[str, ...], list[dict[str, Any]]] = {}
                for query in queries:
                    key = tuple(
                        sorted({" ".join(word.casefold().split()) for word in query["keywords"]})
                    )
                    variants.setdefault(key, []).append(query)
                base = {"direction": direction, "source": source}
                empty_variants = 0
                limited = False
                for attempts in variants.values():
                    latest = attempts[-1]
                    errors = latest["errors"]
                    outcomes = latest["outcomes"]
                    if errors and not latest["returned_jobs"]:
                        retryable = all(code in _RETRYABLE_SEARCH_ERRORS for code in errors)
                        page_attempts = sum(row["page"] == latest["page"] for row in attempts)
                        if retryable and page_attempts < 2:
                            pending.append(
                                {
                                    **base,
                                    "next_page": latest["page"],
                                    "next_action": "retry",
                                    "keywords": latest["keywords"],
                                }
                            )
                        # Unavailable sources are reported separately, not described as empty pages.
                        continue
                    if (
                        not latest["returned_jobs"]
                        and outcomes
                        and all(row["status"] not in {"ok", "empty", "partial"} for row in outcomes)
                    ):
                        continue
                    empty = (
                        not latest["returned_jobs"]
                        and not latest["candidate_count"]
                        and bool(outcomes)
                        and all(row["status"] == "empty" for row in outcomes)
                    )
                    if empty:
                        empty_variants += 1
                    elif latest["page"] < 5:
                        pending.append(
                            {
                                **base,
                                "next_page": latest["page"] + 1,
                                "next_action": "next_page",
                                "keywords": latest["keywords"],
                            }
                        )
                    else:
                        limited = True
                # An empty query is not proof that a source has no relevant jobs.
                # Require an alternative formulation; repeated pages retain pagination.
                if limited or empty_variants == 1 and len(variants) == 1:
                    pending.append(
                        {
                            **base,
                            "next_page": 1,
                            "next_action": "rephrase",
                            "tried_keywords": [row[-1]["keywords"] for row in variants.values()],
                            "page_limit_reached": limited,
                        }
                    )
        return pending

    def ranked(self, items: list[RecommendationItem]) -> list[RecommendationItem]:
        """Rank all batches together by overall fit, without direction quotas."""
        return sorted(items, key=recommendation_key)[: self.target]

    def progress(self) -> dict[str, Any]:
        selected = self.ranked([*self.matched.values(), *self.pending.values()])
        return {
            "sequence": self.progress_seq,
            "discovered_count": len(self.jobs),
            "analyzed_count": len(self.assessed_ids),
            "matched_count": sum(item.job.job_id in self.matched for item in selected),
            "pending_count": sum(item.job.job_id in self.pending for item in selected),
            "elapsed_seconds": round(max(0, asyncio.get_running_loop().time() - self.started), 3),
            "retrieval_stopped": self.stop_event.is_set(),
            "events": self.events[-80:],
            "activity": [item.model_dump(mode="json") for item in self.activity()],
        }

    def activity(self) -> list[SearchActivity]:
        """Expose screening facts without private model diagnostics or the result cap."""
        excluded = eligibility_exclusions(self.profile, list(self.jobs.values()))
        shortlisted = {item.job.job_id for item in self.ranked(list(self.matched.values()))}
        activity: list[SearchActivity] = []
        for job in self.jobs.values():
            item = self.matched.get(job.job_id) or self.pending.get(job.job_id)
            issue = self.analysis_diagnostics.get(job.job_id)
            reasons = excluded.get(job.job_id, []) or (issue.exclusion_reasons if issue else [])
            public_issue = item.review_issue if item else None
            status: JobStatus
            if reasons or (issue and issue.code == "condition_mismatch"):
                status = (
                    "expired"
                    if "expired" in reasons
                    else "duplicate"
                    if "duplicate" in reasons
                    else "excluded"
                )
            elif item:
                status = item.display_status(active=not self.finished)
                if status == "reviewed" and job.job_id not in shortlisted:
                    status = "not_shortlisted"
                if status == "not_reviewed" and self.finished and public_issue is None:
                    public_issue = ReviewIssue(
                        code="stopped" if self.stop_event.is_set() else "search_ended"
                    )
            elif issue:
                public_issue = issue.review_issue()
                status = issue_status(public_issue)
            else:
                status = "not_reviewed" if self.finished else "found"
                if self.finished:
                    public_issue = ReviewIssue(
                        code="stopped" if self.stop_event.is_set() else "search_ended"
                    )
            entry = SearchActivity(
                sequence=self.progress_seq,
                job_id=job.job_id,
                title=job.title,
                company=job.company,
                location=job.location,
                status=status,
                review_issue=public_issue,
                exclusion_reasons=reasons,
                unknown_conditions=item.unknown_conditions if item else [],
                recommendation_fit=item.recommendation_fit
                if item
                and item.review_status == "reviewed"
                and item.analysis_status != "unavailable"
                else "unknown",
            )
            previous = self.activity_entries.get(job.job_id)
            if (
                previous is not None
                and previous.model_copy(update={"sequence": self.progress_seq}) == entry
            ):
                entry = previous
            self.activity_entries[job.job_id] = entry
            activity.append(entry)
        return activity

    async def publish(
        self,
        action: str,
        message: str,
        *,
        source: str | None = None,
        stop_reason: str | None = None,
    ) -> None:
        self.progress_seq += 1
        self.events.append(
            {"sequence": self.progress_seq, "action": action, "message": message, "source": source}
        )
        if self.on_progress is not None:
            await self.on_progress(
                {
                    "run_id": self.run_id,
                    "progress_seq": self.progress_seq,
                    "progress": self.progress(),
                    "recommendation": self.result(stop_reason, final=action == "search_finished"),
                    "source_outcomes": list(self.outcomes),
                    "stop_reason": stop_reason,
                }
            )

    def finish_message(self, reason: str | None) -> str:
        selected = self.ranked([*self.matched.values(), *self.pending.values()])
        count = len(selected)
        promising = sum(
            item.analysis_status != "unavailable"
            and item.recommendation_fit in {"recommended", "possible"}
            for item in selected
        )
        counts = f"Found {count} {'job' if count == 1 else 'jobs'}."
        if promising:
            counts += f" {promising} worth exploring based on the available information."
        detail = {
            "target_reached": "",
            "results_ready": "Search complete. Review the opportunities found so far.",
            "source_exhausted": "The available sources returned no further opportunities for this search.",
            "budget_exhausted": "The search reached its time or analysis limit. Results found so far are available.",
            "user_stopped": "Search stopped.",
            "error": "The search could not continue.",
        }.get(reason or "", "")
        return f"{counts} {detail}".strip()
