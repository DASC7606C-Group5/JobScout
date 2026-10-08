"""Durable form drafts and source-independent saved recommendation snapshots."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import ValidationError
from tortoise.transactions import in_transaction

from jobscout.models import AcceptedRequest, SavedJob, WorkspaceDraft
from jobscout.schemas.recommendation import RecommendationItem
from jobscout.schemas.workspace import (
    ClarificationDraft,
    DraftResponse,
    DraftWriteRequest,
    ProfileDraft,
    SavedJobsResponse,
    SaveJobRequest,
    SummaryDraft,
)
from jobscout.services.encryption import ProfileDocumentCipher
from jobscout.services.identity import owner_id
from jobscout.services.session_service import SessionOperationError, SessionService, _fingerprint

DraftSection = Literal["clarification", "summary"]


def _encrypt_profile_draft(data: dict[str, Any], cipher: ProfileDocumentCipher) -> dict[str, Any]:
    resume = data.get("resume")
    if isinstance(resume, dict) and isinstance(resume.get("text"), str):
        return {**data, "resume": {**resume, "text": cipher.encrypt(resume["text"])}}
    return data


def _decrypt_profile_draft(data: dict[str, Any], cipher: ProfileDocumentCipher) -> dict[str, Any]:
    resume = data.get("resume")
    if isinstance(resume, dict) and isinstance(resume.get("text"), str):
        return {**data, "resume": {**resume, "text": cipher.decrypt(resume["text"])}}
    return data


class WorkspaceService:
    def __init__(
        self, sessions: SessionService, *, profile_cipher: ProfileDocumentCipher | None = None
    ) -> None:
        self.sessions = sessions
        self.profile_cipher = profile_cipher or ProfileDocumentCipher("")

    def _scope(
        self, session_id: str | None, session_revision: int | None, section: DraftSection | None
    ) -> str:
        if session_id is None:
            return "profile"
        record = self.sessions._get(session_id)
        if record.revision != session_revision:
            raise SessionOperationError(
                409, "The search has changed; reload before saving.", code="search_changed"
            )
        return f"session:{session_id}:{session_revision}:{section}"

    @staticmethod
    def _draft_response(draft: WorkspaceDraft | None) -> DraftResponse:
        if draft is None:
            return DraftResponse(data={}, revision=0, updated_at=None)
        return DraftResponse(data=draft.data, revision=draft.revision, updated_at=draft.updated_at)

    async def get_draft(
        self,
        *,
        session_id: str | None = None,
        session_revision: int | None = None,
        section: DraftSection | None = None,
    ) -> DraftResponse:
        async with self.sessions.lock:
            scope = self._scope(session_id, session_revision, section)
            draft = await WorkspaceDraft.get_or_none(owner_id=owner_id(), scope=scope)
            if draft is not None and scope == "profile":
                data = _decrypt_profile_draft(draft.data, self.profile_cipher)
                return DraftResponse(
                    data=data, revision=draft.revision, updated_at=draft.updated_at
                )
            return self._draft_response(draft)

    async def save_draft(
        self,
        payload: DraftWriteRequest,
        *,
        session_id: str | None = None,
        session_revision: int | None = None,
        section: DraftSection | None = None,
    ) -> DraftResponse:
        model = (
            ProfileDraft
            if session_id is None
            else ClarificationDraft
            if section == "clarification"
            else SummaryDraft
        )
        try:
            plain_data = model.model_validate(payload.data).model_dump(mode="json", by_alias=True)
        except ValidationError as error:
            raise SessionOperationError(422, "The draft fields are invalid.") from error
        data = (
            _encrypt_profile_draft(plain_data, self.profile_cipher)
            if session_id is None
            else plain_data
        )
        fingerprint = _fingerprint(payload.model_dump(mode="json"))
        async with self.sessions.lock:
            scope = self._scope(session_id, session_revision, section)
            request_scope = f"draft:{scope}"
            previous = await AcceptedRequest.get_or_none(
                owner_id=owner_id(), scope=request_scope, request_id=payload.request_id
            )
            current = await WorkspaceDraft.get_or_none(owner_id=owner_id(), scope=scope)
            if previous:
                if previous.fingerprint != fingerprint:
                    raise SessionOperationError(
                        409,
                        "The request ID was used for different content.",
                        code="request_conflict",
                    )
                if current is None or current.revision != payload.expected_revision + 1:
                    raise SessionOperationError(
                        409,
                        "The draft changed after this save. Reload before saving.",
                        code="draft_conflict",
                    )
                return DraftResponse(
                    data=(
                        _decrypt_profile_draft(current.data, self.profile_cipher)
                        if scope == "profile"
                        else current.data
                    ),
                    revision=current.revision,
                    updated_at=current.updated_at,
                )
            revision = current.revision if current else 0
            if payload.expected_revision != revision:
                raise SessionOperationError(
                    409,
                    "The draft has changed. Reload before saving.",
                    code="draft_conflict",
                )
            now = datetime.now(UTC)
            async with in_transaction() as connection:
                values = {
                    "data": data,
                    "revision": revision + 1,
                    "session_id": session_id,
                    "updated_at": now,
                }
                updated = (
                    await WorkspaceDraft.filter(owner_id=owner_id(), scope=scope)
                    .using_db(connection)
                    .update(**values)
                )
                if not updated:
                    await WorkspaceDraft.create(
                        owner_id=owner_id(), scope=scope, using_db=connection, **values
                    )
                await AcceptedRequest.create(
                    owner_id=owner_id(),
                    scope=request_scope,
                    request_id=payload.request_id,
                    fingerprint=fingerprint,
                    session_id=session_id,
                    using_db=connection,
                )
            return DraftResponse(data=plain_data, revision=revision + 1, updated_at=now)

    async def delete_draft(
        self,
        *,
        session_id: str | None = None,
        session_revision: int | None = None,
        section: DraftSection | None = None,
    ) -> None:
        async with self.sessions.lock:
            scope = self._scope(session_id, session_revision, section)
            await WorkspaceDraft.filter(owner_id=owner_id(), scope=scope).delete()

    async def saved_jobs(self) -> SavedJobsResponse:
        return SavedJobsResponse(
            items=[
                RecommendationItem.model_validate(record.item)
                for record in await SavedJob.filter(owner_id=owner_id()).order_by(
                    "-saved_at", "job_id"
                )
            ]
        )

    async def save_job(self, job_id: str, payload: SaveJobRequest) -> RecommendationItem:
        async with self.sessions.lock:
            record = self.sessions._get(payload.session_id)
            if record.revision != payload.expected_revision:
                raise SessionOperationError(
                    409, "The recommendation has changed. Reload it.", code="search_changed"
                )
            recommendation = self.sessions._response(record).recommendation
            item = (
                next(
                    (
                        item
                        for item in [*recommendation.jobs, *recommendation.pending_jobs]
                        if item.job.job_id == job_id
                    ),
                    None,
                )
                if recommendation
                else None
            )
            if item is None and record.state.get("published_run_id") == record.state.get("run_id"):
                published = record.state.get("published_jobs", {}).get(job_id)
                if published is not None:
                    item = RecommendationItem.model_validate(published)
            if item is None:
                raise SessionOperationError(
                    404, "This recommendation was not found.", code="saved_job_not_found"
                )
            values: dict[str, Any] = {
                "item": item.model_dump(mode="json"),
                "session_id": payload.session_id,
                "session_revision": payload.expected_revision,
                "saved_at": datetime.now(UTC),
            }
            updated = await SavedJob.filter(owner_id=owner_id(), job_id=job_id).update(**values)
            if not updated:
                await SavedJob.create(owner_id=owner_id(), job_id=job_id, **values)
            return item

    async def unsave_job(self, job_id: str) -> None:
        await SavedJob.filter(owner_id=owner_id(), job_id=job_id).delete()
