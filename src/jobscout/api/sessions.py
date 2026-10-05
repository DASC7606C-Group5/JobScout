"""HTTP routes expose accepted snapshots; operations run outside request lifetimes."""

from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response, status

from jobscout.schemas.session import SessionCreateRequest, SessionResponse, SessionResumeRequest
from jobscout.services.session_service import SessionOperationError, SessionService

router = APIRouter(prefix="/api/v1", tags=["session"])


def _service(request: Request) -> SessionService:
    return cast(SessionService, request.app.state.sessions)


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_session(request: Request, payload: SessionCreateRequest) -> SessionResponse:
    try:
        return await _service(request).create(payload)
    except SessionOperationError as error:
        raise HTTPException(error.status, error.detail) from error


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(request: Request, session_id: str) -> SessionResponse:
    try:
        return await _service(request).get(session_id)
    except SessionOperationError as error:
        raise HTTPException(error.status, error.detail) from error


@router.post(
    "/sessions/{session_id}/resume",
    response_model=SessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_session(
    request: Request,
    session_id: str,
    payload: SessionResumeRequest,
) -> SessionResponse:
    try:
        return await _service(request).resume(session_id, payload)
    except SessionOperationError as error:
        raise HTTPException(error.status, error.detail) from error


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(request: Request, session_id: str) -> Response:
    try:
        await _service(request).delete(session_id)
    except SessionOperationError as error:
        raise HTTPException(error.status, error.detail) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
