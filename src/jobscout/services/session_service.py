"""Single-process operation ownership, idempotency and session snapshots."""

import asyncio
import hashlib
import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.session import SessionCreateRequest, SessionResponse, SessionResumeRequest

logger = logging.getLogger(__name__)


class SessionOperationError(ValueError):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)


@dataclass
class _Session:
    session_id: str
    state: dict[str, Any]
    revision: int = 1
    outcome: str = "running"
    task: asyncio.Task[None] | None = None
    requests: dict[str, str] = field(default_factory=dict)
    deleted: bool = False
    thread_id: str = ""
    thread_ids: list[str] = field(default_factory=list)


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class SessionService:
    def __init__(self, graph: Any, checkpointer: Any, *, mode: str = "live") -> None:
        self.graph = graph
        self.checkpointer = checkpointer
        self.mode = mode
        self.sessions: dict[str, _Session] = {}
        self.creation_requests: dict[str, tuple[str, str]] = {}
        self.lock = asyncio.Lock()

    async def create(self, payload: SessionCreateRequest) -> SessionResponse:
        data = payload.model_dump(mode="json")
        fingerprint = _fingerprint(data)
        async with self.lock:
            previous = self.creation_requests.get(payload.request_id)
            if previous:
                previous_fingerprint, session_id = previous
                if fingerprint != previous_fingerprint:
                    raise SessionOperationError(
                        409, "This request ID has already been used for different content."
                    )
                record = self._get(session_id)
                return self._response(record)
            if not payload.description.strip() and not (
                payload.resume and payload.resume.text.strip()
            ):
                raise SessionOperationError(422, "Provide a resume or personal introduction.")
            session_id = str(uuid4())
            state: dict[str, Any] = {
                "session_id": session_id,
                "input_data": data,
                "revision": 1,
                "current_stage": "ingest",
            }
            record = _Session(session_id, state, thread_id=session_id, thread_ids=[session_id])
            self.sessions[session_id] = record
            self.creation_requests[payload.request_id] = (fingerprint, session_id)
            self._start(record, state)
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
                        409, "This request ID has already been used for different content."
                    )
                return self._response(record)
            if record.revision != payload.expected_revision:
                raise SessionOperationError(
                    409, "The session has been updated. Refresh and try again."
                )
            if record.task is not None and not record.task.done():
                raise SessionOperationError(
                    409, "An operation is already in progress for this session."
                )
            if record.outcome == "completed" and payload.action != "edit_conditions":
                raise SessionOperationError(
                    409, "Update your criteria before confirming a new search."
                )
            if record.outcome == "failed" and payload.action not in {"retry", "edit_conditions"}:
                raise SessionOperationError(409, "Try again or update your criteria.")
            if payload.action == "retry" and record.outcome != "failed":
                raise SessionOperationError(409, "This session does not need to be retried.")
            self._validate_answers(record, payload)
            record.requests[payload.request_id] = fingerprint
            record.revision += 1
            record.state["revision"] = record.revision
            if record.outcome in {"completed", "failed"}:
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
            if payload.action == "edit_conditions":
                record.state["recommendation"] = None
                record.state["search_summary"] = None
            record.state["errors"] = []
            self._start(record, next_input)
            return self._response(record)

    @staticmethod
    def _validate_answers(record: _Session, payload: SessionResumeRequest) -> None:
        questions = record.state.get("clarification_questions", [])
        pending = {
            (q.get("question_id") if isinstance(q, dict) else q.question_id): q
            for q in questions
            if (q.get("status") if isinstance(q, dict) else q.status) == "pending"
        }
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
            if question.get("required") if isinstance(question, dict) else question.required:
                raise SessionOperationError(422, "Required questions cannot be skipped.")
        for answer in payload.answers:
            question = pending[answer.question_id]
            values = question if isinstance(question, dict) else question.model_dump()
            control = values.get("control_type", "text")
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
            options = {option["id"] for option in values.get("options", [])}
            if control != "text" and any(value not in options for value in selected):
                raise SessionOperationError(422, "The answer contains an invalid option.")
        allowed = {
            "education",
            "skills",
            "internships",
            "projects",
            "target_directions",
            "preferences.location",
            "preferences.location_unrestricted",
            "preferences.employment_type",
            "preferences.employment_type_unrestricted",
            "preferences.salary_range",
            "preferences.work_mode",
            "preferences.industry",
        }
        if set(payload.profile_updates) - allowed:
            raise SessionOperationError(422, "The request includes fields that cannot be edited.")
        list_fields = {"education", "skills", "internships", "projects", "target_directions"}
        flag_fields = {
            "preferences.location_unrestricted",
            "preferences.employment_type_unrestricted",
        }
        for name, value in payload.profile_updates.items():
            if name in list_fields:
                valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
            elif name in flag_fields:
                valid = isinstance(value, bool)
            else:
                valid = value is None or isinstance(value, str)
            if not valid:
                raise SessionOperationError(
                    422, "One or more edited fields have an invalid value type."
                )
        if payload.action == "confirm_search" and record.outcome == "paused":
            summary = record.state.get("search_summary")
            summary_data = (
                summary
                if isinstance(summary, dict)
                else (summary.model_dump() if summary is not None else {})
            )
            if not summary_data.get("ready") or summary_data.get("revision") != record.revision:
                raise SessionOperationError(
                    409, "Review and complete the current search summary first."
                )

    async def get(self, session_id: str) -> SessionResponse:
        async with self.lock:
            record = self._get(session_id)
            if record.outcome == "running":
                snapshot = await self.graph.aget_state(self._config(record.thread_id))
                if (
                    snapshot.values
                    and snapshot.values.get("revision", 0) >= record.revision
                    and not record.deleted
                ):
                    record.state.update(snapshot.values)
            return self._response(record)

    async def delete(self, session_id: str) -> None:
        async with self.lock:
            record = self._get(session_id)
            record.deleted = True
            self.sessions.pop(session_id)
            task = record.task
            if task is not None:
                task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        for thread_id in record.thread_ids:
            await self.checkpointer.adelete_thread(thread_id)
        await self._cleanup_session(session_id)

    async def _cleanup_session(self, session_id: str) -> None:
        cleanup = getattr(self.graph, "cleanup_session", None)
        if cleanup is not None:
            result = cleanup(session_id)
            if inspect.isawaitable(result):
                await result

    async def close(self) -> None:
        tasks = []
        for record in self.sessions.values():
            record.deleted = True
            if record.task is not None:
                record.task.cancel()
                tasks.append(record.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for record in self.sessions.values():
            await self._cleanup_session(record.session_id)
            for thread_id in record.thread_ids:
                await self.checkpointer.adelete_thread(thread_id)
        self.sessions.clear()
        self.creation_requests.clear()

    def _get(self, session_id: str) -> _Session:
        record = self.sessions.get(session_id)
        if record is None or record.deleted:
            raise SessionOperationError(404, "This session does not exist or has expired.")
        return record

    @staticmethod
    def _config(session_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": session_id}, "recursion_limit": 100}

    def _start(self, record: _Session, graph_input: Any) -> None:
        record.task = asyncio.create_task(self._operate(record, graph_input))

    async def _operate(self, record: _Session, graph_input: Any) -> None:
        try:
            state = await self.graph.ainvoke(graph_input, self._config(record.thread_id))
            snapshot = await self.graph.aget_state(self._config(record.thread_id))
            if record.deleted or self.sessions.get(record.session_id) is not record:
                return
            record.state = dict(state)
            stage = state.get("current_stage")
            record.outcome = (
                "failed" if stage == "failed" else "paused" if snapshot.next else "completed"
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            if not record.deleted:
                try:
                    snapshot = await self.graph.aget_state(self._config(record.thread_id))
                    if snapshot.values:
                        record.state.update(snapshot.values)
                except Exception:
                    pass
                logger.warning("session_operation_failed", extra={"stage": "workflow"})
                record.state["errors"] = [
                    WorkflowError(
                        code="workflow_execution_error",
                        message="Processing did not finish. Please try again; your input has been saved.",
                        stage="workflow",
                    )
                ]
                record.state["current_stage"] = "failed"
                record.outcome = "failed"

    def _response(self, record: _Session) -> SessionResponse:
        state = record.state
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
                "recommendation": state.get("recommendation"),
                "errors": state.get("errors", []),
                "warnings": list(dict.fromkeys(state.get("warnings", []))),
                "retryable": record.outcome == "failed",
                "mode": self.mode,
            }
        )
