"""FastAPI entry point with application-scoped clients and cancellable sessions."""

import inspect
import os
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from jobscout.api.resumes import router as resumes_router
from jobscout.api.sessions import router as sessions_router
from jobscout.api.workspace import router as workspace_router
from jobscout.config import get_settings
from jobscout.database import database_lifespan, sqlite_path
from jobscout.graph.checkpoints import checkpoint_serializer
from jobscout.services.notice_service import public_error
from jobscout.services.session_service import SessionService
from jobscout.services.workspace_service import WorkspaceService


def create_app(
    *,
    provider: Any = None,
    search_service: Any = None,
    graph: Any = None,
    mode: str | None = None,
    database_url: str | None = None,
) -> FastAPI:
    active_mode = mode or os.environ.get("JOBSCOUT_MODE", "live")
    if active_mode not in {"live", "replay"}:
        raise ValueError("JOBSCOUT_MODE must be live or replay")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
        active_provider = provider
        active_search = search_service
        if active_mode == "replay" and graph is None:
            from jobscout.services.replay_service import ReplayProvider, ReplaySearchService

            active_provider = active_provider or ReplayProvider()
            active_search = active_search or ReplaySearchService()
        active_database_url = database_url or get_settings().database_url
        async with AsyncExitStack() as stack:
            if (
                active_mode == "replay"
                and database_url is None
                and not os.environ.get("DATABASE_URL")
            ):
                replay_directory = stack.enter_context(
                    TemporaryDirectory(prefix="jobscout-replay-")
                )
                active_database_url = (
                    f"sqlite://{(Path(replay_directory) / 'workspace.sqlite3').as_posix()}"
                )
            await stack.enter_async_context(
                database_lifespan(application, database_url=active_database_url)
            )
            checkpointer: Any = getattr(graph, "checkpointer", None)
            if checkpointer is None:
                checkpointer = await stack.enter_async_context(
                    AsyncSqliteSaver.from_conn_string(sqlite_path(active_database_url))
                )
                checkpointer.serde = checkpoint_serializer()
                # A read initializes the official saver's tables without creating a checkpoint.
                await checkpointer.aget_tuple({"configurable": {"thread_id": "__setup__"}})
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
            application.state.sessions = SessionService(
                active_graph, checkpointer, mode=active_mode
            )
            await application.state.sessions.open()
            application.state.workspace = WorkspaceService(application.state.sessions)
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
    application.include_router(workspace_router)
    return application


app = create_app()
