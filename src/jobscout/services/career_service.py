"""Durable career records and narrow graph integration hooks."""

from datetime import UTC, datetime
from typing import Any

from tortoise.transactions import in_transaction

from jobscout.models import (
    JobApplicationRecord,
    PersonalProfileRecord,
    SavedJob,
    TaskJobFeedbackRecord,
)
from jobscout.schemas.career import (
    ApplicationTransition,
    ApplicationWrite,
    FeedbackWrite,
    JobApplication,
    PersonalProfile,
    ProfileWrite,
    TaskJobFeedback,
    TaskMetadata,
    adopt_background,
)
from jobscout.schemas.job import SourceDocument
from jobscout.schemas.profile import ProfilePreferences, UserProfile
from jobscout.schemas.recommendation import RecommendationItem
from jobscout.services.session_service import SessionOperationError, SessionService


async def load_current_profile() -> PersonalProfile:
    record = await PersonalProfileRecord.get_or_none(key="current")
    return (
        PersonalProfile.model_validate(record.data)
        if record
        else PersonalProfile(expected_revision=0)
    )


async def load_task_feedback(session_id: str) -> list[TaskJobFeedback]:
    return [
        TaskJobFeedback.model_validate(r.data)
        for r in await TaskJobFeedbackRecord.filter(session_id=session_id)
    ]


async def refresh_task_background(state: dict[str, Any]) -> dict[str, Any]:
    """B calls on continuation, then invalidates/reassesses affected candidates."""
    current = await load_current_profile()
    if not current.revision or state.get("profile_revision") == current.revision:
        return {}
    updates: dict[str, Any] = {
        "profile_revision": current.revision,
        "profile_documents": current_profile_documents(current)
        + [
            SourceDocument.model_validate(document)
            for document in state.get("profile_documents", [])
            if ":answer:" in SourceDocument.model_validate(document).document_id
        ],
    }
    for key in ("profile", "confirmed_profile"):
        if state.get(key) is not None:
            updates[key] = adopt_background(UserProfile.model_validate(state[key]), current)
    return updates


def current_profile_documents(current: PersonalProfile) -> list[SourceDocument]:
    """Keep supplied evidence and derive stable documents for current raw material."""
    raw = [
        SourceDocument(
            document_id=f"profile:personal-{current.revision}:{kind}",
            source="user",
            source_url="",
            text=text,
            fetched_at=current.updated_at or datetime.now(UTC),
        )
        for kind, text in (
            ("description", current.description),
            ("resume", current.resume.text if current.resume else ""),
        )
        if text
    ]
    documents = {
        document.document_id: document
        for document in current.documents
        if not (
            document.document_id.startswith("profile:")
            and document.document_id.endswith((":description", ":resume"))
        )
    }
    documents.update({document.document_id: document for document in raw})
    return list(documents.values())


