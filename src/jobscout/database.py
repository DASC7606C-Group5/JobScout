"""Database lifecycle and Tortoise ORM configuration."""

import sqlite3
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

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
    path = sqlite_path(database_url or get_settings().database_url)
    if path != ":memory:" and Path(path).is_file():
        with sqlite3.connect(path) as connection:
            columns = connection.execute("PRAGMA table_info(workspace_sessions)").fetchall()
            if columns and "owner_id" not in {column[1] for column in columns}:
                raise ValueError(
                    "This database contains a shared workspace. Use a new DATABASE_URL; existing private data is not migrated."
                )
    await Tortoise.init(config=tortoise_config(database_url))
    await Tortoise.generate_schemas(safe=True)
    try:
        yield
    finally:
        await Tortoise.close_connections()
