"""Database lifecycle and Tortoise ORM configuration."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from tortoise import Tortoise

from jobscout.config import get_settings


def tortoise_config() -> dict[str, object]:
    return {
        "connections": {"default": get_settings().database_url},
        "apps": {
            "models": {
                "models": [],
                "default_connection": "default",
            }
        },
        "use_tz": True,
        "timezone": "UTC",
    }


@asynccontextmanager
async def database_lifespan(_: FastAPI) -> AsyncIterator[None]:
    await Tortoise.init(config=tortoise_config())
    try:
        yield
    finally:
        await Tortoise.close_connections()
