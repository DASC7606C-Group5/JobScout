"""FastAPI application entry point."""

from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver

from jobscout.api.resumes import router as resumes_router
from jobscout.api.sessions import router as sessions_router
from jobscout.database import database_lifespan
from jobscout.graph.builder import build_graph


def create_app() -> FastAPI:
    app = FastAPI(title="JobScout API", lifespan=database_lifespan)
    checkpointer = InMemorySaver()
    app.state.checkpointer = checkpointer
    app.state.graph = build_graph(checkpointer=checkpointer)
    app.include_router(resumes_router)
    app.include_router(sessions_router)
    return app


app = create_app()
