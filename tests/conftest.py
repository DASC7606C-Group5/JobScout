"""Keep every HTTP test's workspace and checkpoints outside the development database."""

import asyncio
import shutil
from collections.abc import Generator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from fastapi import FastAPI

from jobscout.api import auth as auth_api
from jobscout.config import get_settings
from jobscout.database import database_lifespan
from jobscout.services import auth_service
from jobscout.services.identity import current_user_id

FAST_PASSWORD_HASHER = PasswordHasher(memory_cost=4096, time_cost=1, parallelism=1)


@pytest.fixture(scope="session")
def workspace_schema_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the Tortoise schema once per worker and copy it into each isolated workspace."""
    template = tmp_path_factory.mktemp("workspace-schema") / "template.sqlite3"

    async def build() -> None:
        async with database_lifespan(FastAPI(), database_url=f"sqlite://{template.as_posix()}"):
            pass

    asyncio.run(build())
    return template


@pytest.fixture(scope="session", autouse=True)
def fast_password_hashing() -> Generator[None]:
    """Use cheap Argon2id parameters so auth-heavy tests skip the production hashing cost."""
    production_auth_hasher = auth_service.PASSWORD_HASHER
    production_api_hasher = auth_api.PASSWORD_HASHER
    auth_service.PASSWORD_HASHER = FAST_PASSWORD_HASHER
    auth_api.PASSWORD_HASHER = FAST_PASSWORD_HASHER
    yield
    auth_service.PASSWORD_HASHER = production_auth_hasher
    auth_api.PASSWORD_HASHER = production_api_hasher


@pytest.fixture(autouse=True)
def isolated_workspace_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workspace_schema_template: Path,
) -> Generator[None]:
    workspace = tmp_path / "workspace.sqlite3"
    shutil.copyfile(workspace_schema_template, workspace)
    monkeypatch.setenv("DATABASE_URL", f"sqlite://{workspace.as_posix()}")
    monkeypatch.setenv("CREDENTIALS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PRODUCTION", "false")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    identity_token = current_user_id.set("workflow-owner")
    get_settings.cache_clear()
    yield
    current_user_id.reset(identity_token)
    get_settings.cache_clear()
