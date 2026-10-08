"""Assemble an offline application: uvicorn jobscout.replay.app:app."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI

from jobscout.main import create_app
from jobscout.replay.dataset import DEFAULT_DATASET, load_dataset
from jobscout.replay.provider import ReplayProvider
from jobscout.replay.search import ReplaySearchService


def create_replay_app(
    *,
    dataset_path: Path = DEFAULT_DATASET,
    provider: Any = None,
    search_service: Any = None,
    database_url: str | None = None,
) -> FastAPI:
    dataset = load_dataset(dataset_path)
    return create_app(
        provider=provider if provider is not None else ReplayProvider(dataset),
        search_service=search_service
        if search_service is not None
        else ReplaySearchService(dataset),
        mode="replay",
        database_url=database_url,
        temporary_database=True,
    )


app = create_replay_app()
