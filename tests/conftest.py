"""Keep every HTTP test's workspace and checkpoints outside the development database."""

from collections.abc import Generator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from jobscout.config import get_settings
from jobscout.services.identity import current_user_id


@pytest.fixture(autouse=True)
def isolated_workspace_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite://{(tmp_path / 'workspace.sqlite3').as_posix()}")
    monkeypatch.setenv("REGISTRATION_CODE", "synthetic-class-code")
    monkeypatch.setenv("CREDENTIALS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PRODUCTION", "false")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    identity_token = current_user_id.set("workflow-owner")
    get_settings.cache_clear()
    yield
    current_user_id.reset(identity_token)
    get_settings.cache_clear()
