"""Keep every HTTP test's workspace and checkpoints outside the development database."""

from collections.abc import Generator
from pathlib import Path

import pytest

from jobscout.config import get_settings


@pytest.fixture(autouse=True)
def isolated_workspace_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite://{(tmp_path / 'workspace.sqlite3').as_posix()}")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