class CareerService:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions

    async def save_profile(self, payload: ProfileWrite) -> PersonalProfile:
        async with self.sessions.lock, in_transaction():
            current = await load_current_profile()
            if payload.expected_revision != current.revision:
                raise SessionOperationError(
                    409, "Profile changed; reload before saving.", code="draft_conflict"
                )
            result = PersonalProfile(
                **payload.model_dump(), revision=current.revision + 1, updated_at=datetime.now(UTC)
            )
            await PersonalProfileRecord.update_or_create(
                key="current",
                defaults={
                    "revision": result.revision,
                    "data": result.model_dump(mode="json"),
                    "updated_at": result.updated_at,
                },
            )
            return result

    async def resolve_job(self, job_id: str, session_id: str | None) -> RecommendationItem:
        if session_id:
            record = self.sessions._get(session_id)
            recommendation = self.sessions._response(record).recommendation
            if recommendation:
                for item in [*recommendation.jobs, *recommendation.pending_jobs]:
                    if item.job.job_id == job_id:
                        return item
            published = record.state.get("published_jobs", {}).get(job_id)
            if published:
                return RecommendationItem.model_validate(published)
            for job in record.state.get("normalized_jobs", []):
                if job.job_id == job_id:
                    return RecommendationItem(job=job)
            prior = await TaskJobFeedbackRecord.get_or_none(session_id=session_id, job_id=job_id)
            if prior:
                return TaskJobFeedback.model_validate(prior.data).item
            raise SessionOperationError(
                404, "Job not found in this task.", code="saved_job_not_found"
            )
        saved = await SavedJob.get_or_none(job_id=job_id)
        if saved:
            return RecommendationItem.model_validate(saved.item)
        tracked = await JobApplicationRecord.get_or_none(job_id=job_id)
        if tracked:
            return JobApplication.model_validate(tracked.data).item
        feedback = await TaskJobFeedbackRecord.filter(job_id=job_id).first()
        if feedback:
            return TaskJobFeedback.model_validate(feedback.data).item
        raise SessionOperationError(404, "Job not found.", code="saved_job_not_found")

    async def import_profile(self, session_id: str, expected_revision: int) -> PersonalProfile:
        record = self.sessions._get(session_id)
        profile = self.sessions._response(record).profile
        if profile is None:
            raise SessionOperationError(422, "This task has no normalized profile yet.")
        from jobscout.schemas.career import Background
        from jobscout.schemas.session import ResumeInput

        inputs = record.state.get("input_data", {})
        return await self.save_profile(
            ProfileWrite(
                expected_revision=expected_revision,
                description=inputs.get("description", ""),
                resume=ResumeInput.model_validate(inputs["resume"])
                if inputs.get("resume")
                else None,
                background=Background.model_validate(
                    profile.model_dump(include={"education", "skills", "internships", "projects"})
                ),
                documents=record.state.get("profile_documents", []),
            )
        )

    async def feedback(self, session_id: str, job_id: str) -> TaskJobFeedback:
        self.sessions._get(session_id)
        record = await TaskJobFeedbackRecord.get_or_none(session_id=session_id, job_id=job_id)
        if record:
            return TaskJobFeedback.model_validate(record.data)
        return TaskJobFeedback(
            session_id=session_id,
            job_id=job_id,
            item=await self.resolve_job(job_id, session_id),
            updated_at=datetime.now(UTC),
        )

    async def save_feedback(
        self, session_id: str, job_id: str, payload: FeedbackWrite
    ) -> TaskJobFeedback:
        async with self.sessions.lock:
            self.sessions._get(session_id)
            result = TaskJobFeedback(
                **payload.model_dump(),
                session_id=session_id,
                job_id=job_id,
                item=await self.resolve_job(job_id, session_id),
                updated_at=datetime.now(UTC),
            )
            await TaskJobFeedbackRecord.update_or_create(
                session_id=session_id,
                job_id=job_id,
                defaults={"data": result.model_dump(mode="json")},
            )
            return result

    async def applications(self) -> list[JobApplication]:
        return [JobApplication.model_validate(r.data) for r in await JobApplicationRecord.all()]

    async def application(self, job_id: str) -> JobApplication:
        record = await JobApplicationRecord.get_or_none(job_id=job_id)
        if record:
            return JobApplication.model_validate(record.data)
        now = datetime.now(UTC)
        return JobApplication(
            job_id=job_id,
            stage="not_applied",
            note="",
            item=await self.resolve_job(job_id, None),
            created_at=now,
            updated_at=now,
            history=[],
        )

    async def save_application(self, job_id: str, payload: ApplicationWrite) -> JobApplication:
        async with self.sessions.lock, in_transaction():
            record = await JobApplicationRecord.get_or_none(job_id=job_id)
            now = datetime.now(UTC)
            previous = JobApplication.model_validate(record.data) if record else None
            item = previous.item if previous else await self.resolve_job(job_id, payload.session_id)
            history = list(previous.history) if previous else []
            if not previous or (previous.stage, previous.note) != (payload.stage, payload.note):
                history.append(
                    ApplicationTransition(stage=payload.stage, note=payload.note, changed_at=now)
                )
            result = JobApplication(
                job_id=job_id,
                stage=payload.stage,
                note=payload.note,
                item=item,
                created_at=previous.created_at if previous else now,
                updated_at=now,
                history=history,
            )
            await JobApplicationRecord.update_or_create(
                job_id=job_id, defaults={"data": result.model_dump(mode="json")}
            )
            return result

    def task(self, session_id: str) -> TaskMetadata:
        record = self.sessions._get(session_id)
        profile = self.sessions._response(record).profile
        return TaskMetadata(
            session_id=session_id,
            title=record.state.get("task_title", "Job search"),
            profile_revision=record.state.get("profile_revision"),
            preferences=profile.preferences if profile else ProfilePreferences(),
            target_directions=profile.target_directions if profile else [],
        )

    async def rename_task(self, session_id: str, title: str) -> TaskMetadata:
        async with self.sessions.lock:
            record = self.sessions._get(session_id)
            record.state["task_title"] = title
            await self.sessions._persist(record)
            return self.task(session_id)
