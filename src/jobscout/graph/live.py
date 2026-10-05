"""Production async graph. Only dedicated wait nodes contain interrupts."""

import asyncio
import inspect
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Overwrite, interrupt

from jobscout.graph.state import AgentState
from jobscout.schemas.conversation import ConversationMessage, ConversationResponse, SearchSummary
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import JobPosting, SourceDocument
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import ClarificationStatus, SearchRequest
from jobscout.schemas.session import SessionResumeRequest
from jobscout.services.conversation_service import (
    BACKGROUND_FIELDS,
    EDITABLE_FIELDS,
    ConversationService,
    ProfileChange,
    apply_changes,
    missing_fields,
    profile_documents,
)
from jobscout.services.evidence_service import EvidenceService, eligible_jobs
from jobscout.services.job_processing_service import process_jobs, select_balanced_candidates
from jobscout.services.job_retrieval.models import SearchResult
from jobscout.services.job_search_service import JobSearchService
from jobscout.services.llm_service import LLMProvider, ModelServiceError
from jobscout.services.profile_service import dedupe
from jobscout.services.recommendation_service import recommend_jobs

OPERATION_SECONDS = 180.0
RETRIEVAL_SECONDS = 60.0
MAX_CANDIDATES = 20
logger = logging.getLogger(__name__)
_USAGE_FIELDS = (
    "structured_calls",
    "successful_calls",
    "failed_calls",
    "cancellations",
    "requests",
    "retries",
    "repairs",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
)
_SAFE_ERROR_CODES = {
    "profile_input",
    "invalid_answer",
    "search_unavailable",
    "operation_timeout",
    "search_plan",
    "normalization_failed",
    "model_configuration",
    "model_input",
    "model_auth",
    "model_timeout",
    "model_transport",
    "model_http",
    "model_output",
}
_CONFIRM_MESSAGES = {
    "确认",
    "确认搜索",
    "确认检索",
    "开始搜索",
    "开始检索",
    "confirm",
    "confirm search",
    "search now",
}
_FIELD_LABELS = {
    "education": "Education",
    "skills": "Skills",
    "internships": "Internships",
    "projects": "Projects",
    "target_directions": "Job directions",
    "preferences.location": "Work location",
    "preferences.location_unrestricted": "Work location",
    "preferences.employment_type": "Employment type",
    "preferences.employment_type_unrestricted": "Employment type",
    "preferences.salary_range": "Expected salary",
    "preferences.work_mode": "Work arrangement",
    "preferences.industry": "Industry preference",
}
_PREFERENCE_LABELS = {
    "preferences.employment_type": {
        "full-time": "Full-time",
        "part-time": "Part-time",
        "internship": "Internship",
        "contract": "Contract",
        "freelance": "Freelance",
        "unrestricted": "No preference",
    },
    "preferences.work_mode": {
        "onsite": "On-site",
        "on-site": "On-site",
        "hybrid": "Hybrid",
        "remote": "Remote",
        "unrestricted": "No preference",
    },
}


def _display_value(field: str, value: str | list[str] | bool | None) -> str | list[str]:
    if isinstance(value, list):
        return value if value else "Not provided"
    if isinstance(value, bool):
        return "No preference" if value else "As specified"
    if value is None or not value.strip():
        return "Not provided"
    return _PREFERENCE_LABELS.get(field, {}).get(value.casefold(), value)


def _edited_responses(
    request: SessionResumeRequest, profile: UserProfile
) -> list[ConversationResponse]:
    responses: list[ConversationResponse] = []
    displayed: set[str] = set()
    for field, value in request.profile_updates.items():
        primary = field.removesuffix("_unrestricted")
        if primary in displayed:
            continue
        displayed.add(primary)
        if primary in {"preferences.location", "preferences.employment_type"}:
            name = primary.removeprefix("preferences.")
            unrestricted = getattr(profile.preferences, name + "_unrestricted")
            value = "No preference" if unrestricted else getattr(profile.preferences, name)
        responses.append(
            ConversationResponse(label=_FIELD_LABELS[field], value=_display_value(primary, value))
        )
    return responses


class SearchService(Protocol):
    async def search_many_async(
        self, requests: Sequence[SearchRequest], *, timeout: float = 60
    ) -> SearchResult: ...


