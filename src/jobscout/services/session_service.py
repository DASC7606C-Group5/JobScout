"""Durable session snapshots with single-process operation ownership."""

import asyncio
import hashlib
import json
import logging
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import uuid4

from langgraph.types import Command
from pydantic import BaseModel, TypeAdapter
from tortoise import Tortoise
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from jobscout.config import Settings, get_settings
from jobscout.models import (
    AcceptedRequest,
    LoginSession,
    SearchSession,
    SessionOperation,
    WorkspaceDraft,
)
from jobscout.schemas.conversation import ConversationMessage, ConversationResponse, SearchSummary
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.execution import SearchProgress
from jobscout.schemas.feedback import (
    FollowUpAnswerRequest,
    JobFeedback,
    ResultPreferences,
    SessionFeedbackRequest,
    SessionFollowUpRequest,
)
from jobscout.schemas.job import JobPosting, SourceDocument
from jobscout.schemas.notices import ApplicantNotice
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import ClarificationMessage
from jobscout.schemas.session import (
    SessionCancelRequest,
    SessionCreateRequest,
    SessionResponse,
    SessionResumeRequest,
    SessionStopRequest,
)
from jobscout.schemas.workspace import SessionHistoryItem, SessionHistoryResponse
from jobscout.services.auth_service import auth_error
from jobscout.services.encryption import (
    ProfileDocumentCipher,
    decrypt_documents,
    encrypt_documents,
)
from jobscout.services.identity import current_user_id, owner_id
from jobscout.services.job_retrieval.models import SourceOutcome
from jobscout.services.model_settings_service import ModelSettingsService
from jobscout.services.notice_service import (
    dedupe_notices,
    finalize_recommendation,
    public_error,
    source_notices,
)
from jobscout.services.result_feedback_service import merge_results, refresh_hidden

logger = logging.getLogger(__name__)
_JSON_ADAPTER: TypeAdapter[Any] = TypeAdapter(Any)


class SessionOperationError(ValueError):
    def __init__(self, status: int, detail: str, *, code: str = "invalid_input") -> None:
        self.status = status
        self.detail = detail
        self.code = code
        super().__init__(detail)


@dataclass
class _Session:
    session_id: str
    state: dict[str, Any]
    owner_id: str = field(default_factory=owner_id)
    revision: int = 1
    outcome: str = "running"
    task: asyncio.Task[None] | None = None
    previous_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    operation_models: Any = None
    checkpoint_read_id: int = 0
    snapshot_version: int = 0
    accessed_at: float = field(default_factory=time.monotonic)
    published_response: SessionResponse | None = None
    deleted: bool = False
    thread_id: str = ""
    thread_ids: list[str] = field(default_factory=list)
    mode: str = "live"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    active_run_id: str | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _restore_state(
    state: dict[str, Any], cipher: ProfileDocumentCipher | None = None
) -> dict[str, Any]:
    """Reconstitute workflow models rather than passing JSON dictionaries to graph nodes."""
    models: dict[str, type[BaseModel]] = {
        "profile": UserProfile,
        "confirmed_profile": UserProfile,
        "recommendation": RecommendationResult,
        "search_summary": SearchSummary,
        "progress": SearchProgress,
        "result_preferences": ResultPreferences,
    }
    sequences: dict[str, type[BaseModel]] = {
        "clarification_questions": ClarificationMessage,
        "conversation": ConversationMessage,
        "errors": WorkflowError,
        "source_errors": WorkflowError,
        "notices": ApplicantNotice,
        "source_outcomes": SourceOutcome,
        "profile_documents": SourceDocument,
        "normalized_jobs": JobPosting,
        "job_feedback": JobFeedback,
    }
    restored = dict(state)
    restored.setdefault("operation_kind", "initial_search")
    restored.setdefault("job_feedback", [])
    restored.setdefault("result_preferences", {})
    restored.setdefault("result_order", [])
    restored.setdefault("exclusion_matches", {})
    for key, model in models.items():
        if restored.get(key) is not None:
            restored[key] = model.model_validate(restored[key])
    for key, model in sequences.items():
        if key in restored:
            restored[key] = [model.model_validate(item) for item in restored[key]]
    refresh_hidden(restored)
    if cipher is not None:
        documents = restored.get("profile_documents")
        if isinstance(documents, list) and documents:
            restored["profile_documents"] = decrypt_documents(cipher, documents)
        input_data = restored.get("input_data")
        if isinstance(input_data, dict):
            resume = input_data.get("resume")
            if isinstance(resume, dict) and isinstance(resume.get("text"), str):
                input_data = {
                    **input_data,
                    "resume": {**resume, "text": cipher.decrypt(resume["text"])},
                }
                restored["input_data"] = input_data
    return restored


