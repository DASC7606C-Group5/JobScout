"""Database lifecycle and Tortoise ORM configuration."""

import json
import logging
import sqlite3
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from tortoise import Tortoise
from tortoise.backends.base.config_generator import expand_db_url

from jobscout.config import get_settings
from jobscout.services.encryption import ProfileDocumentCipher

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
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        logger.warning("database_vacuum_failed", exc_info=True)
    finally:
        connection.close()


def encrypt_existing_resume_data(database_url: str, cipher: ProfileDocumentCipher) -> None:
    """Migrate existing plaintext before the application accepts requests."""
    path = sqlite_path(database_url)
    if path == ":memory:" or not Path(path).is_file():
        return
    changed = False
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(f"PRAGMA busy_timeout={get_settings().sqlite_busy_timeout_ms}")
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS workspace_migrations "
            "(name TEXT PRIMARY KEY, verification TEXT NOT NULL)"
        )
        migrated = connection.execute(
            "SELECT verification FROM workspace_migrations WHERE name='encrypted_documents_v1'"
        ).fetchone()
        if migrated is not None:
            if cipher.decrypt(migrated[0]) != "encrypted_documents_v1":
                raise ValueError("The stored document encryption key could not be verified.")
            return
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        for table, column in (("workspace_sessions", "state"), ("workspace_drafts", "data")):
            if table not in tables:
                continue
            for rowid, serialized in connection.execute(f"SELECT rowid, {column} FROM {table}"):
                data = json.loads(serialized)
                values = [data] if table == "workspace_drafts" else [data.get("input_data", {})]
                texts = [
                    value["resume"] for value in values if isinstance(value.get("resume"), dict)
                ]
                if table == "workspace_sessions":
                    texts.extend(data.get("profile_documents", []))
                updated = False
                for item in texts:
                    text = item.get("text")
                    if not isinstance(text, str):
                        continue
                    if text.startswith("enc:v1:"):
                        cipher.decrypt(text)  # Fail startup if the existing key no longer works.
                    else:
                        item["text"] = cipher.encrypt(text)
                        updated = True
                if updated:
                    connection.execute(
                        f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                        (json.dumps(data, ensure_ascii=False), rowid),
                    )
                    changed = True
        for table, column in (("checkpoints", "checkpoint"), ("writes", "value")):
            if table not in tables:
                continue
            for rowid, kind, value in connection.execute(
                f"SELECT rowid, type, {column} FROM {table}"
            ):
                if "+" in kind:
                    if not kind.endswith("+fernet"):
                        raise ValueError("Unsupported checkpoint cipher")
                    cipher.decrypt_bytes(value)
                    continue
                connection.execute(
                    f"UPDATE {table} SET type = ?, {column} = ? WHERE rowid = ?",
                    (f"{kind}+fernet", cipher.encrypt_bytes(value), rowid),
                )
                changed = True
        connection.execute(
            "INSERT INTO workspace_migrations (name, verification) VALUES (?, ?)",
            ("encrypted_documents_v1", cipher.encrypt("encrypted_documents_v1")),
        )
    if changed:
        vacuum_sqlite(database_url)


def tortoise_config(database_url: str | None = None) -> dict[str, object]:
    database = expand_db_url(database_url or get_settings().database_url)
    database["credentials"].update(
        journal_mode="WAL", busy_timeout=get_settings().sqlite_busy_timeout_ms
    )
    return {
        "connections": {"default": database},
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
            for table, name in (
                ("workspace_sessions", "snapshot_version"),
                ("dailyusage", "reserved"),
            ):
                existing = connection.execute(f"PRAGMA table_info({table})").fetchall()
                if existing and name not in {column[1] for column in existing}:
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} INT NOT NULL DEFAULT 0"
                    )
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
