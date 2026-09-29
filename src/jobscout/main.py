"""FastAPI application entry point."""

from fastapi import FastAPI

from jobscout.api.sessions import router as sessions_router
from jobscout.database import database_lifespan


def create_app() -> FastAPI:
    app = FastAPI(title="JobScout API", lifespan=database_lifespan)
    app.include_router(sessions_router)
    return app


app = create_app()
