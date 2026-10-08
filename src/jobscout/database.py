"""Database lifecycle and Tortoise ORM configuration."""

import logging
import sqlite3
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from tortoise import Tortoise
from tortoise.backends.base.config_generator import expand_db_url

from jobscout.config import get_settings

logger = logging.getLogger(__name__)


def sqlite_path(database_url: str) -> str:
    if not database_url.startswith("sqlite://"):
        raise ValueError("The shared workspace requires a SQLite database URL.")
    return str(expand_db_url(database_url)["credentials"]["file_path"])


def vacuum_sqlite(database_url: str) -> None:
    """Rebuild the SQLite file so deleted rows are not recoverable from free pages."""
    path = sqlite_path(database_url)
    if path == ":memory:" or not Path(path).is_file():
        return
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("VACUUM")
        connection.commit()
    except sqlite3.Error:
        logger.warning("database_vacuum_failed", exc_info=True)
    finally:
        connection.close()


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
            personal_columns = connection.execute("PRAGMA table_info(personalmodel)").fetchall()
            if personal_columns and "thinking_level" not in {
                column[1] for column in personal_columns
            }:
                connection.execute(
                    "ALTER TABLE personalmodel ADD COLUMN thinking_level "
                    "VARCHAR(32) NOT NULL DEFAULT 'high'"
                )
    await Tortoise.init(config=tortoise_config(database_url))
    try:
        await Tortoise.generate_schemas(safe=True)
        yield
    finally:
        await Tortoise.close_connections()
