"""Connection tests require the account's saved personal model for the requested role."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from replay.app import create_replay_app

from jobscout.api.settings import ConnectionResult
from jobscout.services.llm_service import LangChainModelProvider, ToolCall, ToolTurn
from jobscout.services.model_settings_service import OperationModels
from tests.test_account_security import register


@pytest.mark.parametrize("role", ["semantic", "decision"])
@pytest.mark.parametrize("server_key", ["", "synthetic-server-key"])
def test_server_connection_is_rejected_without_creating_provider_or_charging(
    role: str, server_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_replay_app()
    with TestClient(application) as client:
        register(client)
        setattr(application.state.model_settings.settings, f"llm_{role}_api_key", server_key)
        other_role = "decision" if role == "semantic" else "semantic"
        assert (
            client.put(
                f"/api/v1/settings/models/{other_role}",
                json={"endpoint_id": "openai", "model": "personal", "api_key": "personal-key"},
            ).status_code
            == 204
        )
        factory = Mock(side_effect=AssertionError("Server tests must not create a provider"))
        monkeypatch.setattr("jobscout.services.model_settings_service.get_llm_provider", factory)
        usage = client.get("/api/v1/settings/usage").json()
        response = client.post(f"/api/v1/settings/models/{role}/test")
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "personal_model_required"
        factory.assert_not_called()
        assert client.get("/api/v1/settings/usage").json() == usage
        assert not application.state.sessions.testing_users


@pytest.mark.parametrize("role", ["semantic", "decision"])
def test_personal_connection_works_and_clearing_it_disables_testing(
    role: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    structured = AsyncMock(return_value=ConnectionResult(ok=True))
    tool_turn = AsyncMock(
        return_value=ToolTurn(
            calls=[ToolCall(id="connection", name="check_connection", arguments={})]
        )
    )
    monkeypatch.setattr(LangChainModelProvider, "structured", structured)
    monkeypatch.setattr(LangChainModelProvider, "tool_turn", tool_turn)
    application = create_replay_app()
    with TestClient(application) as client:
        register(client)
        assert (
            client.put(
                f"/api/v1/settings/models/{role}",
                json={"endpoint_id": "openai", "model": "personal", "api_key": "personal-key"},
            ).status_code
            == 204
        )
        usage = client.get("/api/v1/settings/usage").json()
        response = client.post(f"/api/v1/settings/models/{role}/test")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        structured.assert_awaited_once()
        if role == "decision":
            tool_turn.assert_awaited_once()
        else:
            tool_turn.assert_not_awaited()
        assert client.get("/api/v1/settings/usage").json() == usage
        assert not application.state.sessions.testing_users
        assert client.delete(f"/api/v1/settings/models/{role}").status_code == 204
        response = client.post(f"/api/v1/settings/models/{role}/test")
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "personal_model_required"
        structured.assert_awaited_once()


def test_capacity_rejection_closes_models_without_releasing_another_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_replay_app()
    with TestClient(application) as client:
        account = register(client)
        router = Mock()
        router.aclose = AsyncMock()
        router.semantic.structured = AsyncMock()
        prepared = AsyncMock(return_value=OperationModels(provider=router, uses_server=False))
        monkeypatch.setattr(application.state.model_settings, "prepare", prepared)
        application.state.sessions.model_settings = application.state.model_settings
        application.state.sessions.testing_users.add(account["user_id"])
        response = client.post("/api/v1/settings/models/semantic/test")
        assert response.status_code == 429
        assert response.json()["detail"]["code"] == "operation_capacity"
        assert application.state.sessions.testing_users == {account["user_id"]}
        router.semantic.structured.assert_not_awaited()
        router.aclose.assert_awaited_once()