class SessionService:
    def __init__(
        self,
        graph: Any,
        checkpointer: Any,
        *,
        mode: str = "live",
        model_settings: Any = None,
        graph_factory: Any = None,
        profile_cipher: ProfileDocumentCipher | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model_settings = model_settings
        self.graph_factory = graph_factory
        self.profile_cipher = profile_cipher or ProfileDocumentCipher(
            self.settings.credentials_key.get_secret_value()
        )
        self.testing_users: set[str] = set()
        self.graph = graph
        self.checkpointer = checkpointer
        self.mode = mode
        self.sessions: dict[str, _Session] = {}
        self.tasks: set[asyncio.Task[None]] = set()
        self.scheduler: asyncio.Task[None] | None = None
        self.wake = asyncio.Event()
        self.subscriber_owners: dict[asyncio.Queue[SessionResponse | None], str] = {}
        self.next_cleanup = 0.0
        self.lock = asyncio.Lock()
        self.closing = False
        self.subscribers: dict[str, set[asyncio.Queue[SessionResponse | None]]] = {}

    async def subscribe(self, session_id: str) -> asyncio.Queue[SessionResponse | None]:
        """Register and capture the current snapshot under the same lock as updates."""
        async with self.lock:
            record = await self._get(session_id)
            if self.closing:
                raise SessionOperationError(503, "Service is closing.", code="service_unavailable")
            if (
                sum(value == owner_id() for value in self.subscriber_owners.values())
                >= self.settings.event_streams_per_user
            ):
                raise auth_error(429, "event_stream_capacity")
            queue: asyncio.Queue[SessionResponse | None] = asyncio.Queue(maxsize=1)
            queue.put_nowait(self._response(record).model_copy(deep=True))
            self.subscribers.setdefault(session_id, set()).add(queue)
            self.subscriber_owners[queue] = owner_id()
            return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[SessionResponse | None]) -> None:
        self.subscriber_owners.pop(queue, None)
        listeners = self.subscribers.get(session_id)
        if listeners is not None:
            listeners.discard(queue)
            if not listeners:
                self.subscribers.pop(session_id, None)

    def _notify(self, record: _Session) -> None:
        if not record.deleted and not self.closing:
            record.published_response = self._response(record).model_copy(deep=True)
        listeners = self.subscribers.get(record.session_id)
        if not listeners:
            return
        snapshot = None if record.deleted or self.closing else record.published_response
        for queue in listeners:
            # Slow readers recover to the latest state without delaying the search.
            if queue.full() or snapshot is None:
                while not queue.empty():
                    queue.get_nowait()
            queue.put_nowait(snapshot)

    async def open(self) -> None:
        """Recover interrupted work without loading history or repeating model calls."""
        cursor = ""
        while True:
            rows = (
                await SearchSession.filter(
                    Q(outcome="running") | Q(deleting=True), session_id__gt=cursor
                )
                .order_by("session_id")
                .limit(self.settings.cleanup_batch_size)
            )
            if not rows:
                break
            for stored in rows:
                cursor = stored.session_id
                record = self._restore_record(stored)
                if record.deleted:
                    await self._finish_delete(record)
                    continue
                self._interrupt(record)
                async with in_transaction() as connection:
                    await self._persist(record, connection=connection)
                    operations = await SessionOperation.filter(
                        session_id=record.session_id, status="running"
                    ).using_db(connection)
                    for operation in operations:
                        await self._finish_operation(operation, "failed", connection)
        # A result may have committed just before provider cleanup was interrupted.
        # Replaced operations can also coexist with a newer queued session snapshot.
        while operations := await SessionOperation.filter(status="running").limit(
            self.settings.cleanup_batch_size
        ):
            async with in_transaction() as connection:
                for operation in operations:
                    await self._finish_operation(operation, "failed", connection)
        self._ensure_scheduler()

    def _ensure_scheduler(self) -> None:
        if self.scheduler is None and not self.closing:
            self.scheduler = asyncio.create_task(self._schedule())
        self.wake.set()

    @staticmethod
    def _retain_accepted_command(record: _Session) -> None:
        command = record.state.get("accepted_resume")
        if (
            command
            and command.get("action") != "retry"
            and record.state.get("applied_request_id") != command.get("request_id")
        ):
            record.state["failed_resume_payload"] = command

    @staticmethod
    def _interrupt(record: _Session) -> None:
        SessionService._retain_accepted_command(record)
        record.outcome = "failed"
        record.state["current_stage"] = "failed"
        record.state["retryable"] = True
        record.state["errors"] = [
            WorkflowError(
                code="search_interrupted",
                message="Processing was interrupted. Your input has been saved; retry when ready.",
                stage="workflow",
            )
        ]

    async def _persist(
        self, record: _Session, *, connection: BaseDBAsyncClient | None = None
    ) -> None:
        state = dict(record.state)
        documents = state.get("profile_documents")
        if isinstance(documents, list) and documents:
            state["profile_documents"] = encrypt_documents(self.profile_cipher, documents)
        input_data = state.get("input_data")
        if isinstance(input_data, dict):
            resume = input_data.get("resume")
            if isinstance(resume, dict) and isinstance(resume.get("text"), str):
                state["input_data"] = {
                    **input_data,
                    "resume": {**resume, "text": self.profile_cipher.encrypt(resume["text"])},
                }
        state = _JSON_ADAPTER.dump_python(state, mode="json")
        values = {
            "owner_id": record.owner_id,
            "state": state,
            "revision": record.revision,
            "snapshot_version": record.snapshot_version + 1,
            "outcome": record.outcome,
            "thread_id": record.thread_id,
            "thread_ids": record.thread_ids,
            "mode": record.mode,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "deleting": record.deleted,
        }
        # Start with a write: a deferred SQLite read-then-write transaction cannot be
        # upgraded after the separate checkpoint connection commits in WAL mode.
        updated = (
            await SearchSession.filter(session_id=record.session_id)
            .using_db(connection)
            .update(**values)
        )
        if not updated:
            await SearchSession.create(session_id=record.session_id, using_db=connection, **values)
        record.snapshot_version += 1

    async def create(self, payload: SessionCreateRequest) -> SessionResponse:
        data = payload.model_dump(mode="json")
        fingerprint = _fingerprint(data)
        async with self.lock:
            previous = await AcceptedRequest.get_or_none(
                owner_id=owner_id(), scope="create", request_id=payload.request_id
            )
            if previous:
                if previous.fingerprint != fingerprint:
                    raise SessionOperationError(
                        409, "Request ID has different content.", code="request_conflict"
                    )
                record = await self._get(str(previous.session_id))
                return self._response(record)
            if not payload.description.strip() and not (
                payload.resume and payload.resume.text.strip()
            ):
                raise SessionOperationError(422, "Provide a resume or personal introduction.")
            if payload.resume and payload.resume.text.strip() and not payload.resume_consent:
                raise SessionOperationError(
                    422,
                    "Confirm that you consent to sending your resume to the configured AI model.",
                    code="resume_consent_required",
                )
            session_id = str(uuid4())
            state: dict[str, Any] = {
                "session_id": session_id,
                "input_data": data,
                "revision": 1,
                "current_stage": "ingest",
            }
            now = datetime.now(UTC)
            record = _Session(
                session_id,
                state,
                thread_id=session_id,
                thread_ids=[session_id],
                mode=self.mode,
                created_at=now,
                updated_at=now,
            )
            async with in_transaction() as connection:
                await self._write_lock(connection)
                await self._enqueue(record, state, "create", payload.request_id, connection)
                await self._persist(record, connection=connection)
                await AcceptedRequest.create(
                    owner_id=owner_id(),
                    scope="create",
                    request_id=payload.request_id,
                    fingerprint=fingerprint,
                    session_id=session_id,
                    using_db=connection,
                )
            self.sessions[session_id] = record
            await self._dispatch_locked()
            self._ensure_scheduler()
            response = self._response(record)
            self._trim_cache()
            return response

    async def resume(self, session_id: str, payload: SessionResumeRequest) -> SessionResponse:
        data = payload.model_dump(mode="json")
        fingerprint = _fingerprint(data)
        async with self.lock:
            record = await self._get(session_id)
            previous = await AcceptedRequest.get_or_none(
                owner_id=owner_id(), scope=f"resume:{session_id}", request_id=payload.request_id
            )
            if previous:
                if previous.fingerprint != fingerprint:
                    raise SessionOperationError(
                        409,
                        "This request ID has already been used for different content.",
                        code="request_conflict",
                    )
                return self._response(record)
            if record.revision != payload.expected_revision:
                raise SessionOperationError(
                    409,
                    "The session has been updated. Refresh and try again.",
                    code="search_changed",
                )
            editing_run = (
                payload.action == "edit_conditions"
                and record.outcome == "running"
                and record.state.get("run_id") is not None
                and record.state.get("profile") is not None
            )
            previous_task = record.task if editing_run else None
            if record.outcome == "queued" or (
                record.task is not None and not record.task.done() and not editing_run
            ):
                raise SessionOperationError(
                    409,
                    "An operation is already in progress for this session.",
                    code="operation_in_progress",
                )
            if record.outcome == "completed" and payload.action != "edit_conditions":
                raise SessionOperationError(
                    409,
                    "Update your criteria before confirming a new search.",
                    code="search_completed",
                )
            if record.outcome in {"failed", "cancelled"} and payload.action not in {
                "retry",
                "edit_conditions",
            }:
                raise SessionOperationError(
                    409, "Try again or update your criteria.", code="search_not_retryable"
                )
            if payload.action == "retry" and record.outcome not in {"failed", "cancelled"}:
                raise SessionOperationError(
                    409, "This session does not need to be retried.", code="search_not_retryable"
                )
            if payload.action == "retry" and not record.state.get("retryable", True):
                raise SessionOperationError(
                    409, "This search cannot be retried.", code="search_not_retryable"
                )
            if payload.action == "retry" and record.state.get("operation_kind") == "follow_up":
                return await self._accept_follow_up(record, data, fingerprint, retry=True)
            if record.state.get("current_stage") == "follow_up_clarify":
                raise SessionOperationError(
                    409, "Answer the pending result questions.", code="follow_up_answer_required"
                )
            self._validate_answers(record, payload)
            previous_state = dict(record.state)
            previous_outcome = record.outcome
            previous_thread = record.thread_id
            previous_threads = list(record.thread_ids)
            previous_updated_at = record.updated_at
            previous_snapshot_version = record.snapshot_version
            record.revision += 1
            record.state["revision"] = record.revision
            if payload.action == "edit_conditions":
                record.state.update(
                    recommendation=None,
                    operation_kind="initial_search",
                    exclusion_matches={},
                    accepted_follow_up=None,
                    pending_follow_up=None,
                    search_summary=None,
                    run_id=None,
                    progress=SearchProgress(),
                    progress_seq=0,
                    stop_reason=None,
                    source_outcomes=[],
                )
            if record.outcome in {"completed", "failed", "cancelled"} or editing_run:
                record.thread_id = f"{session_id}:{record.revision}"
                record.thread_ids.append(record.thread_id)
                next_input: Any = {
                    **record.state,
                    "command": data,
                    "errors": [],
                    "current_stage": payload.action,
                }
            else:
                next_input = Command(resume=data)
            record.outcome = "running"
            record.state["current_stage"] = (
                "search" if payload.action == "confirm_search" else "validate"
            )
            record.state["errors"] = []
            record.state["notices"] = []
            record.state["accepted_resume"] = data
            record.updated_at = datetime.now(UTC)
            try:
                async with in_transaction() as connection:
                    await self._write_lock(connection)
                    await self._enqueue(
                        record,
                        next_input,
                        payload.action,
                        payload.request_id,
                        connection,
                        replacing=editing_run,
                    )
                    await self._persist(record, connection=connection)
                    await AcceptedRequest.create(
                        owner_id=owner_id(),
                        scope=f"resume:{session_id}",
                        request_id=payload.request_id,
                        fingerprint=fingerprint,
                        session_id=session_id,
                        using_db=connection,
                    )
                    await WorkspaceDraft.filter(session_id=session_id).using_db(connection).delete()
            except BaseException:
                record.revision -= 1
                record.state = previous_state
                record.outcome = previous_outcome
                record.thread_id = previous_thread
                record.thread_ids = previous_threads
                record.updated_at = previous_updated_at
                record.snapshot_version = previous_snapshot_version
                raise
            record.active_run_id = None
            if previous_task is not None and not previous_task.cancelling():
                previous_task.cancel()
            await self._dispatch_locked()
            self._ensure_scheduler()
            self._notify(record)
            response = self._response(record)
            self._trim_cache()
            return response

    @staticmethod
    async def _result_request(
        record: _Session, data: dict[str, Any], operation: str
    ) -> tuple[str, bool]:
        fingerprint = _fingerprint({"operation": operation, "payload": data})
        previous = (
            await AcceptedRequest.filter(
                owner_id=record.owner_id,
                session_id=record.session_id,
                request_id=data["request_id"],
            )
            .exclude(scope="create")
            .first()
        )
        if previous is not None:
            if previous.fingerprint != fingerprint:
                raise SessionOperationError(
                    409, "Request ID already used.", code="request_conflict"
                )
            return fingerprint, True
        if record.revision != data["expected_revision"]:
            raise SessionOperationError(409, "Search has changed.", code="search_changed")
        if record.outcome in {"queued", "running"}:
            raise SessionOperationError(409, "Operation is running.", code="operation_in_progress")
        return fingerprint, False

    @staticmethod
    def _require_result(record: _Session, job_id: str | None = None) -> None:
        if record.state.get("current_stage") == "follow_up_clarify":
            raise SessionOperationError(
                409, "Answer the pending questions.", code="follow_up_answer_required"
            )
        if record.outcome != "completed" or record.state.get("recommendation") is None:
            raise SessionOperationError(
                409, "Complete or retry the search first.", code="follow_up_unavailable"
            )
        if job_id is not None:
            result = record.state["recommendation"]
            if not any(item.job.job_id == job_id for item in [*result.jobs, *result.pending_jobs]):
                raise SessionOperationError(
                    404, "Job is not in this search.", code="job_not_in_session"
                )

    async def feedback(self, session_id: str, payload: SessionFeedbackRequest) -> SessionResponse:
        data = payload.model_dump(mode="json")
        async with self.lock:
            record = await self._get(session_id)
            fingerprint, repeated = await self._result_request(record, data, "feedback")
            if repeated:
                return self._response(record)
            self._require_result(record, payload.job_id)
            previous_state, previous_updated = record.state, record.updated_at
            previous_version = record.snapshot_version
            record.state = dict(record.state)
            feedback = [
                item
                for item in record.state.get("job_feedback", [])
                if item.job_id != payload.job_id
            ]
            if payload.reaction is not None:
                previous_feedback = next(
                    (
                        item
                        for item in record.state.get("job_feedback", [])
                        if item.job_id == payload.job_id and item.reaction == payload.reaction
                    ),
                    None,
                )
                feedback.append(
                    JobFeedback(
                        job_id=payload.job_id,
                        reaction=payload.reaction,
                        reason=previous_feedback.reason if previous_feedback else None,
                        updated_at=datetime.now(UTC),
                    )
                )
            record.revision += 1
            record.state.update(job_feedback=feedback, revision=record.revision)
            refresh_hidden(record.state)
            record.updated_at = datetime.now(UTC)
            try:
                async with in_transaction() as connection:
                    await self._persist(record, connection=connection)
                    await AcceptedRequest.create(
                        owner_id=record.owner_id,
                        scope=f"resume:{session_id}",
                        request_id=payload.request_id,
                        fingerprint=fingerprint,
                        session_id=session_id,
                        using_db=connection,
                    )
            except BaseException:
                record.revision -= 1
                record.state, record.updated_at = previous_state, previous_updated
                record.snapshot_version = previous_version
                raise
            self._notify(record)
            return self._response(record)

    async def follow_up(self, session_id: str, payload: SessionFollowUpRequest) -> SessionResponse:
        data = payload.model_dump(mode="json")
        async with self.lock:
            record = await self._get(session_id)
            fingerprint, repeated = await self._result_request(record, data, "follow_up")
            if repeated:
                return self._response(record)
            if isinstance(payload, FollowUpAnswerRequest):
                pending = {
                    q.question_id: q
                    for q in record.state.get("clarification_questions", [])
                    if q.status == "pending"
                }
                submitted = [
                    *(answer.question_id for answer in payload.answers),
                    *payload.skipped_question_ids,
                ]
                if (
                    record.outcome != "paused"
                    or record.state.get("current_stage") != "follow_up_clarify"
                ):
                    raise SessionOperationError(
                        409, "No result question is waiting.", code="follow_up_unavailable"
                    )
                if (
                    not submitted
                    or len(submitted) != len(set(submitted))
                    or set(submitted) != set(pending)
                ):
                    raise SessionOperationError(
                        422,
                        "Answer or skip each current question once.",
                        code="invalid_follow_up_input",
                    )
                for answer in payload.answers:
                    question = pending[answer.question_id]
                    values = answer.value if isinstance(answer.value, list) else [answer.value]
                    options = {option.id for option in question.options}
                    if (
                        not values
                        or any(not value.strip() for value in values)
                        or len(values) != len(set(values))
                        or (question.control_type == "multiple_choice")
                        != isinstance(answer.value, list)
                        or (question.control_type != "text" and not set(values) <= options)
                    ):
                        raise SessionOperationError(
                            422, "Invalid result answer.", code="invalid_follow_up_input"
                        )
            else:
                self._require_result(record, payload.job_id)
                if payload.action == "message" and not payload.message.strip():
                    raise SessionOperationError(
                        422, "Enter a message.", code="invalid_follow_up_input"
                    )
            return await self._accept_follow_up(record, data, fingerprint)

    async def _accept_follow_up(
        self, record: _Session, data: dict[str, Any], fingerprint: str, *, retry: bool = False
    ) -> SessionResponse:
        previous_state, previous_outcome = record.state, record.outcome
        previous_thread, previous_threads = record.thread_id, list(record.thread_ids)
        previous_updated = record.updated_at
        previous_version = record.snapshot_version
        record.state = dict(record.state)
        record.revision += 1
        original = record.state.get("accepted_follow_up") if retry else data
        if not original:
            record.revision -= 1
            record.state = previous_state
            raise SessionOperationError(
                409, "No accepted result request.", code="follow_up_unavailable"
            )
        answering = original.get("action") == "answer"
        if not retry:
            if not answering:
                result = record.state.get("recommendation")
                record.state["follow_up_baseline_job_ids"] = (
                    [item.job.job_id for item in [*result.jobs, *result.pending_jobs]]
                    if result
                    else []
                )
            record.state["accepted_follow_up"] = data
            record.state["follow_up_search_ready"] = False
            record.state["feedback_reason_updates"] = {}
            record.state["conversation"] = [
                *record.state.get("conversation", []),
                ConversationMessage(
                    message_id=f"message:{data['request_id']}",
                    role="user",
                    text=data.get(
                        "message",
                        "Find more similar jobs."
                        if data["action"] == "find_similar"
                        else "Answers submitted.",
                    ),
                    job_id=data.get("job_id"),
                    responses=[
                        ConversationResponse(
                            label=next(
                                q.question
                                for q in record.state.get("clarification_questions", [])
                                if q.question_id == answer["question_id"]
                            ),
                            value=answer["value"],
                        )
                        for answer in data.get("answers", [])
                    ]
                    + [
                        ConversationResponse(
                            label=next(
                                q.question
                                for q in record.state.get("clarification_questions", [])
                                if q.question_id == question_id
                            ),
                            value="Skipped",
                            status="skipped",
                        )
                        for question_id in data.get("skipped_question_ids", [])
                    ],
                ),
            ]
        record.outcome = "running"
        record.state.update(
            revision=record.revision,
            operation_kind="follow_up",
            current_stage="follow_up_interpret",
            errors=[],
            retryable=False,
        )
        record.updated_at = datetime.now(UTC)
        resume_wait = answering and not retry
        if not resume_wait:
            record.thread_id = f"{record.session_id}:{record.revision}"
            record.thread_ids.append(record.thread_id)
        graph_input: Any = (
            Command(
                resume={
                    "kind": "follow_up",
                    "payload": original,
                    "revision": record.revision,
                    "conversation": record.state.get("conversation", []),
                }
            )
            if resume_wait
            else {**record.state, "command": {"kind": "follow_up", "payload": original}}
        )
        try:
            async with in_transaction() as connection:
                await self._write_lock(connection)
                await self._enqueue(
                    record, graph_input, "follow_up", data["request_id"], connection
                )
                await self._persist(record, connection=connection)
                await AcceptedRequest.create(
                    owner_id=record.owner_id,
                    scope=f"resume:{record.session_id}",
                    request_id=data["request_id"],
                    fingerprint=fingerprint,
                    session_id=record.session_id,
                    using_db=connection,
                )
        except BaseException:
            record.revision -= 1
            record.state, record.outcome = previous_state, previous_outcome
            record.thread_id, record.thread_ids = previous_thread, previous_threads
            record.updated_at = previous_updated
            record.snapshot_version = previous_version
            raise
        await self._dispatch_locked()
        self._ensure_scheduler()
        self._notify(record)
        response = self._response(record)
        self._trim_cache()
        return response

    @staticmethod
    def _validate_answers(record: _Session, payload: SessionResumeRequest) -> None:
        questions = record.state.get("clarification_questions", [])
        pending = {q.question_id: q for q in questions if q.status == "pending"}
        answered_ids = [answer.question_id for answer in payload.answers]
        submitted = [*answered_ids, *payload.skipped_question_ids]
        if len(submitted) != len(set(submitted)):
            raise SessionOperationError(
                422, "A question cannot be answered more than once or both answered and skipped."
            )
        for question_id in submitted:
            if question_id not in pending:
                raise SessionOperationError(
                    422, "This question is no longer valid or does not exist."
                )
        for question_id in payload.skipped_question_ids:
            question = pending[question_id]
            if question.required:
                raise SessionOperationError(422, "Required questions cannot be skipped.")
        for answer in payload.answers:
            question = pending[answer.question_id]
            control = question.control_type
            if control == "multiple_choice":
                if not isinstance(answer.value, list):
                    raise SessionOperationError(
                        422, "Answers to multiple-choice questions must be a list of options."
                    )
                selected = answer.value
            else:
                if not isinstance(answer.value, str):
                    raise SessionOperationError(
                        422, "This question requires a text or single-choice answer."
                    )
                selected = [answer.value]
            if len(selected) != len(set(selected)):
                raise SessionOperationError(
                    422, "The same option cannot be submitted more than once."
                )
            options = {option.id for option in question.options}
            if control != "text" and any(value not in options for value in selected):
                raise SessionOperationError(422, "The answer contains an invalid option.")
        if payload.action == "confirm_search" and record.outcome == "paused":
            summary = record.state.get("search_summary")
            if summary is None or not summary.ready or summary.revision != record.revision:
                raise SessionOperationError(
                    409,
                    "Review and complete the current search summary first.",
                    code="search_changed",
                )

    async def get(self, session_id: str) -> SessionResponse:
        record = await self._get(session_id)
        if record.published_response is None:
            record.published_response = self._response(record).model_copy(deep=True)
        try:
            async with asyncio.timeout(1):
                return await self._read_current(session_id)
        except TimeoutError:
            # The graph writer and workspace persistence may both be busy. Return only
            # the last published snapshot, including the normal owner/deletion checks.
            record = await self._get(session_id)
            assert record.published_response is not None
            return record.published_response.model_copy(deep=True)

    async def _read_current(self, session_id: str) -> SessionResponse:
        async with self.lock:
            record = await self._get(session_id)
            if record.outcome != "running":
                record.published_response = self._response(record).model_copy(deep=True)
                return record.published_response.model_copy(deep=True)
            thread_id, revision = record.thread_id, record.revision
            record.checkpoint_read_id += 1
            read_id = record.checkpoint_read_id
        # Checkpoint reads can wait on the graph writer; other sessions must remain usable.
        snapshot = await self.graph.aget_state(self._config(thread_id))
        async with self.lock:
            record = await self._get(session_id)
            if (
                record.outcome == "running"
                and record.thread_id == thread_id
                and record.revision == revision
                and record.checkpoint_read_id == read_id
                and snapshot.values
                and snapshot.values.get("revision", 0) >= revision
            ):
                previous_state = dict(record.state)
                self._merge_snapshot(record, snapshot.values)
                try:
                    if record.state != previous_state:
                        await self._persist(record)
                        record.published_response = self._response(record).model_copy(deep=True)
                except BaseException:
                    record.state = previous_state
                    raise
            return self._response(record)

    async def stop(self, session_id: str, payload: SessionStopRequest) -> SessionResponse:
        """Stop further retrieval while the current run finishes reviewing its vacancies."""
        fingerprint = _fingerprint(payload.model_dump(mode="json"))
        async with self.lock:
            record = await self._get(session_id)
            previous = await AcceptedRequest.get_or_none(
                owner_id=owner_id(), scope=f"stop:{session_id}", request_id=payload.request_id
            )
            if previous:
                if previous.fingerprint != fingerprint:
                    raise SessionOperationError(
                        409,
                        "The request ID was used for different content.",
                        code="request_conflict",
                    )
                return self._response(record)
            if record.state.get("run_id") != payload.run_id:
                raise SessionOperationError(
                    409, "The search run has changed.", code="search_changed"
                )
            if record.outcome in {"completed", "failed"}:
                return self._response(record)
            if record.revision != payload.expected_revision:
                raise SessionOperationError(409, "The search has changed.", code="search_changed")
            if record.outcome != "running" or record.active_run_id != payload.run_id:
                raise SessionOperationError(
                    409, "This search is not running.", code="search_changed"
                )

            previous_state = dict(record.state)
            previous_updated_at = record.updated_at
            progress = SearchProgress.model_validate(record.state.get("progress", {}))
            record.state.update(
                progress=progress.model_copy(update={"retrieval_stopped": True}),
                stop_reason="user_stopped",
                current_stage="review",
            )
            record.updated_at = datetime.now(UTC)
            try:
                async with in_transaction() as connection:
                    await self._persist(record, connection=connection)
                    await AcceptedRequest.create(
                        owner_id=owner_id(),
                        scope=f"stop:{session_id}",
                        request_id=payload.request_id,
                        fingerprint=fingerprint,
                        session_id=session_id,
                        using_db=connection,
                    )
            except BaseException:
                record.state = previous_state
                record.outcome = "running"
                record.updated_at = previous_updated_at
                raise
            record.stop_event.set()
            self._notify(record)
            response = self._response(record)
        return response

    @staticmethod
    def _merge_snapshot(record: _Session, values: dict[str, Any]) -> None:
        """A graph checkpoint may lag finer-grained, durably saved tool progress."""
        incoming = dict(values)
        incoming.pop("job_feedback", None)
        for key in ("hidden_job_ids", "hidden_job_reasons"):
            incoming.pop(key, None)
        if record.state.get("progress_seq", 0) > incoming.get("progress_seq", 0) or (
            record.state.get("run_id") is not None
            and record.state.get("run_id") != incoming.get("run_id")
        ):
            for key in (
                "recommendation",
                "progress",
                "progress_seq",
                "run_id",
                "stop_reason",
                "source_outcomes",
                "exclusion_matches",
            ):
                incoming.pop(key, None)
            if incoming.get("current_stage") not in {"completed", "failed"}:
                incoming.pop("current_stage", None)
        if record.stop_event.is_set():
            incoming.pop("stop_reason", None)
            if "progress" in incoming:
                incoming["progress"] = SearchProgress.model_validate(
                    incoming["progress"]
                ).model_copy(update={"retrieval_stopped": True})
            if incoming.get("current_stage") not in {"completed", "failed", "review"}:
                incoming.pop("current_stage", None)
        if (
            incoming.get("recommendation") is not None
            and record.state.get("operation_kind") == "follow_up"
        ):
            incoming["recommendation"], incoming["result_order"] = merge_results(
                record.state.get("recommendation"),
                RecommendationResult.model_validate(incoming["recommendation"]),
                record.state.get("result_order", []),
                baseline_job_ids=record.state.get("follow_up_baseline_job_ids"),
            )
        elif (
            record.state.get("recommendation") is not None
            and record.state.get("operation_kind") == "follow_up"
        ):
            incoming.pop("recommendation", None)
        if record.state.get("operation_kind") == "follow_up" and "source_outcomes" in incoming:
            self_outcomes = {
                _fingerprint(item.model_dump(mode="json")): item
                for item in [*record.state.get("source_outcomes", []), *incoming["source_outcomes"]]
            }
            incoming["source_outcomes"] = list(self_outcomes.values())
        reason_updates = incoming.pop("feedback_reason_updates", {})
        if reason_updates:
            record.state["job_feedback"] = [
                item.model_copy(
                    update={"reason": reason_updates[item.job_id], "updated_at": datetime.now(UTC)}
                )
                if item.job_id in reason_updates and item.reason != reason_updates[item.job_id]
                else item
                for item in record.state.get("job_feedback", [])
            ]
        record.state.update(incoming)
        refresh_hidden(record.state)

    async def _progress(
        self, record: _Session, run_id: str, revision: int, update: dict[str, Any]
    ) -> None:
        async with self.lock:
            if (
                record.deleted
                or self.closing
                or record.outcome != "running"
                or self.sessions.get(record.session_id) is not record
                or record.active_run_id != run_id
                or record.revision != revision
                or update.get("run_id") != run_id
            ):
                return
            progress = SearchProgress.model_validate(update.get("progress", {})).model_copy(
                deep=True
            )
            if record.stop_event.is_set():
                progress = progress.model_copy(update={"retrieval_stopped": True})
            sequence = update.get("progress_seq", progress.sequence)
            if sequence <= record.state.get("progress_seq", 0):
                return
            previous = dict(record.state)
            record.state.update(run_id=run_id, progress=progress, progress_seq=sequence)
            if update.get("recommendation") is not None:
                result = RecommendationResult.model_validate(update["recommendation"]).model_copy(
                    deep=True
                )
                if record.state.get("operation_kind") == "follow_up":
                    record.state["recommendation"], record.state["result_order"] = merge_results(
                        record.state.get("recommendation"),
                        result,
                        record.state.get("result_order", []),
                        baseline_job_ids=record.state.get("follow_up_baseline_job_ids"),
                    )
                else:
                    record.state["recommendation"] = result
                recommendation = finalize_recommendation(record.state["recommendation"])
                published = (
                    dict(record.state.get("published_jobs", {}))
                    if record.state.get("published_run_id") == run_id
                    else {}
                )
                published.update(
                    {
                        item.job.job_id: item.model_dump(mode="json")
                        for item in [*recommendation.jobs, *recommendation.pending_jobs]
                    }
                )
                record.state.update(published_jobs=published, published_run_id=run_id)
            if "exclusion_matches" in update:
                record.state["exclusion_matches"] = update["exclusion_matches"]
            for key in ("profile", "result_preferences", "follow_up_search_ready"):
                if key in update:
                    record.state[key] = update[key]
            reason_updates = update.get("feedback_reason_updates", {})
            if reason_updates:
                record.state["job_feedback"] = [
                    item.model_copy(
                        update={
                            "reason": reason_updates[item.job_id],
                            "updated_at": datetime.now(UTC),
                        }
                    )
                    if item.job_id in reason_updates and item.reason != reason_updates[item.job_id]
                    else item
                    for item in record.state.get("job_feedback", [])
                ]
            refresh_hidden(record.state)
            if "source_outcomes" in update:
                outcomes = [
                    SourceOutcome.model_validate(value).model_copy(deep=True)
                    for value in update["source_outcomes"]
                ]
                if record.state.get("operation_kind") == "follow_up":
                    combined = {
                        _fingerprint(item.model_dump(mode="json")): item
                        for item in [*record.state.get("source_outcomes", []), *outcomes]
                    }
                    outcomes = list(combined.values())
                record.state["source_outcomes"] = outcomes
            for key in ("stop_reason", "current_stage"):
                if key in update:
                    if key == "stop_reason" and record.stop_event.is_set() and update[key] is None:
                        continue
                    record.state[key] = update[key]
            try:
                await self._persist(record)
            except BaseException:
                record.state = previous
                raise
            self._notify(record)

    async def history(
        self, *, cursor: str | None = None, limit: int = 20
    ) -> SessionHistoryResponse:
        query = SearchSession.filter(deleting=False, owner_id=owner_id())
        if cursor:
            try:
                timestamp, session_id = json.loads(urlsafe_b64decode(cursor.encode("ascii")))
                boundary = datetime.fromisoformat(timestamp)
                if boundary.tzinfo is None or not isinstance(session_id, str):
                    raise ValueError("Invalid cursor")
            except (ValueError, TypeError, UnicodeError) as error:
                raise SessionOperationError(422, "The history cursor is invalid.") from error
            query = query.filter(
                Q(updated_at__lt=boundary) | Q(updated_at=boundary, session_id__lt=session_id)
            )
        records = await query.order_by("-updated_at", "-session_id").limit(limit + 1)
        items = []
        for stored in records[:limit]:
            state = stored.state
            profile = state.get("profile") or state.get("input_data", {})
            preferences = profile.get("preferences", {})
            directions = profile.get("target_directions", [])
            items.append(
                SessionHistoryItem(
                    session_id=stored.session_id,
                    title=", ".join(directions) or "Job search",
                    location="Any location"
                    if preferences.get("location_unrestricted")
                    else preferences.get("location") or "Location undecided",
                    outcome=cast(
                        Literal["queued", "running", "paused", "completed", "failed", "cancelled"],
                        stored.outcome,
                    ),
                    current_stage=state.get("current_stage", "ingest"),
                    revision=stored.revision,
                    created_at=stored.created_at,
                    updated_at=stored.updated_at,
                    retryable=stored.outcome in {"failed", "cancelled"}
                    and bool(state.get("retryable", True)),
                    mode=cast(Literal["live", "replay"], stored.mode),
                )
            )
        next_cursor = None
        if len(records) > limit:
            last = records[limit - 1]
            next_cursor = urlsafe_b64encode(
                json.dumps([last.updated_at.isoformat(), last.session_id]).encode("utf-8")
            ).decode("ascii")
        return SessionHistoryResponse(items=items, next_cursor=next_cursor)

    async def delete(self, session_id: str) -> None:
        async with self.lock:
            try:
                record = await self._get(session_id, include_deleted=True)
            except SessionOperationError:
                if await AcceptedRequest.filter(
                    owner_id=owner_id(), scope="create", session_id=session_id
                ).exists():
                    return
                raise SessionOperationError(
                    404, "This search was not found.", code="search_not_found"
                ) from None
            if record.owner_id != owner_id():
                raise SessionOperationError(
                    404, "This search was not found.", code="search_not_found"
                )
            previous_deleted = record.deleted
            previous_state = record.state
            record.deleted = True
            record.state = {}
            try:
                async with in_transaction() as connection:
                    await self._persist(record, connection=connection)
                    for operation in await SessionOperation.filter(
                        session_id=session_id, status="queued"
                    ).using_db(connection):
                        await self._finish_operation(operation, "cancelled", connection)
                    await WorkspaceDraft.filter(session_id=session_id).using_db(connection).delete()
            except BaseException:
                record.deleted = previous_deleted
                record.state = previous_state
                raise
            self._notify(record)
            tasks = [*record.previous_tasks, *([record.task] if record.task is not None else [])]
            for task in tasks:
                if not task.cancelling():
                    task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._close_models(record.operation_models)
        record.operation_models = None
        await self._finish_delete(record)
        async with self.lock:
            await self._notify_positions()

    async def _finish_delete(self, record: _Session) -> None:
        for thread_id in record.thread_ids:
            await self.checkpointer.adelete_thread(thread_id)
        await self._cleanup_session(record.session_id)
        async with in_transaction() as connection:
            await self._write_lock(connection)
            for operation in await SessionOperation.filter(
                session_id=record.session_id, status="queued"
            ).using_db(connection):
                await self._finish_operation(operation, "cancelled", connection)
            await (
                SessionOperation.filter(session_id=record.session_id).using_db(connection).delete()
            )
            await SearchSession.filter(session_id=record.session_id).using_db(connection).delete()
        self.wake.set()
        self.sessions.pop(record.session_id, None)

    async def _cleanup_session(self, session_id: str) -> None:
        await self.graph.cleanup_session(session_id)

    async def close(self) -> None:
        self.closing = True
        if self.scheduler is not None:
            self.scheduler.cancel()
            await asyncio.gather(self.scheduler, return_exceptions=True)
            self.scheduler = None
        async with self.lock:
            self.closing = True
            records = list(self.sessions.values())
            tasks = []
            for record in records:
                self._notify(record)
                record_tasks = [
                    *record.previous_tasks,
                    *([record.task] if record.task is not None else []),
                ]
                for task in record_tasks:
                    if not task.cancelling():
                        task.cancel()
                tasks.extend(record_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for record in records:
            # A task cancelled before its first turn never executes its finally block.
            await self._close_models(record.operation_models)
            record.operation_models = None
        failures: list[Exception] = []
        for record in records:
            if record.deleted:
                continue
            try:
                if record.outcome == "running":
                    snapshot = await self.graph.aget_state(self._config(record.thread_id))
                    if snapshot.values and snapshot.values.get("revision", 0) >= record.revision:
                        self._merge_snapshot(record, snapshot.values)
                    await self._persist(record)
            except Exception as error:
                failures.append(error)
            try:
                await self._cleanup_session(record.session_id)
            except Exception as error:
                failures.append(error)
        self.sessions.clear()
        self.subscribers.clear()
        self.subscriber_owners.clear()
        if failures:
            raise ExceptionGroup("Session shutdown failed", failures)

    def _restore_record(self, stored: SearchSession) -> _Session:
        return _Session(
            session_id=stored.session_id,
            state=_restore_state(stored.state, self.profile_cipher),
            owner_id=stored.owner_id,
            revision=stored.revision,
            snapshot_version=stored.snapshot_version,
            outcome=stored.outcome,
            thread_id=stored.thread_id,
            thread_ids=stored.thread_ids,
            deleted=stored.deleting,
            mode=stored.mode,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
        )

    async def _get(self, session_id: str, *, include_deleted: bool = False) -> _Session:
        record = self.sessions.get(session_id)
        if record is None:
            query = SearchSession.filter(session_id=session_id, owner_id=owner_id())
            if not include_deleted:
                query = query.filter(deleting=False)
            stored = await query.first()
            if stored is not None:
                record = self._restore_record(stored)
                self.sessions[session_id] = record
        if (
            record is None
            or (record.deleted and not include_deleted)
            or record.owner_id != owner_id()
        ):
            raise SessionOperationError(
                404, "This session does not exist or has expired.", code="search_not_found"
            )
        record.accessed_at = time.monotonic()
        if record.outcome == "queued":
            operation = await SessionOperation.filter(
                session_id=session_id, status="queued"
            ).first()
            if operation:
                record.state["queue_position"] = await SessionOperation.filter(
                    status="queued", id__lte=operation.id
                ).count()
        self._trim_cache()
        return record

    def _trim_cache(self) -> None:
        now = time.monotonic()
        idle = sorted(
            (
                record
                for record in self.sessions.values()
                if not (record.task and not record.task.done()) and not record.previous_tasks
            ),
            key=lambda record: record.accessed_at,
            reverse=True,
        )
        size = 0
        count = 0
        for record in idle:
            weight = len(_JSON_ADAPTER.dump_json(record.state))
            if record.published_response is not None:
                weight += len(record.published_response.model_dump_json().encode())
            if (
                record.outcome == "queued"
                or now - record.accessed_at >= self.settings.session_cache_seconds
                or count >= self.settings.session_cache_entries
                or size + weight > self.settings.session_cache_bytes
            ):
                self.sessions.pop(record.session_id, None)
            else:
                size += weight
                count += 1

    @staticmethod
    def _config(session_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": session_id}, "recursion_limit": 100}

    async def check_capacity(self) -> None:
        if self.closing:
            raise SessionOperationError(503, "Service is closing.", code="service_unavailable")
        if (
            await SessionOperation.filter(status="queued").exists()
            or len(self.tasks) + len(self.testing_users) >= self.settings.concurrent_total_limit
            or owner_id() in self.testing_users
            or await SessionOperation.filter(
                owner_id=owner_id(), status__in=["queued", "running"]
            ).exists()
        ):
            raise auth_error(429, "operation_capacity")

    @staticmethod
    async def _write_lock(connection: BaseDBAsyncClient) -> None:
        # Acquire SQLite's writer before reading counters shared with the checkpoint connection.
        await connection.execute_query(
            "UPDATE workspace_sessions SET revision=revision WHERE session_id='__queue_lock__'"
        )

    async def _enqueue(
        self,
        record: _Session,
        graph_input: Any,
        kind: str,
        request_id: str,
        connection: BaseDBAsyncClient,
        *,
        replacing: bool = False,
    ) -> None:
        if self.closing:
            raise SessionOperationError(503, "Service is closing.", code="service_unavailable")
        active = SessionOperation.filter(owner_id=record.owner_id, status__in=["queued", "running"])
        if replacing:
            active = active.exclude(session_id=record.session_id, status="running")
        if (
            record.owner_id in self.testing_users
            or await active.using_db(connection).count() >= self.settings.concurrent_user_limit
        ):
            raise auth_error(429, "operation_capacity")
        if (
            await SessionOperation.filter(status="queued").using_db(connection).count()
            >= self.settings.queue_limit
        ):
            from fastapi import HTTPException

            raise HTTPException(429, {"code": "queue_full"}, headers={"Retry-After": "10"})
        values, uses_server = (
            await self.model_settings.snapshot(record.owner_id)
            if self.model_settings
            else ({}, False)
        )
        day = (
            await self.model_settings.reserve(record.owner_id, connection) if uses_server else None
        )
        now = datetime.now(UTC)
        operation = await SessionOperation.create(
            operation_id=str(uuid4()),
            owner_id=record.owner_id,
            session_id=record.session_id,
            request_id=request_id,
            revision=record.revision,
            kind=kind,
            encrypted_input=self.profile_cipher.encrypt(
                _JSON_ADAPTER.dump_json(
                    {
                        "resume": isinstance(graph_input, Command),
                        "value": graph_input.resume
                        if isinstance(graph_input, Command)
                        else graph_input,
                    }
                ).decode()
            ),
            encrypted_models=self.profile_cipher.encrypt(
                json.dumps({"values": values, "uses_server": uses_server})
            )
            if self.model_settings
            else "",
            quota_day=day,
            quota_status="reserved" if day else "none",
            enqueued_at=now,
            expires_at=now + timedelta(seconds=self.settings.queue_wait_seconds),
            using_db=connection,
        )
        record.outcome = "queued"
        record.state.update(
            operation_id=operation.operation_id,
            enqueued_at=now.isoformat(),
            expires_at=operation.expires_at.isoformat(),
            queue_position=await SessionOperation.filter(status="queued", id__lte=operation.id)
            .using_db(connection)
            .count(),
        )

    async def _finish_operation(
        self,
        operation: SessionOperation,
        status: str,
        connection: BaseDBAsyncClient,
    ) -> None:
        await ModelSettingsService.settle(operation, connection, started=False)
        operation.status = status
        operation.finished_at = datetime.now(UTC)
        operation.encrypted_models = ""
        operation.encrypted_input = ""
        await operation.save(using_db=connection)

    async def _dispatch_locked(self) -> None:
        changed = False
        while (
            not self.closing
            and len(self.tasks) + len(self.testing_users) < self.settings.concurrent_total_limit
        ):
            operation = await SessionOperation.filter(status="queued").order_by("id").first()
            if operation is None:
                break
            token = current_user_id.set(operation.owner_id)
            models = None
            try:
                record = await self._get(operation.session_id)
                if record.task is not None and not record.task.done():
                    break
                if operation.expires_at <= datetime.now(UTC):
                    async with in_transaction() as connection:
                        await self._cancel_waiting(record, operation, connection, expired=True)
                    self._notify(record)
                    changed = True
                    continue
                try:
                    encoded = json.loads(self.profile_cipher.decrypt(operation.encrypted_input))
                    graph_input: Any = (
                        Command(resume=encoded["value"])
                        if encoded["resume"]
                        else _restore_state(encoded["value"])
                    )
                    if self.model_settings:
                        configuration = json.loads(
                            self.profile_cipher.decrypt(operation.encrypted_models)
                        )
                        models = self.model_settings.restore(
                            configuration["values"], configuration["uses_server"]
                        )
                except Exception:
                    self._interrupt(record)
                    async with in_transaction() as connection:
                        await self._persist(record, connection=connection)
                        await self._finish_operation(operation, "failed", connection)
                    self._notify(record)
                    changed = True
                    continue
                previous_outcome = record.outcome
                previous_version = record.snapshot_version
                previous_state = dict(record.state)
                record.outcome = "running"
                record.state.update(
                    run_id=None, progress=SearchProgress(), progress_seq=0, stop_reason=None
                )
                try:
                    async with in_transaction() as connection:
                        await self._persist(record, connection=connection)
                        await ModelSettingsService.settle(operation, connection, started=True)
                        operation.status = "running"
                        operation.started_at = datetime.now(UTC)
                        await operation.save(using_db=connection)
                except BaseException:
                    record.outcome = previous_outcome
                    record.snapshot_version = previous_version
                    record.state = previous_state
                    await self._close_models(models)
                    raise
                self.sessions[record.session_id] = record
                self._start(record, graph_input, models=models, operation=operation)
                self._notify(record)
                changed = True
            finally:
                current_user_id.reset(token)
        if changed:
            await self._notify_positions()

    async def _execute_operation(
        self,
        record: _Session,
        graph_input: Any,
        run_id: str,
        models: Any,
        operation: SessionOperation,
    ) -> None:
        try:
            await self._operate(record, graph_input, run_id, models=models)
        finally:
            # The slot remains occupied until _operate has closed providers and graph resources.
            async with self.lock:
                if self.closing and record.outcome == "running":
                    self._interrupt(record)
                    await self._persist(record)
                if await SessionOperation.filter(
                    operation_id=operation.operation_id, status="running"
                ).exists():
                    async with in_transaction() as connection:
                        await self._write_lock(connection)
                        status = (
                            "succeeded"
                            if record.active_run_id == run_id
                            and record.outcome in {"paused", "completed"}
                            else "failed"
                        )
                        await self._finish_operation(operation, status, connection)
                if record.task is asyncio.current_task():
                    record.task = None
                self._trim_cache()
                self.wake.set()

    async def _schedule(self) -> None:
        while not self.closing:
            self.wake.clear()
            try:
                async with self.lock:
                    if time.monotonic() >= self.next_cleanup:
                        await self._cleanup_locked()
                        self.next_cleanup = (
                            time.monotonic() + self.settings.cleanup_interval_seconds
                        )
                    await self._dispatch_locked()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("operation_dispatch_failed")
            try:
                await asyncio.wait_for(self.wake.wait(), self.settings.queue_scan_seconds)
            except TimeoutError:
                pass

    async def _notify_positions(self) -> None:
        changed = await Tortoise.get_connection("default").execute_query_dict(
            """
            WITH positions AS (
                SELECT session_id, ROW_NUMBER() OVER (ORDER BY id) AS position
                FROM session_operations WHERE status='queued'
            )
            UPDATE workspace_sessions
            SET snapshot_version=snapshot_version+1,
                state=json_set(state, '$.queue_position',
                    (SELECT position FROM positions WHERE positions.session_id=workspace_sessions.session_id))
            WHERE outcome='queued' AND session_id IN (SELECT session_id FROM positions)
                AND COALESCE(json_extract(state, '$.queue_position'), -1) !=
                    (SELECT position FROM positions WHERE positions.session_id=workspace_sessions.session_id)
            RETURNING session_id, owner_id, snapshot_version,
                json_extract(state, '$.queue_position') AS queue_position
            """
        )
        for item in changed:
            session_id = str(item["session_id"])
            record = self.sessions.get(session_id)
            if record is not None:
                record.snapshot_version = item["snapshot_version"]
                record.state["queue_position"] = item["queue_position"]
            if session_id not in self.subscribers:
                continue
            token = current_user_id.set(str(item["owner_id"]))
            try:
                record = await self._get(session_id)
                self._notify(record)
            finally:
                current_user_id.reset(token)

    async def _cancel_waiting(
        self,
        record: _Session,
        operation: SessionOperation,
        connection: BaseDBAsyncClient,
        *,
        expired: bool,
    ) -> None:
        self._retain_accepted_command(record)
        record.outcome = "failed" if expired else "cancelled"
        record.state.update(
            current_stage=record.outcome,
            retryable=True,
            errors=[
                WorkflowError(
                    code="queue_expired" if expired else "queue_cancelled",
                    message="The queued operation expired."
                    if expired
                    else "The queued operation was cancelled.",
                    stage="workflow",
                )
            ],
        )
        await self._persist(record, connection=connection)
        await self._finish_operation(operation, "expired" if expired else "cancelled", connection)

    async def cancel(self, session_id: str, payload: SessionCancelRequest) -> SessionResponse:
        async with self.lock:
            record = await self._get(session_id)
            fingerprint = _fingerprint(payload.model_dump(mode="json"))
            scope = f"cancel:{session_id}"
            previous = await AcceptedRequest.get_or_none(
                owner_id=owner_id(), scope=scope, request_id=payload.request_id
            )
            if previous:
                if previous.fingerprint != fingerprint:
                    raise SessionOperationError(
                        409, "Request ID has different content.", code="request_conflict"
                    )
                return self._response(record)
            operation = await SessionOperation.get_or_none(
                operation_id=payload.operation_id, owner_id=owner_id(), session_id=session_id
            )
            if (
                operation is None
                or record.revision != payload.expected_revision
                or operation.revision != record.revision
            ):
                raise SessionOperationError(
                    409, "The operation has changed.", code="search_changed"
                )
            if operation.status != "queued":
                raise SessionOperationError(
                    409,
                    "The operation has already started or finished.",
                    code="operation_already_started",
                )
            previous_state = dict(record.state)
            previous_outcome = record.outcome
            previous_version = record.snapshot_version
            try:
                async with in_transaction() as connection:
                    await self._write_lock(connection)
                    await self._cancel_waiting(record, operation, connection, expired=False)
                    await AcceptedRequest.create(
                        owner_id=owner_id(),
                        scope=scope,
                        request_id=payload.request_id,
                        fingerprint=fingerprint,
                        session_id=session_id,
                        using_db=connection,
                    )
            except BaseException:
                record.state = previous_state
                record.outcome = previous_outcome
                record.snapshot_version = previous_version
                raise
            self._notify(record)
            await self._notify_positions()
            self.wake.set()
            return self._response(record)

    async def _cleanup_locked(self) -> None:
        remaining = self.settings.cleanup_batch_size
        now = datetime.now(UTC)
        expired = (
            await SessionOperation.filter(status="queued", expires_at__lte=now)
            .order_by("id")
            .limit(remaining)
        )
        for operation in expired:
            token = current_user_id.set(operation.owner_id)
            try:
                record = await self._get(operation.session_id)
                async with in_transaction() as connection:
                    await self._cancel_waiting(record, operation, connection, expired=True)
                self._notify(record)
            finally:
                current_user_id.reset(token)
        remaining -= len(expired)
        if expired:
            await self._notify_positions()
        if remaining:
            logins = (
                await LoginSession.filter(expires_at__lte=now)
                .limit(remaining)
                .values_list("token_hash", flat=True)
            )
            await LoginSession.filter(token_hash__in=logins).delete()
            remaining -= len(logins)
        if remaining:
            ids = (
                await SessionOperation.filter(
                    status__not_in=["queued", "running"],
                    finished_at__lte=now
                    - timedelta(seconds=self.settings.operation_retention_seconds),
                )
                .limit(remaining)
                .values_list("id", flat=True)
            )
            await SessionOperation.filter(id__in=ids).delete()
        self._trim_cache()

    def _start(
        self,
        record: _Session,
        graph_input: Any,
        *,
        previous_task: asyncio.Task[None] | None = None,
        models: Any = None,
        operation: SessionOperation,
    ) -> None:
        run_id = uuid4().hex
        if previous_task is not None:
            record.previous_tasks.add(previous_task)
            previous_task.add_done_callback(record.previous_tasks.discard)
        record.active_run_id = run_id
        record.operation_models = models
        record.stop_event = asyncio.Event()
        record.task = asyncio.create_task(
            self._execute_operation(record, graph_input, run_id, models, operation)
        )
        self.tasks.add(record.task)
        record.task.add_done_callback(self.tasks.discard)
        record.task.add_done_callback(lambda _: self.wake.set())

    async def _operate(
        self,
        record: _Session,
        graph_input: Any,
        run_id: str,
        *,
        previous_task: asyncio.Task[None] | None = None,
        models: Any = None,
    ) -> None:
        revision = record.revision
        thread_id = record.thread_id
        graph = self.graph

        async def on_progress(update: dict[str, Any]) -> None:
            await self._progress(record, run_id, revision, update)

        config = self._config(thread_id)
        config["configurable"].update(
            run_id=run_id, stop_event=record.stop_event, on_progress=on_progress
        )
        try:
            if models is not None:
                graph = self.graph_factory(models.provider)
            if previous_task is not None:
                previous_finished = asyncio.gather(previous_task, return_exceptions=True)
                try:
                    await asyncio.shield(previous_finished)
                except asyncio.CancelledError:
                    # The superseded worker owns its provider until its cleanup finishes.
                    # Cancelling this worker must not cancel that cleanup a second time.
                    await asyncio.shield(previous_finished)
                    raise
            state = await graph.ainvoke(graph_input, config)
            snapshot = await graph.aget_state(self._config(thread_id))
            async with self.lock:
                if (
                    record.deleted
                    or self.closing
                    or self.sessions.get(record.session_id) is not record
                    or record.outcome != "running"
                    or record.active_run_id != run_id
                ):
                    return
                previous_state = dict(record.state)
                self._merge_snapshot(record, state)
                stage = state.get("current_stage")
                record.outcome = (
                    "failed" if stage == "failed" else "paused" if snapshot.next else "completed"
                )
                if record.outcome in {"paused", "completed"}:
                    record.state.pop("accepted_resume", None)
                try:
                    await self._persist(record)
                except BaseException:
                    record.state = previous_state
                    record.outcome = "running"
                    raise
                self._notify(record)
        except asyncio.CancelledError:
            raise
        except Exception:
            recovered: dict[str, Any] = {}
            try:
                snapshot = await graph.aget_state(self._config(thread_id))
                recovered = snapshot.values
            except Exception:
                pass
            async with self.lock:
                if (
                    record.deleted
                    or self.closing
                    or record.outcome != "running"
                    or record.active_run_id != run_id
                    or self.sessions.get(record.session_id) is not record
                ):
                    return
                if recovered:
                    self._merge_snapshot(record, recovered)
                logger.warning("session_operation_failed", extra={"stage": "workflow"})
                record.state["errors"] = [
                    WorkflowError(
                        code="workflow_execution_error",
                        message="Processing did not finish. Please try again; your input has been saved.",
                        stage="workflow",
                    )
                ]
                record.state["current_stage"] = "failed"
                record.state["retryable"] = True
                record.outcome = "failed"
                self._retain_accepted_command(record)
                await self._persist(record)
                self._notify(record)

        finally:
            if models is not None:
                try:
                    await graph.cleanup_session(record.session_id)
                except Exception:
                    logger.warning("session_cleanup_failed")
                finally:
                    await self._close_models(models)
                    if record.operation_models is models:
                        record.operation_models = None

    @staticmethod
    async def _close_models(models: Any) -> None:
        if models is not None:
            try:
                await models.provider.aclose()
            except Exception:
                logger.warning("session_provider_close_failed")

    def _response(self, record: _Session) -> SessionResponse:
        state = record.state
        notices = dedupe_notices(
            [
                *state.get("notices", []),
                *source_notices(state.get("source_outcomes", [])),
            ]
        )
        recommendation = state.get("recommendation")
        if recommendation is not None:
            recommendation = finalize_recommendation(
                RecommendationResult.model_validate(recommendation),
                notices=notices,
            )
            notices = recommendation.notices
        notices = [notice for notice in notices if notice.scope != "job"]
        retryable = record.outcome in {"failed", "cancelled"} and bool(state.get("retryable", True))
        errors = [
            public_error(
                error.code,
                retryable=retryable,
            )
            for error in state.get("errors", [])
        ]
        return SessionResponse.model_validate(
            {
                "session_id": record.session_id,
                "snapshot_version": record.snapshot_version,
                "operation_id": record.state.get("operation_id"),
                "queue_position": record.state.get("queue_position")
                if record.outcome == "queued"
                else None,
                "enqueued_at": record.state.get("enqueued_at"),
                "expires_at": record.state.get("expires_at"),
                "operation_kind": state.get("operation_kind", "initial_search"),
                "job_feedback": state.get("job_feedback", []),
                "hidden_job_ids": state.get("hidden_job_ids", []),
                "hidden_job_reasons": state.get("hidden_job_reasons", []),
                "result_preferences": state.get("result_preferences", {}),
                "result_order": state.get("result_order", []),
                "outcome": record.outcome,
                "current_stage": state.get("current_stage", "ingest"),
                "revision": record.revision,
                "profile": state.get("profile"),
                "clarification_questions": state.get("clarification_questions", []),
                "conversation": state.get("conversation", []),
                "search_summary": state.get("search_summary"),
                "source_outcomes": state.get("source_outcomes", []),
                "recommendation": recommendation,
                "errors": errors,
                "notices": notices,
                "retryable": retryable,
                "mode": record.mode,
                "run_id": state.get("run_id"),
                "progress": state.get("progress", {}),
                "stop_reason": state.get("stop_reason"),
            }
        )
