"""HTTP routes for service health and workflow sessions."""

from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status

from jobscout.graph.runner import run_workflow
from jobscout.schemas.session import (
    SessionCreateRequest,
    SessionResponse,
    SessionResumeRequest,
)

router = APIRouter(prefix="/api/v1", tags=["session"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


def _session_snapshot(request: Request, session_id: str) -> Any:
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": session_id}}
    snapshot = graph.get_state(config)
    if snapshot.values.get("session_id") != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return snapshot


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(request: Request, payload: SessionCreateRequest) -> SessionResponse:
    session_id = str(uuid4())
    result = run_workflow(
        graph=request.app.state.graph,
        session_id=session_id,
        input_data=payload.model_dump(),
    )
    return SessionResponse(
        session_id=session_id,
        outcome=result["outcome"],
        state=result["state"],
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(request: Request, session_id: str) -> SessionResponse:
    snapshot = _session_snapshot(request, session_id)
    state = snapshot.values
    outcome: Literal["paused", "completed", "failed"]
    if state.get("current_stage") == "failed":
        outcome = "failed"
    elif state.get("current_stage") == "completed":
        outcome = "completed"
    else:
        outcome = "paused"
    return SessionResponse(session_id=session_id, outcome=outcome, state=state)


@router.post("/sessions/{session_id}/resume", response_model=SessionResponse)
async def resume_session(
    request: Request,
    session_id: str,
    payload: SessionResumeRequest,
) -> SessionResponse:
    snapshot = _session_snapshot(request, session_id)
    if snapshot.next != ("clarify",):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session is not waiting for clarification",
        )

    result = run_workflow(
        graph=request.app.state.graph,
        session_id=session_id,
        answers=cast(dict[str, object], payload.answers),
    )
    return SessionResponse(
        session_id=session_id,
        outcome=result["outcome"],
        state=result["state"],
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(request: Request, session_id: str) -> Response:
    _session_snapshot(request, session_id)
    request.app.state.checkpointer.delete_thread(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