class AssessmentService(Protocol):
    async def assess(
        self,
        profile: UserProfile,
        jobs: list[JobPosting],
        profile_documents: dict[str, str],
        session_id: str,
        deadline: float | None = None,
    ) -> RecommendationResult: ...


def _message(role: str, text: str, question_ids: list[str] | None = None) -> ConversationMessage:
    return ConversationMessage(
        message_id=uuid4().hex, role=cast(Any, role), text=text, question_ids=question_ids or []
    )


def _failure(code: str, stage: str, *, retryable: bool = True) -> dict[str, Any]:
    messages = {
        "profile_input": "Provide a resume or personal introduction, then try again.",
        "invalid_answer": "The answer format is invalid. Check the question options or edit your criteria directly.",
        "search_unavailable": "Job sources are temporarily unavailable. Try again later.",
        "operation_timeout": "This search reached its time limit. Please try again.",
        "model_auth": "Model service authentication failed. Check the service configuration.",
    }
    return {
        "current_stage": "failed",
        "outcome": "failed",
        "retryable": retryable,
        "errors": [
            WorkflowError(
                code=code,
                message=messages.get(
                    code, "Analysis did not finish. Your input has been saved; you can try again."
                ),
                stage=stage,
            )
        ],
    }


def build_live_graph(
    checkpointer: BaseCheckpointSaver[Any] | None,
    provider: LLMProvider,
    search_service: SearchService | None = None,
    *,
    evidence_factory: Callable[[LLMProvider], AssessmentService] | None = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    conversation = ConversationService(provider)
    search = search_service if search_service is not None else JobSearchService()
    factory = evidence_factory or EvidenceService
    evidence: dict[str, AssessmentService] = {}
    evidence_search_ids: dict[str, str] = {}

    async def cleanup_session(session_id: str) -> None:
        """Dispose session evidence after its operation has been cancelled/awaited."""
        service = evidence.pop(session_id, None)
        evidence_search_ids.pop(session_id, None)
        cleanup = getattr(service, "cleanup_session", None)
        if callable(cleanup):
            result = cleanup(session_id)
            if inspect.isawaitable(result):
                await result

    async def session_evidence(
        session_id: str, revision: int, snapshot: dict[str, object] | None = None
    ) -> AssessmentService:
        if session_id not in evidence:
            service = factory(provider)
            restore = getattr(service, "import_cache", None)
            if snapshot and callable(restore):
                try:
                    restore(snapshot, session_id)
                except Exception:
                    logger.warning(
                        "workflow_cache_rejected", extra={"error_code": "invalid_checkpoint_cache"}
                    )
                    service = factory(provider)
            evidence[session_id] = service
        service = evidence[session_id]
        search_id = f"{session_id}:{revision}"
        if evidence_search_ids.get(session_id) != search_id:
            begin = getattr(service, "begin_search", None)
            if callable(begin):
                result = begin(search_id)
                if inspect.isawaitable(result):
                    await result
            evidence_search_ids[session_id] = search_id
        return service

    def entry(state: AgentState) -> dict[str, Any]:
        reset: dict[str, Any] = {
            "errors": Overwrite([]),
            "warnings": Overwrite([]),
            "outcome": "running",
            "retryable": False,
            "recommendation": None,
            "search_summary": None,
            "confirmed_profile": None,
            "assessment": None,
            "source_outcomes": [],
            "search_requests": [],
            "raw_jobs": [],
            "normalized_jobs": [],
            "analysis_jobs": [],
            "analyzed_job_ids": [],
            "retrieval_round": 0,
            "retrieval_seconds": 0.0,
            "operation_deadline": 0.0,
            "resume_payload": {},
            "failed_resume_payload": None,
            "clarification_questions": [],
            "current_stage": "profile",
        }
        command = state.get("command")
        if command is None:
            return reset
        try:
            request = SessionResumeRequest.model_validate(command)
            if request.action not in {"edit_conditions", "retry"}:
                raise ValueError("Entry commands only support editing and retry.")
            reset.update(
                {
                    "revision": request.expected_revision + 1,
                    "resume_payload": request.model_dump(),
                    "current_stage": "edit_conditions"
                    if state.get("profile") is not None
                    else "profile",
                    "optional_rounds": 3
                    if state.get("profile") is not None
                    else state.get("optional_rounds", 0),
                }
            )
            failed_payload = state.get("failed_resume_payload")
            if request.action == "retry" and failed_payload:
                reset.update(
                    {
                        "resume_payload": {
                            **failed_payload,
                            "expected_revision": request.expected_revision,
                        },
                        "clarification_questions": state.get("clarification_questions", []),
                        "optional_rounds": state.get("optional_rounds", 0),
                    }
                )
            return reset
        except Exception:
            failure = _failure("invalid_answer", "profile")
            failure["errors"] = Overwrite(failure["errors"])
            return reset | failure | {"command": None}

    def entry_route(state: AgentState) -> str:
        if state.get("current_stage") == "failed":
            return "failed"
        return "apply" if state.get("current_stage") == "edit_conditions" else "extract"

    async def extract(state: AgentState) -> dict[str, Any]:
        try:
            inputs = state.get("input_data", {})
            source_documents = profile_documents(inputs, state["session_id"])
            documents = list(state.get("profile_documents", [])) or source_documents
            if not source_documents:
                return _failure("profile_input", "profile")
            profile = state.get("profile")
            if profile is None:
                profile = await conversation.extract(inputs, state["session_id"])
            history = list(state.get("conversation", []))
            if not history:
                history.append(
                    _message("user", str(inputs.get("description") or "Resume uploaded."))
                )
            return {
                "profile": profile,
                "profile_documents": documents,
                "conversation": history,
                "revision": state.get("revision", 0),
                "current_stage": "validate",
                "outcome": "running",
                "retryable": False,
                "recommendation": None,
                "search_summary": None,
                "confirmed_profile": None,
                "optional_rounds": state.get("optional_rounds", 0),
                "required_attempts": state.get("required_attempts", {}),
                "suppressed_fields": state.get("suppressed_fields", []),
                "question_turn": state.get("question_turn", 0),
                "direct_edit_fields": [],
                "source_outcomes": [],
                "raw_jobs": [],
                "normalized_jobs": [],
                "analysis_jobs": [],
                "analyzed_job_ids": [],
                "retrieval_seconds": 0.0,
                "retrieval_round": 0,
            }
        except asyncio.CancelledError:
            raise
        except ModelServiceError as error:
            return _failure(error.code, "profile")
        except Exception:
            return _failure("profile_input", "profile")

    def validate(state: AgentState) -> dict[str, Any]:
        profile = state["profile"]
        assert profile is not None
        missing = missing_fields(profile)
        attempts = state.get("required_attempts", {})
        direct = [field for field in missing if attempts.get(field, 0) >= 2]
        return {
            "profile": profile.model_copy(update={"missing_required_fields": missing}),
            "direct_edit_fields": direct,
            "current_stage": "validate",
        }

    def validation_route(state: AgentState) -> str:
        profile = state["profile"]
        assert profile is not None
        if state.get("direct_edit_fields"):
            return "build_summary"
        if profile.missing_required_fields or state.get("optional_rounds", 0) < 3:
            return "generate_question"
        return "build_summary"

    async def generate_question(state: AgentState) -> dict[str, Any]:
        profile = state["profile"]
        assert profile is not None
        turn = state.get("question_turn", 0) + 1
        try:
            questions = await conversation.questions(
                profile, profile.missing_required_fields, state.get("suppressed_fields", []), turn
            )
        except asyncio.CancelledError:
            raise
        except ModelServiceError as error:
            if error.code == "model_auth":
                return _failure(error.code, "clarify")
            # A failed question model must not trap users behind another model call.
            return {
                "clarification_questions": [],
                "direct_edit_fields": profile.missing_required_fields,
                "warnings": [
                    "Follow-up question generation is unavailable. Edit your criteria directly in the summary."
                ],
            }
        except Exception:
            return {
                "clarification_questions": [],
                "direct_edit_fields": profile.missing_required_fields,
                "warnings": [
                    "Follow-up question generation is unavailable. Edit your criteria directly in the summary."
                ],
            }
        history = list(state.get("conversation", []))
        if questions:
            history.append(
                _message(
                    "assistant",
                    "Please provide the following information. You can also enter corrections or skip optional questions.\n"
                    + "\n".join(question.question for question in questions),
                    [q.question_id for q in questions],
                )
            )
        return {
            "clarification_questions": questions,
            "question_turn": turn,
            "conversation": history,
            "current_stage": "clarify",
            "outcome": "paused" if questions else "running",
        }

    def accept_resume(state: AgentState, payload: object) -> dict[str, Any]:
        request = SessionResumeRequest.model_validate(payload)
        revision = request.expected_revision + 1
        summary = state.get("search_summary")
        return {
            "resume_payload": request.model_dump(),
            "revision": revision,
            "search_summary": summary.model_copy(update={"revision": revision, "confirmed": False})
            if summary is not None
            else None,
            "confirmed_profile": None,
            "recommendation": None,
            "outcome": "running",
            "current_stage": "validate",
        }

    def await_answers(state: AgentState) -> dict[str, Any]:
        payload = interrupt(
            {
                "kind": "clarification",
                "questions": [
                    q.model_dump(mode="json") for q in state.get("clarification_questions", [])
                ],
                "revision": state.get("revision", 0),
            }
        )
        return accept_resume(state, payload)

    async def apply(state: AgentState) -> dict[str, Any]:
        profile = state["profile"]
        assert profile is not None
        accepted_revision = state.get("revision", 1)
        try:
            request = SessionResumeRequest.model_validate(state["resume_payload"])
            accepted_revision = request.expected_revision + 1
            questions = list(state.get("clarification_questions", []))
            by_id = {question.question_id: question for question in questions}
            answer_ids = [answer.question_id for answer in request.answers]
            if (
                len(set(answer_ids)) != len(answer_ids)
                or any(qid not in by_id for qid in [*answer_ids, *request.skipped_question_ids])
                or set(answer_ids) & set(request.skipped_question_ids)
            ):
                raise ValueError("Unknown, duplicate or conflicting question IDs.")
            updates: list[ProfileChange] = []
            responses: list[ConversationResponse] = []
            statuses: dict[str, tuple[ClarificationStatus, str | None]] = {}
            for answer in request.answers:
                question = by_id[answer.question_id]
                values = answer.value if isinstance(answer.value, list) else [answer.value]
                if question.control_type == "single_choice" and len(values) != 1:
                    raise ValueError("Single choice requires one answer.")
                options = {option.id: option.label for option in question.options}
                if question.control_type != "text" and options:
                    if any(value not in options for value in values):
                        raise ValueError("Unknown option ID.")
                    values = [options[value] for value in values]
                value: str | list[str] = (
                    values
                    if isinstance(answer.value, list)
                    and question.field in (*BACKGROUND_FIELDS, "target_directions")
                    else ", ".join(values)
                )
                if any(item.strip() for item in values):
                    updates.append(ProfileChange(field=question.field, value=value))
                    statuses[question.question_id] = (
                        ClarificationStatus.ANSWERED,
                        ", ".join(values),
                    )
                    responses.append(
                        ConversationResponse(
                            label=question.question,
                            value=_display_value(question.field, value),
                        )
                    )
            # Apply free-text corrections after structured answers, then explicit editor patches.
            profile = apply_changes(profile, updates)
            is_confirm = (
                request.action == "confirm_search"
                or request.message.strip().casefold().rstrip("。.!！") in _CONFIRM_MESSAGES
            )
            text_changes = (
                []
                if request.message.strip().casefold().rstrip("。.!！") in _CONFIRM_MESSAGES
                else await conversation.interpret(profile, request.message)
            )
            profile = apply_changes(profile, text_changes)
            profile = apply_changes(
                profile,
                [
                    ProfileChange(field=field, value=value)
                    for field, value in request.profile_updates.items()
                ],
            )
            original = state["profile"]
            assert original is not None
            changed = profile.model_dump(
                exclude={"confirmed_fields", "missing_required_fields"}
            ) != original.model_dump(exclude={"confirmed_fields", "missing_required_fields"})
            remaining = missing_fields(profile)
            attempts = dict(state.get("required_attempts", {}))
            suppressed = list(state.get("suppressed_fields", []))
            for question in questions:
                if question.required and question.field in remaining:
                    attempts[question.field] = attempts.get(question.field, 0) + 1
                if not question.required:
                    suppressed.append(question.field)
                if question.question_id in request.skipped_question_ids and not question.required:
                    statuses[question.question_id] = (ClarificationStatus.SKIPPED, None)
                    responses.append(
                        ConversationResponse(
                            label=question.question, value="Skipped", status="skipped"
                        )
                    )
            questions = [
                question.model_copy(
                    update={
                        "status": statuses[question.question_id][0],
                        "answer": statuses[question.question_id][1],
                    }
                )
                if question.question_id in statuses
                else question
                for question in questions
            ]
            history = [
                *state.get("conversation", []),
                _message(
                    "user",
                    request.message.strip()
                    or (
                        "Search confirmed."
                        if is_confirm
                        else "Answer submitted or criteria updated."
                    ),
                ),
            ]
            history[-1] = history[-1].model_copy(
                update={"responses": [*responses, *_edited_responses(request, profile)]}
            )
            documents = list(state.get("profile_documents", []))
            evidence_text = "\n".join(
                filter(
                    None,
                    [
                        request.message,
                        *(f"{change.field}: {change.value}" for change in updates),
                        *(f"{field}: {value}" for field, value in request.profile_updates.items()),
                    ],
                )
            )
            if evidence_text:
                documents.append(
                    SourceDocument(
                        document_id=f"profile:{state['session_id']}:answer:{request.request_id}",
                        source="user",
                        source_url="",
                        text=evidence_text,
                        fetched_at=datetime.now(UTC),
                    )
                )
            summary = state.get("search_summary")
            can_confirm = (
                is_confirm
                and not changed
                and not remaining
                and summary is not None
                and summary.ready
                and request.action != "edit_conditions"
            )
            result: dict[str, Any] = {
                "profile": profile.model_copy(update={"missing_required_fields": remaining}),
                "revision": accepted_revision,
                "command": None,
                "failed_resume_payload": None,
                "conversation": history,
                "profile_documents": documents,
                "clarification_questions": questions,
                "required_attempts": attempts,
                "suppressed_fields": dedupe(suppressed),
                "optional_rounds": 3
                if summary is not None
                else state.get("optional_rounds", 0) + int(any(not q.required for q in questions)),
                "confirmed_profile": None,
                "search_summary": None,
                "recommendation": None,
                "current_stage": "edit_conditions"
                if request.action == "edit_conditions"
                else "validate",
                "outcome": "running",
            }
            if can_confirm:
                confirmed = profile.model_copy(
                    deep=True, update={"confirmed_fields": list(EDITABLE_FIELDS)}
                )
                result.update(
                    {
                        "confirmed_profile": confirmed,
                        "profile": confirmed,
                        "search_summary": SearchSummary(
                            profile=confirmed.model_copy(deep=True),
                            revision=accepted_revision,
                            ready=True,
                            confirmed=True,
                            editable_fields=list(EDITABLE_FIELDS),
                        ),
                        "operation_deadline": asyncio.get_running_loop().time() + OPERATION_SECONDS,
                        "retrieval_seconds": 0.0,
                        "retrieval_round": 0,
                        "raw_jobs": [],
                        "normalized_jobs": [],
                        "analysis_jobs": [],
                        "analyzed_job_ids": [],
                        "source_outcomes": [],
                        "current_stage": "plan",
                    }
                )
                async with asyncio.timeout_at(result["operation_deadline"]):
                    await session_evidence(
                        state["session_id"], accepted_revision, state.get("jd_cache")
                    )
            return result
        except asyncio.CancelledError:
            raise
        except ModelServiceError as error:
            return _failure(error.code, "clarify") | {
                "revision": accepted_revision,
                "command": None,
                "failed_resume_payload": state.get("resume_payload"),
            }
        except Exception:
            return _failure("invalid_answer", "clarify") | {
                "revision": accepted_revision,
                "command": None,
            }

    def build_summary(state: AgentState) -> dict[str, Any]:
        profile = state["profile"]
        assert profile is not None
        missing = missing_fields(profile)
        summary = SearchSummary(
            profile=profile.model_copy(deep=True),
            revision=state.get("revision", 0),
            ready=not missing,
            editable_fields=list(EDITABLE_FIELDS),
            missing_fields=missing,
        )
        text = (
            "Review and confirm your search criteria. The search will begin after you confirm."
            if summary.ready
            else "Some required criteria still need confirmation. Edit the summary directly; choose up to three directions and select a supported location or no preference."
        )
        return {
            "search_summary": summary,
            "clarification_questions": [],
            "current_stage": "confirm",
            "outcome": "paused",
            "conversation": [*state.get("conversation", []), _message("assistant", text)],
        }

    def await_confirmation(state: AgentState) -> dict[str, Any]:
        summary = state.get("search_summary")
        payload = interrupt(
            {
                "kind": "confirmation",
                "summary": summary.model_dump(mode="json") if summary else None,
                "revision": state.get("revision", 0),
            }
        )
        return accept_resume(state, payload)

    async def plan(state: AgentState) -> dict[str, Any]:
        profile = state["confirmed_profile"]
        assert profile is not None
        try:
            async with asyncio.timeout_at(state["operation_deadline"]):
                requests = await conversation.plan(
                    profile.model_copy(deep=True),
                    round_number=state.get("retrieval_round", 0) + 1,
                    deadline=state["operation_deadline"],
                )
            return {"search_requests": requests, "current_stage": "retrieve"}
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return _failure("operation_timeout", "plan")
        except ModelServiceError as error:
            return _failure(error.code, "plan")
        except Exception:
            return _failure("search_plan", "plan")

    async def retrieve(state: AgentState) -> dict[str, Any]:
        start = asyncio.get_running_loop().time()
        budget = min(
            RETRIEVAL_SECONDS - state.get("retrieval_seconds", 0.0),
            state["operation_deadline"] - start,
        )
        if budget <= 0:
            return {
                "retrieval_round": 2,
                "warnings": [
                    "The cumulative search time limit was reached. Keeping the jobs found so far."
                ],
            }
        try:
            async with asyncio.timeout(budget):
                # Let cooperative sources aggregate completed results before our hard cutoff.
                source_budget = max(0.0, budget - min(0.05, budget * 0.05))
                found = await search.search_many_async(
                    state.get("search_requests", []), timeout=source_budget
                )
            raw = [
                *state.get("raw_jobs", []),
                *(job.model_dump(mode="json") for job in found.raw_jobs),
            ]
            outcomes = [*state.get("source_outcomes", []), *found.outcomes]
            successful = bool(raw) or any(
                outcome.status in {"ok", "empty", "partial", "success"} for outcome in outcomes
            )
            if not successful and (found.errors or outcomes):
                return _failure("search_unavailable", "retrieve") | {
                    "source_outcomes": outcomes,
                    "warnings": found.warnings,
                }
            return {
                "raw_jobs": raw,
                "source_outcomes": outcomes,
                "warnings": [
                    *found.warnings,
                    *(
                        f"Some sources could not be searched: {error.code}"
                        for error in found.errors
                    ),
                ],
                "retrieval_seconds": state.get("retrieval_seconds", 0.0)
                + asyncio.get_running_loop().time()
                - start,
                "retrieval_round": state.get("retrieval_round", 0) + 1,
                "current_stage": "normalize",
            }
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            if state.get("raw_jobs"):
                return {
                    "retrieval_round": 2,
                    "retrieval_seconds": RETRIEVAL_SECONDS,
                    "warnings": [
                        "The search timed out. Keeping the jobs found in the previous round."
                    ],
                }
            return _failure("operation_timeout", "retrieve")
        except Exception:
            if state.get("raw_jobs"):
                return {
                    "retrieval_round": 2,
                    "warnings": [
                        "The additional search did not finish. Keeping the jobs found in the previous round."
                    ],
                }
            return _failure("search_unavailable", "retrieve")

    def normalize(state: AgentState) -> dict[str, Any]:
        try:
            profile = state["confirmed_profile"]
            assert profile is not None
            jobs, warnings = process_jobs(state.get("raw_jobs", []))
            eligible = eligible_jobs(profile, jobs)
            old_ids = set(state.get("analyzed_job_ids", []))
            retained = [job for job in eligible if job.job_id in old_ids]
            added = select_balanced_candidates(
                [job for job in eligible if job.job_id not in old_ids],
                limit=max(0, MAX_CANDIDATES - len(old_ids)),
            )
            selected = [*retained, *added]
            return {
                "normalized_jobs": jobs,
                "analysis_jobs": selected,
                "analyzed_job_ids": dedupe(
                    [*state.get("analyzed_job_ids", []), *(job.job_id for job in added)]
                ),
                "warnings": warnings,
                "current_stage": "understand",
            }
        except Exception:
            return _failure("normalization_failed", "normalize")

    async def understand(state: AgentState) -> dict[str, Any]:
        profile = state["confirmed_profile"]
        assert profile is not None
        try:
            async with asyncio.timeout_at(state["operation_deadline"]):
                service = await session_evidence(
                    state["session_id"], state["revision"], state.get("jd_cache")
                )
                assessment = await service.assess(
                    profile.model_copy(deep=True),
                    state.get("analysis_jobs", []),
                    {
                        document.document_id: document.text
                        for document in state.get("profile_documents", [])
                    },
                    state["session_id"],
                    deadline=state["operation_deadline"],
                )
            update: dict[str, Any] = {"assessment": assessment, "current_stage": "coverage"}
            export = getattr(service, "export_cache", None)
            if callable(export):
                try:
                    update["jd_cache"] = export()
                except Exception:
                    update["warnings"] = [
                        "Job analysis finished, but the cache was not saved. A later search may need to analyze these jobs again."
                    ]
                    logger.warning(
                        "workflow_cache_export_failed",
                        extra={"error_code": "checkpoint_cache_unavailable"},
                    )
            return update
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return _failure("operation_timeout", "understand")
        except Exception:
            assessment = recommend_jobs(
                profile, state.get("analysis_jobs", []), session_id=state["session_id"]
            )
            return {
                "assessment": assessment,
                "current_stage": "coverage",
                "warnings": [
                    "Model evidence analysis did not finish. Keeping the deterministic analysis results."
                ],
            }

    def coverage(state: AgentState) -> dict[str, Any]:
        return {"current_stage": "coverage"}

    async def coverage_route(state: AgentState) -> str:
        profile = state["confirmed_profile"]
        assert profile is not None
        remaining = state["operation_deadline"] - asyncio.get_running_loop().time()
        if (
            len(eligible_jobs(profile, state.get("normalized_jobs", []))) < 5
            and state.get("retrieval_round", 0) < 2
            and state.get("retrieval_seconds", 0.0) < RETRIEVAL_SECONDS
            and remaining > 0
        ):
            return "plan"
        return "recommend"

    async def recommend(state: AgentState) -> dict[str, Any]:
        if asyncio.get_running_loop().time() >= state["operation_deadline"]:
            return _failure("operation_timeout", "recommend")
        return {"recommendation": state.get("assessment"), "current_stage": "present"}

    async def present(state: AgentState) -> dict[str, Any]:
        if (
            state.get("current_stage") == "failed"
            or asyncio.get_running_loop().time() >= state["operation_deadline"]
        ):
            return _failure("operation_timeout", "present")
        result = state.get("recommendation") or RecommendationResult(
            session_id=state["session_id"], generated_at=datetime.now(UTC)
        )
        intro = (
            f"Found {len(result.jobs)} jobs matching your confirmed criteria. Check the source links to verify the details."
            if result.jobs
            else "No jobs matched your confirmed criteria. We did not broaden your search automatically; you can edit your criteria and search again."
        )
        result = result.model_copy(
            update={
                "introduction": intro,
                "warnings": dedupe([*result.warnings, *state.get("warnings", [])]),
            }
        )
        return {
            "recommendation": result,
            "conversation": [*state.get("conversation", []), _message("assistant", intro)],
            "current_stage": "completed",
            "outcome": "completed",
            "retryable": False,
        }

    def failed(state: AgentState) -> dict[str, Any]:
        return {"current_stage": "failed", "outcome": "failed"}

    def after_apply(state: AgentState) -> str:
        if state.get("current_stage") == "failed":
            return "failed"
        if state.get("confirmed_profile") is not None:
            return "plan"
        if (
            state.get("search_summary") is not None
            or state.get("current_stage") == "edit_conditions"
        ):
            return "build_summary"
        return "validate"

    def usage_snapshot() -> dict[str, int]:
        try:
            usage = getattr(provider, "usage", None)
            return {
                field: value
                for field in _USAGE_FIELDS
                if isinstance(value := getattr(usage, field, None), int)
                and not isinstance(value, bool)
                and value >= 0
            }
        except Exception:
            return {}

    def timed(stage: str, node: Callable[..., Any]) -> Callable[..., Any]:
        async def invoke(state: AgentState) -> dict[str, Any]:
            started = asyncio.get_running_loop().time()
            status = "failed"
            update: dict[str, Any] = {}
            error_codes: list[str] = []
            try:
                result = node(state)
                update = await result if inspect.isawaitable(result) else result
                status = "failed" if update.get("current_stage") == "failed" else "ok"
                returned_errors = update.get("errors", [])
                if isinstance(returned_errors, list):
                    error_codes = [
                        error.code if error.code in _SAFE_ERROR_CODES else "workflow_error"
                        for error in returned_errors
                        if isinstance(error, WorkflowError)
                    ]
                return update
            except asyncio.CancelledError:
                status = "cancelled"
                raise
            except Exception:
                error_codes = ["unhandled_stage_error"]
                raise
            finally:
                outcomes = update.get("source_outcomes", state.get("source_outcomes", []))
                source_counts: dict[str, int] = {}
                if isinstance(outcomes, list):
                    for outcome in outcomes:
                        value = getattr(outcome, "status", "unknown")
                        key = (
                            value
                            if value in {"ok", "empty", "partial", "blocked", "unavailable"}
                            else "unknown"
                        )
                        source_counts[key] = source_counts.get(key, 0) + 1
                logger.info(
                    "workflow_stage",
                    extra={
                        "stage": stage,
                        "status": status,
                        "elapsed_seconds": round(
                            max(0.0, asyncio.get_running_loop().time() - started), 6
                        ),
                        "revision": update.get("revision", state.get("revision", 0)),
                        "source_counts": source_counts,
                        "error_codes": error_codes,
                        "model_usage_snapshot": usage_snapshot(),
                    },
                )

        return invoke

    graph = StateGraph(AgentState)
    nodes = {
        "entry": entry,
        "extract": extract,
        "validate": validate,
        "generate_question": generate_question,
        "await_answers": await_answers,
        "apply": apply,
        "build_summary": build_summary,
        "await_confirmation": await_confirmation,
        "plan": plan,
        "retrieve": retrieve,
        "normalize": normalize,
        "understand": understand,
        "coverage": coverage,
        "recommend": recommend,
        "present": present,
        "failed": failed,
    }
    for name, node in nodes.items():
        graph.add_node(
            name,
            cast(
                Any,
                node
                if name in {"await_answers", "await_confirmation"}
                else timed(name, cast(Any, node)),
            ),
        )
    graph.add_edge(START, "entry")
    graph.add_conditional_edges("entry", cast(Any, entry_route), ["failed", "apply", "extract"])
    graph.add_conditional_edges(
        "extract",
        lambda state: (
            "failed"
            if state.get("current_stage") == "failed"
            else "apply"
            if state.get("command")
            else "validate"
        ),
        ["failed", "apply", "validate"],
    )
    graph.add_conditional_edges(
        "validate", cast(Any, validation_route), ["generate_question", "build_summary"]
    )
    graph.add_conditional_edges(
        "generate_question",
        lambda state: (
            "failed"
            if state.get("current_stage") == "failed"
            else "await_answers"
            if state.get("clarification_questions")
            else "build_summary"
        ),
        ["failed", "await_answers", "build_summary"],
    )
    graph.add_edge("await_answers", "apply")
    graph.add_conditional_edges(
        "apply", cast(Any, after_apply), ["failed", "plan", "validate", "build_summary"]
    )
    graph.add_edge("build_summary", "await_confirmation")
    graph.add_edge("await_confirmation", "apply")
    for name, successor in (
        ("plan", "retrieve"),
        ("retrieve", "normalize"),
        ("normalize", "understand"),
        ("understand", "coverage"),
    ):
        graph.add_conditional_edges(
            name,
            lambda state, next_node=successor: (
                "failed" if state.get("current_stage") == "failed" else next_node
            ),
            ["failed", successor],
        )
    graph.add_conditional_edges("coverage", cast(Any, coverage_route), ["plan", "recommend"])
    graph.add_edge("recommend", "present")
    graph.add_edge("present", END)
    graph.add_edge("failed", END)
    compiled = graph.compile(checkpointer=checkpointer)
    cast(Any, compiled).cleanup_session = cleanup_session
    return compiled
