"""Database startup failures release the SQLite connection and its worker thread."""

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from tortoise import Tortoise

from jobscout.database import database_lifespan
from jobscout.models import DailyUsage, SearchSession, SessionOperation


def test_queue_migration_is_repeatable_and_preserves_existing_workspace(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    url = f"sqlite://{path.as_posix()}"

    async def seed() -> None:
        async with database_lifespan(FastAPI(), database_url=url):
            now = datetime.now(UTC)
            await SearchSession.create(
                owner_id="student",
                session_id="history",
                mode="live",
                state={"input_data": {"description": "Preserved applicant input"}},
                outcome="completed",
                thread_id="checkpoint",
                thread_ids=["checkpoint"],
                created_at=now,
                updated_at=now,
            )
            await DailyUsage.create(owner_id="student", day="2026-10-09", operations=3)

    asyncio.run(seed())
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE workspace_sessions DROP COLUMN snapshot_version")
        connection.execute("ALTER TABLE dailyusage DROP COLUMN reserved")
        connection.execute("DROP TABLE session_operations")

    async def verify() -> None:
        for _ in range(2):
            async with database_lifespan(FastAPI(), database_url=url):
                stored = await SearchSession.get(session_id="history")
                assert stored.state["input_data"]["description"] == "Preserved applicant input"
                assert stored.thread_ids == ["checkpoint"] and stored.snapshot_version == 0
                usage = await DailyUsage.get(owner_id="student", day="2026-10-09")
                assert (usage.operations, usage.reserved) == (3, 0)
                assert not await SessionOperation.exists()
                connection = Tortoise.get_connection("default")
                assert (await connection.execute_query_dict("PRAGMA journal_mode"))[0][
                    "journal_mode"
                ] == "wal"
                assert (await connection.execute_query_dict("PRAGMA busy_timeout"))[0][
                    "timeout"
                ] == 5000

    asyncio.run(verify())


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
