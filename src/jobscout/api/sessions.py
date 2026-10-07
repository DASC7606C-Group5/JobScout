"""HTTP routes expose accepted snapshots; operations run outside request lifetimes."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from jobscout.schemas.session import (
    SessionCreateRequest,
    SessionResponse,
    SessionResumeRequest,
    SessionStopRequest,
)
from jobscout.schemas.workspace import SessionHistoryResponse
from jobscout.services.notice_service import public_error
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
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.get("/sessions", response_model=SessionHistoryResponse)
async def get_history(
    request: Request, cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)
) -> SessionHistoryResponse:
    try:
        return await _service(request).history(cursor=cursor, limit=limit)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(request: Request, session_id: str) -> SessionResponse:
    try:
        return await _service(request).get(session_id)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.get("/sessions/{session_id}/events")
async def session_events(request: Request, session_id: str) -> StreamingResponse:
    service = _service(request)
    try:
        queue = await service.subscribe(session_id)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error

    async def events() -> AsyncIterator[str]:
        identity = getattr(request.state, "identity", None)
        revoked = asyncio.create_task(identity.revoked.wait()) if identity is not None else None
        try:
            yield "retry: 1500\n\n"
            while True:
                if identity is not None and (
                    identity.revoked.is_set() or identity.session.expires_at <= datetime.now(UTC)
                ):
                    return
                received = asyncio.create_task(queue.get())
                try:
                    waiting = {received, revoked} if revoked is not None else {received}
                    timeout = (
                        min(
                            15,
                            max(
                                0, (identity.session.expires_at - datetime.now(UTC)).total_seconds()
                            ),
                        )
                        if identity is not None
                        else 15
                    )
                    done, _ = await asyncio.wait(
                        waiting, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                    )
                    if revoked is not None and revoked in done:
                        return
                    if received in done:
                        snapshot = received.result()
                    else:
                        snapshot = None
                finally:
                    received.cancel()
                    await asyncio.gather(received, return_exceptions=True)
                if received not in done:
                    yield ": heartbeat\n\n"
                    continue
                if snapshot is None:
                    return
                yield f"event: snapshot\ndata: {snapshot.model_dump_json()}\n\n"
                if snapshot.outcome != "running":
                    return
        finally:
            if revoked is not None:
                revoked.cancel()
                await asyncio.gather(revoked, return_exceptions=True)
            service.unsubscribe(session_id, queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


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
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.post("/sessions/{session_id}/stop", response_model=SessionResponse)
async def stop_session(
    request: Request, session_id: str, payload: SessionStopRequest
) -> SessionResponse:
    try:
        return await _service(request).stop(session_id, payload)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(request: Request, session_id: str) -> Response:
    try:
        await _service(request).delete(session_id)
    except SessionOperationError as error:
        raise HTTPException(error.status, public_error(error.code).model_dump()) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
