"""Profile, task feedback and application endpoints."""

from typing import cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from jobscout.schemas.career import (
    ApplicationWrite,
    FeedbackWrite,
    JobApplication,
    PersonalProfile,
    ProfileWrite,
    TaskJobFeedback,
    TaskMetadata,
)
from jobscout.services.career_service import CareerService, load_current_profile, load_task_feedback
from jobscout.services.notice_service import public_error
from jobscout.services.session_service import SessionOperationError

router = APIRouter(prefix="/api/v1", tags=["career"])


def service(request: Request) -> CareerService:
    return cast(CareerService, request.app.state.career)


class TaskTitleWrite(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ProfileImportWrite(BaseModel):
    session_id: str
    expected_revision: int = Field(ge=0)


@router.put("/profile/from-session")
async def import_profile(request: Request, payload: ProfileImportWrite) -> PersonalProfile:
    try:
        return await service(request).import_profile(payload.session_id, payload.expected_revision)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.get("/profile")
async def profile() -> PersonalProfile:
    return await load_current_profile()


@router.put("/profile")
async def save_profile(request: Request, payload: ProfileWrite) -> PersonalProfile:
    try:
        return await service(request).save_profile(payload)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.get("/sessions/{session_id}/task")
async def task(request: Request, session_id: str) -> TaskMetadata:
    try:
        return service(request).task(session_id)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.put("/sessions/{session_id}/task")
async def rename_task(request: Request, session_id: str, payload: TaskTitleWrite) -> TaskMetadata:
    try:
        return await service(request).rename_task(session_id, payload.title)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.get("/sessions/{session_id}/feedback")
async def feedback_list(request: Request, session_id: str) -> list[TaskJobFeedback]:
    try:
        service(request).sessions._get(session_id)
        return await load_task_feedback(session_id)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.get("/sessions/{session_id}/feedback/{job_id:path}")
async def feedback(request: Request, session_id: str, job_id: str) -> TaskJobFeedback:
    try:
        return await service(request).feedback(session_id, job_id)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.put("/sessions/{session_id}/feedback/{job_id:path}")
async def save_feedback(
    request: Request, session_id: str, job_id: str, payload: FeedbackWrite
) -> TaskJobFeedback:
    try:
        return await service(request).save_feedback(session_id, job_id, payload)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.get("/applications")
async def applications(request: Request) -> list[JobApplication]:
    return await service(request).applications()


@router.get("/applications/{job_id:path}")
async def application(request: Request, job_id: str) -> JobApplication:
    try:
        return await service(request).application(job_id)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.put("/applications/{job_id:path}")
async def save_application(
    request: Request, job_id: str, payload: ApplicationWrite
) -> JobApplication:
    try:
        return await service(request).save_application(job_id, payload)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error
