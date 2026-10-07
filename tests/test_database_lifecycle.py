"""Database startup failures release the SQLite connection and its worker thread."""

import asyncio

import aiosqlite
import pytest
from fastapi import FastAPI
from tortoise import Tortoise

from jobscout.database import database_lifespan


@pytest.mark.parametrize("cancelled", [False, True])
def test_schema_startup_failure_closes_database(
    cancelled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        opened: list[aiosqlite.Connection] = []
        failure = asyncio.CancelledError() if cancelled else OSError("Schema unavailable")

        async def fail_schema(*, safe: bool) -> None:
            async with Tortoise.get_connection("default").acquire_connection() as connection:
                opened.append(connection)
                await connection.execute("SELECT 1")
            raise failure

        monkeypatch.setattr(Tortoise, "generate_schemas", fail_schema)
        try:
            with pytest.raises(type(failure)) as raised:
                async with database_lifespan(FastAPI(), database_url="sqlite://:memory:"):
                    pytest.fail("Failed startup must not serve requests")
            assert raised.value is failure
            with pytest.raises(ValueError, match="no active connection"):
                await opened[0].execute("SELECT 1")
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
