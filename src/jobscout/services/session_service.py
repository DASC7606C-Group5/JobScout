"""Durable session snapshots with single-process operation ownership."""

import asyncio
import hashlib
import json
import logging
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import uuid4

from langgraph.types import Command
from pydantic import BaseModel, TypeAdapter
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from jobscout.config import get_settings
from jobscout.models import AcceptedRequest, SearchSession, WorkspaceDraft
from jobscout.schemas.conversation import ConversationMessage, SearchSummary
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.execution import SearchProgress
from jobscout.schemas.job import JobPosting, SourceDocument
from jobscout.schemas.notices import ApplicantNotice
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import ClarificationMessage
from jobscout.schemas.session import (
    SessionCreateRequest,
    SessionResponse,
    SessionResumeRequest,
    SessionStopRequest,
)
from jobscout.schemas.workspace import SessionHistoryItem, SessionHistoryResponse
from jobscout.services.encryption import (
    ProfileDocumentCipher,
    decrypt_documents,
    encrypt_documents,
)
from jobscout.services.identity import owner_id
from jobscout.services.job_retrieval.models import SourceOutcome
from jobscout.services.notice_service import (
    dedupe_notices,
    finalize_recommendation,
    public_error,
    source_notices,
)

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
    requests: dict[str, str] = field(default_factory=dict)
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
    }
    restored = dict(state)
    for key, model in models.items():
        if restored.get(key) is not None:
            restored[key] = model.model_validate(restored[key])
    for key, model in sequences.items():
        if key in restored:
            restored[key] = [model.model_validate(item) for item in restored[key]]
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
    ) -> None:
        self.model_settings = model_settings
        self.graph_factory = graph_factory
        self.profile_cipher = profile_cipher or ProfileDocumentCipher(
            get_settings().credentials_key.get_secret_value()
        )
        self.testing_users: set[str] = set()
        self.graph = graph
        self.checkpointer = checkpointer
        self.mode = mode
        self.sessions: dict[str, _Session] = {}
        self.creation_requests: dict[tuple[str, str], tuple[str, str]] = {}
        self.lock = asyncio.Lock()
        self.closing = False
        self.subscribers: dict[str, set[asyncio.Queue[SessionResponse | None]]] = {}

    async def subscribe(self, session_id: str) -> asyncio.Queue[SessionResponse | None]:
        """Register and capture the current snapshot under the same lock as updates."""
        async with self.lock:
            record = self._get(session_id)
            if self.closing:
                raise SessionOperationError(503, "Service is closing.", code="service_unavailable")
            queue: asyncio.Queue[SessionResponse | None] = asyncio.Queue(maxsize=16)
            queue.put_nowait(self._response(record).model_copy(deep=True))
            self.subscribers.setdefault(session_id, set()).add(queue)
            return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[SessionResponse | None]) -> None:
        listeners = self.subscribers.get(session_id)
        if listeners is not None:
            listeners.discard(queue)
            if not listeners:
                self.subscribers.pop(session_id, None)

    def _notify(self, record: _Session) -> None:
        listeners = self.subscribers.get(record.session_id)
        if not listeners:
            return
        snapshot = (
            None if record.deleted or self.closing else self._response(record).model_copy(deep=True)
        )
        for queue in listeners:
            # Slow readers recover to the latest state without delaying the search.
            if queue.full() or snapshot is None:
                while not queue.empty():
                    queue.get_nowait()
            queue.put_nowait(snapshot)

    async def open(self) -> None:
        """Recover checkpoints without invoking providers or restarting accepted work."""
        for stored in await SearchSession.all():
            record = _Session(
                stored.session_id,
                _restore_state(stored.state, self.profile_cipher),
                owner_id=stored.owner_id,
                revision=stored.revision,
                outcome=stored.outcome,
                thread_id=stored.thread_id,
                thread_ids=stored.thread_ids,
                deleted=stored.deleting,
                mode=stored.mode,
                created_at=stored.created_at,
                updated_at=stored.updated_at,
            )
            self.sessions[record.session_id] = record
            if record.deleted:
                try:
                    await self._finish_delete(record)
                except Exception:
                    logger.warning("session_deletion_pending")
                continue
            if record.outcome not in {"running", "paused"}:
                continue
            snapshot = await self.graph.aget_state(self._config(record.thread_id))
            if snapshot.values and snapshot.values.get("revision", 0) >= record.revision:
                self._merge_snapshot(record, snapshot.values)
                if snapshot.values.get("current_stage") == "failed":
                    record.outcome = "failed"
                elif not snapshot.next:
                    record.outcome = "completed"
                elif any(getattr(task, "interrupts", ()) for task in snapshot.tasks):
                    record.outcome = "paused"
                else:
                    self._interrupt(record)
            else:
                self._interrupt(record)
            if record.outcome in {"paused", "completed"}:
                record.state.pop("accepted_resume", None)
            await self._persist(record)
        for accepted in await AcceptedRequest.filter(
            Q(scope="create") | Q(scope__startswith="resume:")
        ):
            if accepted.scope == "create" and accepted.session_id:
                self.creation_requests[(accepted.owner_id, accepted.request_id)] = (
                    accepted.fingerprint,
                    accepted.session_id,
                )
            elif accepted.scope.startswith("resume:") and accepted.session_id in self.sessions:
                self.sessions[accepted.session_id].requests[accepted.request_id] = (
                    accepted.fingerprint
                )

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

    async def create(self, payload: SessionCreateRequest) -> SessionResponse:
        data = payload.model_dump(mode="json")
        fingerprint = _fingerprint(data)
        async with self.lock:
            previous = self.creation_requests.get((owner_id(), payload.request_id))
            if previous:
                previous_fingerprint, session_id = previous
                if fingerprint != previous_fingerprint:
                    raise SessionOperationError(
                        409,
                        "This request ID has already been used for different content.",
                        code="request_conflict",
                    )
                record = self._get(session_id)
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
            self.check_capacity()
            models = await self.model_settings.prepare(owner_id()) if self.model_settings else None
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
            try:
                async with in_transaction() as connection:
                    await self._persist(record, connection=connection)
                    if models and models.uses_server:
                        await self.model_settings.charge(owner_id(), connection)
                    await AcceptedRequest.create(
                        owner_id=owner_id(),
                        scope="create",
                        request_id=payload.request_id,
                        fingerprint=fingerprint,
                        session_id=session_id,
                        using_db=connection,
                    )
            except BaseException:
                await self._close_models(models)
                raise
            self.sessions[session_id] = record
            self.creation_requests[(owner_id(), payload.request_id)] = (fingerprint, session_id)
            self._start(record, state, models=models)
            return self._response(record)

    async def resume(self, session_id: str, payload: SessionResumeRequest) -> SessionResponse:
        data = payload.model_dump(mode="json")
        fingerprint = _fingerprint(data)
        async with self.lock:
            record = self._get(session_id)
            previous = record.requests.get(payload.request_id)
            if previous:
                if previous != fingerprint:
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
            if record.task is not None and not record.task.done() and not editing_run:
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
            if record.outcome == "failed" and payload.action not in {"retry", "edit_conditions"}:
                raise SessionOperationError(
                    409, "Try again or update your criteria.", code="search_not_retryable"
                )
            if payload.action == "retry" and record.outcome != "failed":
                raise SessionOperationError(
                    409, "This session does not need to be retried.", code="search_not_retryable"
                )
            if payload.action == "retry" and not record.state.get("retryable", True):
                raise SessionOperationError(
                    409, "This search cannot be retried.", code="search_not_retryable"
                )
            self._validate_answers(record, payload)
            self.check_capacity(exclude_session=session_id if editing_run else None)
            models = await self.model_settings.prepare(owner_id()) if self.model_settings else None
            previous_state = dict(record.state)
            previous_outcome = record.outcome
            previous_thread = record.thread_id
            previous_threads = list(record.thread_ids)
            previous_updated_at = record.updated_at
            record.revision += 1
            record.state["revision"] = record.revision
            if payload.action == "edit_conditions":
                record.state.update(
                    recommendation=None,
                    search_summary=None,
                    run_id=None,
                    progress=SearchProgress(),
                    progress_seq=0,
                    stop_reason=None,
                    source_outcomes=[],
                )
            if record.outcome in {"completed", "failed"} or editing_run:
                record.thread_id = f"{session_id}:{record.revision}"
                record.thread_ids.append(record.thread_id)
                next_input: Any = {
                    **record.state,
                    "command": data,
                    "errors": [],
                    "current_stage": payload.action,
                    "recommendation": None,
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
                    await self._persist(record, connection=connection)
                    if models and models.uses_server:
                        await self.model_settings.charge(owner_id(), connection)
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
                await self._close_models(models)
                raise
            record.requests[payload.request_id] = fingerprint
            if previous_task is not None and not previous_task.cancelling():
                previous_task.cancel()
            self._start(record, next_input, previous_task=previous_task, models=models)
            self._notify(record)
            return self._response(record)

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
        async with self.lock:
            record = self._get(session_id)
            if record.outcome != "running":
                return self._response(record)
            thread_id, revision = record.thread_id, record.revision
            record.checkpoint_read_id += 1
            read_id = record.checkpoint_read_id
        # Checkpoint reads can wait on the graph writer; other sessions must remain usable.
        snapshot = await self.graph.aget_state(self._config(thread_id))
        async with self.lock:
            record = self._get(session_id)
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
                except BaseException:
                    record.state = previous_state
                    raise
            return self._response(record)

    async def stop(self, session_id: str, payload: SessionStopRequest) -> SessionResponse:
        """Stop further retrieval while the current run finishes reviewing its vacancies."""
        fingerprint = _fingerprint(payload.model_dump(mode="json"))
        async with self.lock:
            record = self._get(session_id)
            if record.state.get("run_id") != payload.run_id:
                raise SessionOperationError(
                    409, "The search run has changed.", code="search_changed"
                )
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
        record.state.update(incoming)

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
                record.state["recommendation"] = RecommendationResult.model_validate(
                    update["recommendation"]
                ).model_copy(deep=True)
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
            if "source_outcomes" in update:
                record.state["source_outcomes"] = [
                    SourceOutcome.model_validate(value).model_copy(deep=True)
                    for value in update["source_outcomes"]
                ]
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
                        Literal["running", "paused", "completed", "failed"], stored.outcome
                    ),
                    current_stage=state.get("current_stage", "ingest"),
                    revision=stored.revision,
                    created_at=stored.created_at,
                    updated_at=stored.updated_at,
                    retryable=stored.outcome == "failed" and bool(state.get("retryable", True)),
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
            record = self.sessions.get(session_id)
            if record is None:
                if await AcceptedRequest.filter(
                    owner_id=owner_id(), scope="create", session_id=session_id
                ).exists():
                    return
                raise SessionOperationError(
                    404, "This search was not found.", code="search_not_found"
                )
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

    async def _finish_delete(self, record: _Session) -> None:
        for thread_id in record.thread_ids:
            await self.checkpointer.adelete_thread(thread_id)
        await self._cleanup_session(record.session_id)
        await SearchSession.filter(session_id=record.session_id).delete()
        self.sessions.pop(record.session_id, None)

    async def _cleanup_session(self, session_id: str) -> None:
        await self.graph.cleanup_session(session_id)

    async def close(self) -> None:
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
        self.creation_requests.clear()
        self.subscribers.clear()
        if failures:
            raise ExceptionGroup("Session shutdown failed", failures)

    def _get(self, session_id: str) -> _Session:
        record = self.sessions.get(session_id)
        if record is None or record.deleted or record.owner_id != owner_id():
            raise SessionOperationError(
                404, "This session does not exist or has expired.", code="search_not_found"
            )
        return record

    @staticmethod
    def _config(session_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": session_id}, "recursion_limit": 100}

    def check_capacity(self, exclude_session: str | None = None) -> None:
        if self.closing:
            raise SessionOperationError(503, "Service is closing.", code="service_unavailable")
        if self.model_settings is None:
            return
        active = [
            record
            for record in self.sessions.values()
            if record.session_id != exclude_session
            and record.task is not None
            and not record.task.done()
        ]
        settings = self.model_settings.settings
        account_count = sum(record.owner_id == owner_id() for record in active) + (
            owner_id() in self.testing_users
        )
        if (
            account_count >= settings.concurrent_user_limit
            or len(active) + len(self.testing_users) >= settings.concurrent_total_limit
        ):
            from jobscout.services.auth_service import auth_error

            raise auth_error(429, "operation_capacity")

    def _start(
        self,
        record: _Session,
        graph_input: Any,
        *,
        previous_task: asyncio.Task[None] | None = None,
        models: Any = None,
    ) -> None:
        run_id = uuid4().hex
        if previous_task is not None:
            record.previous_tasks.add(previous_task)
            previous_task.add_done_callback(record.previous_tasks.discard)
        record.active_run_id = run_id
        record.operation_models = models
        record.stop_event = asyncio.Event()
        record.state.update(
            run_id=None, progress=SearchProgress(), progress_seq=0, stop_reason=None
        )
        record.task = asyncio.create_task(
            self._operate(record, graph_input, run_id, previous_task=previous_task, models=models)
        )

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
        retryable = record.outcome == "failed" and bool(state.get("retryable", True))
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
