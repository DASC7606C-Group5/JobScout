"""FastAPI entry point with application-scoped clients and cancellable sessions."""

import inspect
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langgraph.checkpoint.memory import InMemorySaver

from jobscout.api.resumes import router as resumes_router
from jobscout.api.sessions import router as sessions_router
from jobscout.database import database_lifespan
from jobscout.services.notice_service import public_error
from jobscout.services.session_service import SessionService


def create_app(
    *,
    provider: Any = None,
    search_service: Any = None,
    graph: Any = None,
    mode: str | None = None,
) -> FastAPI:
    active_mode = mode or os.environ.get("JOBSCOUT_MODE", "live")
    if active_mode not in {"live", "replay"}:
        raise ValueError("JOBSCOUT_MODE must be live or replay")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        active_provider = provider
        active_search = search_service
        if active_mode == "replay" and graph is None:
            from jobscout.services.replay_service import ReplayProvider, ReplaySearchService

            active_provider = active_provider or ReplayProvider()
            active_search = active_search or ReplaySearchService()
        checkpointer = getattr(graph, "checkpointer", None) or InMemorySaver()
        active_graph = graph
        if active_graph is None:
            from jobscout.graph.live import build_live_graph
            from jobscout.services.llm_service import get_llm_provider

            active_provider = active_provider or get_llm_provider()
            active_graph = build_live_graph(
                checkpointer=checkpointer,
                provider=active_provider,
                search_service=active_search,
            )
        application.state.checkpointer = checkpointer
        application.state.graph = active_graph
        application.state.sessions = SessionService(active_graph, checkpointer, mode=active_mode)
        async with database_lifespan(application):
            try:
                yield
            finally:
                await application.state.sessions.close()
                for resource in (active_provider, active_search):
                    if resource is not None and hasattr(resource, "aclose"):
                        result = resource.aclose()
                        if inspect.isawaitable(result):
                            await result

    application = FastAPI(title="JobScout API", lifespan=lifespan)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request: Any, _error: RequestValidationError) -> JSONResponse:
        # Validation details can contain supplied input and private schema field names.
        return JSONResponse(
            status_code=422, content={"detail": public_error("invalid_input").model_dump()}
        )

    @application.exception_handler(Exception)
    async def unavailable_service(_request: Any, _error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500, content={"detail": public_error("service_unavailable").model_dump()}
        )

    application.include_router(resumes_router)
    application.include_router(sessions_router)
    return application


app = create_app()
