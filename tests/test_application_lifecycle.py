"""Application clients close even when startup or another cleanup step fails."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from jobscout.main import create_app
from jobscout.services.session_service import SessionService
from tests.test_session_operations import ControlledGraph


@pytest.mark.parametrize("failure", ["session_open", "session_close", "provider", "search"])
def test_all_clients_close_on_lifecycle_failure(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = RuntimeError("synthetic lifecycle failure")
    provider = SimpleNamespace(
        aclose=AsyncMock(side_effect=error if failure == "provider" else None)
    )
    search = SimpleNamespace(aclose=AsyncMock(side_effect=error if failure == "search" else None))
    if failure.startswith("session_"):
        monkeypatch.setattr(
            SessionService, failure.removeprefix("session_"), AsyncMock(side_effect=error)
        )
    application = create_app(provider=provider, search_service=search, graph=ControlledGraph())
    with pytest.raises(RuntimeError, match="synthetic lifecycle failure"):
        with TestClient(application):
            pass
    provider.aclose.assert_awaited_once()
    search.aclose.assert_awaited_once()


def test_graph_startup_failure_closes_supplied_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = SimpleNamespace(aclose=AsyncMock())
    search = SimpleNamespace(aclose=AsyncMock())

    def unavailable_graph(**_kwargs: object) -> None:
        raise RuntimeError("synthetic graph failure")

    monkeypatch.setattr("jobscout.graph.live.build_live_graph", unavailable_graph)
    with pytest.raises(RuntimeError, match="synthetic graph failure"):
        with TestClient(create_app(provider=provider, search_service=search)):
            pass
    provider.aclose.assert_awaited_once()
    search.aclose.assert_awaited_once()
