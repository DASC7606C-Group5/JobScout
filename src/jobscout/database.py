"""Database lifecycle and Tortoise ORM configuration."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from tortoise import Tortoise
from tortoise.backends.base.config_generator import expand_db_url

from jobscout.config import get_settings


def sqlite_path(database_url: str) -> str:
    if not database_url.startswith("sqlite://"):
        raise ValueError("The shared workspace requires a SQLite database URL.")
    return str(expand_db_url(database_url)["credentials"]["file_path"])


def tortoise_config(database_url: str | None = None) -> dict[str, object]:
    return {
        "connections": {"default": database_url or get_settings().database_url},
        "apps": {
            "models": {
                "models": ["jobscout.models"],
                "default_connection": "default",
            }
        },
        "use_tz": True,
        "timezone": "UTC",
    }


@asynccontextmanager
async def database_lifespan(_: FastAPI, *, database_url: str | None = None) -> AsyncGenerator[None]:
    await Tortoise.init(config=tortoise_config(database_url))
    await Tortoise.generate_schemas(safe=True)
    try:
        yield
    finally:
        await Tortoise.close_connections()
