"""Shared workspace draft and favorite endpoints."""

from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Request, Response, status

from jobscout.schemas.recommendation import RecommendationItem
from jobscout.schemas.workspace import (
    DraftResponse,
    DraftWriteRequest,
    SavedJobsResponse,
    SaveJobRequest,
)
from jobscout.services.notice_service import public_error
from jobscout.services.session_service import SessionOperationError
from jobscout.services.workspace_service import DraftSection, WorkspaceService

router = APIRouter(prefix="/api/v1", tags=["workspace"])


def _service(request: Request) -> WorkspaceService:
    return cast(WorkspaceService, request.app.state.workspace)


@router.get("/workspace/draft", response_model=DraftResponse)
async def get_workspace_draft(request: Request) -> DraftResponse:
    return await _service(request).get_draft()


@router.put("/workspace/draft", response_model=DraftResponse)
async def save_workspace_draft(request: Request, payload: DraftWriteRequest) -> DraftResponse:
    try:
        return await _service(request).save_draft(payload)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.get("/sessions/{session_id}/drafts/{revision}/{section}", response_model=DraftResponse)
async def get_session_draft(
    request: Request,
    session_id: str,
    revision: Annotated[int, Path(ge=0)],
    section: DraftSection,
) -> DraftResponse:
    try:
        return await _service(request).get_draft(
            session_id=session_id, session_revision=revision, section=section
        )
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.put("/sessions/{session_id}/drafts/{revision}/{section}", response_model=DraftResponse)
async def save_session_draft(
    request: Request,
    session_id: str,
    revision: Annotated[int, Path(ge=0)],
    section: DraftSection,
    payload: DraftWriteRequest,
) -> DraftResponse:
    try:
        return await _service(request).save_draft(
            payload, session_id=session_id, session_revision=revision, section=section
        )
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.get("/saved-jobs", response_model=SavedJobsResponse)
async def get_saved_jobs(request: Request) -> SavedJobsResponse:
    return await _service(request).saved_jobs()


@router.put("/saved-jobs/{job_id:path}", response_model=RecommendationItem)
async def save_job(request: Request, job_id: str, payload: SaveJobRequest) -> RecommendationItem:
    try:
        return await _service(request).save_job(job_id, payload)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.delete("/saved-jobs/{job_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def unsave_job(request: Request, job_id: str) -> Response:
    await _service(request).unsave_job(job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
