"""FastAPI entry point with application-scoped clients and cancellable sessions."""

import asyncio
import inspect
import os
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from jobscout.api.auth import router as auth_router
from jobscout.api.resumes import router as resumes_router
from jobscout.api.security import SecurityMiddleware
from jobscout.api.sessions import router as sessions_router
from jobscout.api.settings import router as settings_router
from jobscout.api.workspace import router as workspace_router
from jobscout.config import get_settings
from jobscout.database import database_lifespan, encrypt_existing_resume_data, sqlite_path
from jobscout.services.auth_service import AuthService
from jobscout.services.encryption import ProfileDocumentCipher
from jobscout.services.model_settings_service import ModelSettingsService
from jobscout.services.notice_service import public_error
from jobscout.services.session_service import SessionService
from jobscout.services.workspace_service import WorkspaceService


async def close_resource(resource: Any) -> None:
    result = resource.aclose()
    if inspect.isawaitable(result):
        await result


def create_app(
    *,
    provider: Any = None,
    search_service: Any = None,
    graph: Any = None,
    mode: str = "live",
    database_url: str | None = None,
    temporary_database: bool = False,
) -> FastAPI:
    active_mode = mode
    if active_mode not in {"live", "replay"}:
        raise ValueError("mode must be live or replay")

    if active_mode == "replay" and graph is None and (provider is None or search_service is None):
        raise ValueError("Replay mode requires injected model and search services")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
        settings = get_settings()
        profile_cipher = ProfileDocumentCipher(settings.credentials_key.get_secret_value())
        active_provider = provider
        active_search = search_service
        active_database_url = database_url or get_settings().database_url
        async with AsyncExitStack() as stack:
            resources: set[int] = set()

            def own_resource(resource: Any) -> None:
                if (
                    resource is not None
                    and hasattr(resource, "aclose")
                    and id(resource) not in resources
                ):
                    resources.add(id(resource))
                    stack.push_async_callback(close_resource, resource)

            own_resource(active_provider)
            own_resource(active_search)
            if temporary_database and database_url is None and not os.environ.get("DATABASE_URL"):
                workspace_directory = stack.enter_context(
                    TemporaryDirectory(prefix="jobscout-workspace-")
                )
                active_database_url = (
                    f"sqlite://{(Path(workspace_directory) / 'workspace.sqlite3').as_posix()}"
                )
            await run_in_threadpool(
                encrypt_existing_resume_data, active_database_url, profile_cipher
            )
            await stack.enter_async_context(
                database_lifespan(application, database_url=active_database_url)
            )
            application.state.database_url = active_database_url
            application.state.auth = AuthService(settings)
            await application.state.auth.open()
            application.state.resume_slots = asyncio.Semaphore(2)
            application.state.model_settings = ModelSettingsService(settings)
            checkpointer: Any = getattr(graph, "checkpointer", None)
            if checkpointer is None:
                from jobscout.graph.encrypted_saver import EncryptedSqliteSaver

                checkpointer = await stack.enter_async_context(
                    EncryptedSqliteSaver.connect_encrypted(
                        sqlite_path(active_database_url), profile_cipher
                    )
                )
                # A read initializes the official saver's tables without creating a checkpoint.
                await checkpointer.aget_tuple({"configurable": {"thread_id": "__setup__"}})
            active_graph = graph
            if active_graph is None:
                from jobscout.graph.live import build_live_graph
                from jobscout.services.llm_service import get_llm_provider

                active_provider = active_provider or get_llm_provider()
                own_resource(active_provider)
                active_graph = build_live_graph(
                    checkpointer=checkpointer,
                    provider=active_provider,
                    search_service=active_search,
                )
            application.state.checkpointer = checkpointer
            application.state.graph = active_graph
            application.state.sessions = SessionService(
                active_graph,
                checkpointer,
                mode=active_mode,
                model_settings=application.state.model_settings
                if active_mode == "live" and graph is None and provider is None
                else None,
                profile_cipher=profile_cipher,
                graph_factory=(
                    lambda model: build_live_graph(
                        checkpointer=checkpointer, provider=model, search_service=active_search
                    )
                )
                if active_mode == "live" and graph is None and provider is None
                else None,
            )
            stack.push_async_callback(application.state.sessions.close)
            await application.state.sessions.open()
            application.state.workspace = WorkspaceService(
                application.state.sessions, profile_cipher=profile_cipher
            )
            yield

    settings = get_settings()
    application = FastAPI(
        title="JobScout API",
        lifespan=lifespan,
        docs_url=None if settings.production else "/docs",
        redoc_url=None if settings.production else "/redoc",
        openapi_url=None if settings.production else "/openapi.json",
    )
    application.add_middleware(SecurityMiddleware)

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
    application.include_router(auth_router)
    application.include_router(settings_router)
    frontend = Path(settings.frontend_directory).resolve()
    if (frontend / "assets").is_dir():
        application.mount("/assets", StaticFiles(directory=frontend / "assets"))

    @application.get("/{path:path}", include_in_schema=False)
    async def frontend_page(path: str) -> FileResponse:
        if (
            path.startswith("api/")
            or path in {"docs", "redoc", "openapi.json"}
            or not (frontend / "index.html").is_file()
        ):
            raise HTTPException(404, {"code": "not_found"})
        return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-cache"})

    return application


app = create_app()
