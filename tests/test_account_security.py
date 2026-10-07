"""Account boundaries, credentials, allowances and operation configuration snapshots."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from replay.app import create_replay_app
from tortoise import Tortoise

from jobscout.config import Settings, get_settings
from jobscout.database import tortoise_config
from jobscout.manage import backup_database
from jobscout.services.auth_service import PASSWORD_HASHER
from jobscout.services.identity import current_user_id
from jobscout.services.llm_service import LangChainModelProvider
from jobscout.services.model_settings_service import ModelSettingsService
from jobscout.services.session_service import SessionService
from tests.test_session_operations import ControlledGraph, Memory, create_payload
from tests.test_web_scaffold import settled
from tests.test_workspace_persistence import CREATE, RAW_DRAFT


def register(client: TestClient, username: str = "student") -> dict[str, Any]:
    client.headers["Origin"] = get_settings().public_origin
    result = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "synthetic-password-123",
            "registration_code": "synthetic-class-code",
        },
    )
    assert result.status_code == 201, result.text
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return result.json()  # type: ignore[no-any-return]


def test_private_routes_require_login_and_writes_require_origin_and_csrf() -> None:
    with TestClient(create_replay_app()) as client:
        for method, path in [
            ("GET", "/api/v1/sessions"),
            ("GET", "/api/v1/sessions/private/events"),
            ("PUT", "/api/v1/workspace/draft"),
            ("GET", "/api/v1/saved-jobs"),
            ("POST", "/api/v1/resumes/parse"),
            ("GET", "/api/v1/settings/models"),
        ]:
            response = client.request(method, path)
            assert response.status_code == 401
            assert response.json()["detail"]["code"] == "authentication_required"
        client.headers["Origin"] = "https://attacker.example"
        response = client.post(
            "/api/v1/auth/login", json={"username": "student", "password": "synthetic-password-123"}
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "invalid_origin"
        register(client)
        client.headers.pop("X-CSRF-Token")
        response = client.put(
            "/api/v1/workspace/draft",
            json={"request_id": "draft", "expected_revision": 0, "data": {}},
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "invalid_csrf_token"


def test_registration_hashes_password_and_normalizes_username(tmp_path: Path) -> None:
    database = tmp_path / "accounts.sqlite3"
    with TestClient(create_replay_app(database_url=f"sqlite://{database.as_posix()}")) as client:
        account = register(client, "Student")
        assert account["username"] == "student"
        cookie = client.cookies.get("jobscout_session")
        assert cookie is not None
        assert (
            "HttpOnly"
            in client.post(
                "/api/v1/auth/login",
                json={"username": "STUDENT", "password": "synthetic-password-123"},
            ).headers["set-cookie"]
        )
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "student",
                "password": "synthetic-password-123",
                "registration_code": "synthetic-class-code",
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "username_unavailable"
        wrong = client.post(
            "/api/v1/auth/register",
            json={
                "username": "other",
                "password": "synthetic-password-123",
                "registration_code": "incorrect",
            },
        )
        assert wrong.status_code == 403
    with sqlite3.connect(database) as connection:
        hashed = connection.execute('SELECT password_hash FROM "user"').fetchone()[0]
        assert hashed.startswith("$argon2id$v=19$m=65536,t=3,p=1$")
        assert PASSWORD_HASHER.verify(hashed, "synthetic-password-123")
        assert (
            connection.execute(
                "SELECT token_hash FROM loginsession WHERE token_hash = ?", [cookie]
            ).fetchall()
            == []
        )


def test_login_failure_is_uniform_and_throttled() -> None:
    with TestClient(create_replay_app()) as client:
        register(client)
        unknown = client.post(
            "/api/v1/auth/login", json={"username": "unknown", "password": "incorrect-password"}
        )
        known = client.post(
            "/api/v1/auth/login", json={"username": "student", "password": "incorrect-password"}
        )
        assert known.status_code == unknown.status_code == 401
        assert known.json() == unknown.json() == {"detail": {"code": "invalid_credentials"}}
        for _ in range(9):
            assert (
                client.post(
                    "/api/v1/auth/login",
                    json={"username": "student", "password": "incorrect-password"},
                ).status_code
                == 401
            )
        blocked = client.post(
            "/api/v1/auth/login", json={"username": "student", "password": "synthetic-password-123"}
        )
        assert blocked.status_code == 429
        assert blocked.json()["detail"]["code"] == "auth_rate_limited"


def test_password_change_and_logout_revoke_sessions_and_event_listeners() -> None:
    application = create_replay_app()
    with TestClient(application) as first:
        account = register(first)
        second = TestClient(application)
        second.portal = first.portal
        second.headers["Origin"] = get_settings().public_origin
        login = second.post(
            "/api/v1/auth/login", json={"username": "student", "password": "synthetic-password-123"}
        )
        second.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        portal = first.portal
        assert portal is not None
        identity = portal.call(
            application.state.auth.identity, first.cookies.get("jobscout_session")
        )
        portal.call(application.state.auth.listen, identity)
        expired = portal.call(
            application.state.auth.identity, second.cookies.get("jobscout_session")
        )

        async def expire() -> None:
            expired.session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await expired.session.save()

        portal.call(expire)
        assert second.get("/api/v1/auth/me").status_code == 401
        changed = first.post(
            "/api/v1/auth/password",
            json={
                "current_password": "synthetic-password-123",
                "new_password": "changed-password-123",
            },
        )
        assert changed.status_code == 204
        assert identity.revoked.is_set()
        assert first.get("/api/v1/auth/me").status_code == 401
        wrong = second.post(
            "/api/v1/auth/login", json={"username": "student", "password": "synthetic-password-123"}
        )
        assert wrong.status_code == 401
        login = second.post(
            "/api/v1/auth/login", json={"username": "student", "password": "changed-password-123"}
        )
        second.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        assert login.json()["user_id"] == account["user_id"]
        assert second.post("/api/v1/auth/logout").status_code == 204
        assert second.get("/api/v1/auth/me").status_code == 401


def test_accounts_have_independent_searches_drafts_saved_jobs_and_request_ids() -> None:
    application = create_replay_app()
    with TestClient(application) as first:
        register(first, "first")
        second = TestClient(application)
        second.portal = first.portal
        register(second, "second")
        payload = {"request_id": "same-draft", "expected_revision": 0, "data": RAW_DRAFT}
        assert first.put("/api/v1/workspace/draft", json=payload).status_code == 200
        assert second.get("/api/v1/workspace/draft").json()["data"] == {}
        other = {**payload, "data": {**RAW_DRAFT, "description": "Second student private data"}}
        assert second.put("/api/v1/workspace/draft", json=other).status_code == 200
        one = first.post("/api/v1/sessions", json=CREATE).json()["session_id"]
        two = second.post("/api/v1/sessions", json=CREATE).json()["session_id"]
        assert one != two
        assert [row["session_id"] for row in first.get("/api/v1/sessions").json()["items"]] == [one]
        assert [row["session_id"] for row in second.get("/api/v1/sessions").json()["items"]] == [
            two
        ]
        for method, path in [
            ("GET", f"/sessions/{one}"),
            ("DELETE", f"/sessions/{one}"),
            ("GET", f"/sessions/{one}/events"),
            ("GET", f"/sessions/{one}/drafts/1/summary"),
        ]:
            assert second.request(method, "/api/v1" + path).status_code == 404
        for client, identifier in [(first, one), (second, two)]:
            waiting = settled(client, identifier)
            accepted = client.post(
                f"/api/v1/sessions/{identifier}/resume",
                json={
                    "request_id": "same-resume",
                    "expected_revision": waiting["revision"],
                    "action": "confirm_search",
                },
            )
            assert accepted.status_code == 202
            result = settled(client, identifier)
            job = result["recommendation"]["jobs"][0]["job"]["job_id"]
            assert (
                client.put(
                    f"/api/v1/saved-jobs/{job}",
                    json={"session_id": identifier, "expected_revision": result["revision"]},
                ).status_code
                == 200
            )
        assert first.get("/api/v1/saved-jobs").json()["items"][0]["job"]["job_id"] == job
        assert second.delete(f"/api/v1/saved-jobs/{job}").status_code == 204
        assert first.get("/api/v1/saved-jobs").json()["items"][0]["job"]["job_id"] == job


def test_model_settings_are_encrypted_and_never_inherit_keys_across_services(
    tmp_path: Path,
) -> None:
    database = tmp_path / "keys.sqlite3"
    with TestClient(create_replay_app(database_url=f"sqlite://{database.as_posix()}")) as client:
        register(client)
        config = {
            "endpoint_id": "openai",
            "model": "synthetic-semantic",
            "api_key": "synthetic-private-key",
            "thinking": True,
        }
        assert client.put("/api/v1/settings/models/semantic", json=config).status_code == 204
        read = client.get("/api/v1/settings/models")
        assert "synthetic-private-key" not in read.text
        assert read.json()["roles"]["semantic"]["key_configured"] is True
        assert read.json()["roles"]["semantic"]["thinking"] is True
        assert read.json()["roles"]["decision"]["personal"] is False
        assert (
            client.put(
                "/api/v1/settings/models/semantic",
                json={"endpoint_id": "openai", "model": "changed-model"},
            ).status_code
            == 204
        )
        switched = client.put(
            "/api/v1/settings/models/semantic", json={"endpoint_id": "deepseek", "model": "other"}
        )
        assert switched.status_code == 422
        assert switched.json()["detail"]["code"] == "model_key_required"
        arbitrary = client.put(
            "/api/v1/settings/models/semantic", json={**config, "base_url": "http://127.0.0.1"}
        )
        assert arbitrary.status_code == 422
    with sqlite3.connect(database) as connection:
        encrypted = connection.execute("SELECT encrypted_key FROM personalmodel").fetchone()[0]
        assert "synthetic-private-key" not in encrypted
        cipher = Fernet(get_settings().credentials_key.get_secret_value().encode())
        assert cipher.decrypt(encrypted.encode()) == b"synthetic-private-key"


def test_operation_snapshots_limits_and_atomic_idempotent_allowance() -> None:
    async def scenario() -> None:
        await Tortoise.init(config=tortoise_config("sqlite://:memory:"))
        await Tortoise.generate_schemas()
        settings = Settings.model_validate(
            {
                "llm_semantic_api_key": "server-semantic",
                "llm_decision_api_key": "server-decision",
                "credentials_key": Fernet.generate_key().decode(),
                "server_daily_user_limit": 1,
            }
        )
        models = ModelSettingsService(settings)
        graph = ControlledGraph()
        routers: list[Any] = []

        def factory(router: Any) -> ControlledGraph:
            routers.append(router)
            return graph

        manager = SessionService(graph, Memory(), model_settings=models, graph_factory=factory)
        try:
            first = await manager.create(create_payload())
            assert (await manager.create(create_payload())).session_id == first.session_id
            assert (await models.usage("workflow-owner"))["used"] == 1
            await graph.started.wait()
            from jobscout.services.model_settings_service import ModelWrite

            await models.write(
                "workflow-owner",
                "semantic",
                ModelWrite(
                    endpoint_id="openai",
                    model="personal-semantic",
                    api_key="personal-semantic-key",
                    thinking=True,
                ),
            )
            await models.write(
                "workflow-owner",
                "decision",
                ModelWrite(
                    endpoint_id="deepseek",
                    model="personal-decision",
                    api_key="personal-decision-key",
                ),
            )
            assert routers[0].semantic.model == settings.llm_semantic_model
            assert routers[0].semantic.thinking is False
            with pytest.raises(HTTPException) as blocked:
                await manager.create(create_payload("capacity"))
            assert blocked.value.status_code == 429
            assert cast(object, blocked.value.detail) == {"code": "operation_capacity"}
            graph.release.set()
            task = manager.sessions[first.session_id].task
            assert task is not None
            await task
            second = await manager.create(create_payload("personal"))
            task = manager.sessions[second.session_id].task
            assert task is not None
            await task
            assert routers[-1].semantic.model == "personal-semantic"
            assert routers[-1].semantic.thinking is True
            assert routers[-1].decision.model == "personal-decision"
            assert (await models.usage("workflow-owner"))["used"] == 1
            await models.clear("workflow-owner", "decision")
            with pytest.raises(HTTPException) as limited:
                await manager.create(create_payload("daily"))
            assert limited.value.status_code == 429
            assert cast(object, limited.value.detail) == {"code": "server_daily_limit"}
            assert await manager.history()
            assert len(manager.sessions) == 2
        finally:
            await manager.close()
            await Tortoise.close_connections()

    asyncio.run(scenario())


@pytest.mark.parametrize("provider_name", ["openai", "openai_compatible", "deepseek"])
def test_provider_sends_only_supported_service_parameters(provider_name: str) -> None:
    from pydantic import BaseModel

    class Result(BaseModel):
        ok: bool

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert ("thinking" in body) == (provider_name == "deepseek")
        assert ("max_completion_tokens" in body) == (provider_name == "openai")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"ok": true}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = LangChainModelProvider(
                Settings.model_validate(
                    {"llm_semantic_provider": provider_name, "llm_semantic_api_key": "synthetic"}
                ),
                client=client,
            )
            assert (
                await provider.structured(Result, [{"role": "user", "content": "Return JSON"}])
            ).ok

    asyncio.run(scenario())


def test_production_requires_secrets_and_backup_preserves_rows(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as invalid:
        Settings.model_validate(
            {
                "production": True,
                "credentials_key": "",
                "registration_code": "",
                "cookie_secure": False,
                "llm_semantic_api_key": "synthetic-startup-secret",
            }
        )
    assert "synthetic-startup-secret" not in str(invalid.value)
    source = tmp_path / "original.sqlite3"
    destination = tmp_path / "backup.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE private_data (id TEXT)")
        connection.execute("INSERT INTO private_data VALUES ('synthetic-account')")
    backup_database(source, destination)
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT id FROM private_data").fetchall() == [
            ("synthetic-account",)
        ]
    with pytest.raises(ValueError):
        backup_database(source, destination)


def test_site_capacity_and_allowance_rejection_roll_back_acceptance() -> None:
    async def scenario() -> None:
        from jobscout.models import AcceptedRequest, SearchSession

        await Tortoise.init(config=tortoise_config("sqlite://:memory:"))
        await Tortoise.generate_schemas()
        settings = Settings.model_validate(
            {
                "llm_semantic_api_key": "server-semantic",
                "llm_decision_api_key": "server-decision",
                "server_daily_total_limit": 3,
            }
        )
        models = ModelSettingsService(settings)
        graph = ControlledGraph()
        manager = SessionService(
            graph, Memory(), model_settings=models, graph_factory=lambda _: graph
        )
        context = current_user_id.set("first")
        try:
            identifiers = []
            for owner in ["first", "second", "third"]:
                current_user_id.set(owner)
                identifiers.append(
                    (await manager.create(create_payload("same-request"))).session_id
                )
            current_user_id.set("fourth")
            with pytest.raises(HTTPException) as capacity:
                await manager.create(create_payload("same-request"))
            assert cast(object, capacity.value.detail) == {"code": "operation_capacity"}
            assert (await models.usage("fourth"))["used"] == 0
            graph.release.set()
            tasks = []
            for identifier in identifiers:
                task = manager.sessions[identifier].task
                assert task is not None
                tasks.append(task)
            await asyncio.gather(*tasks)
            with pytest.raises(HTTPException) as allowance:
                await manager.create(create_payload("same-request"))
            assert cast(object, allowance.value.detail) == {"code": "server_daily_limit"}
            assert not await AcceptedRequest.filter(owner_id="fourth").exists()
            assert not await SearchSession.filter(owner_id="fourth").exists()
            assert (await models.usage("fourth"))["used"] == 0
            models.day = lambda: "2099-01-01"  # type: ignore[method-assign]
            assert (await models.usage("fourth"))["remaining"] == 20
            fresh = await manager.create(create_payload("same-request"))
            task = manager.sessions[fresh.session_id].task
            assert task is not None
            await task
            assert (await models.usage("fourth"))["used"] == 1
        finally:
            await manager.close()
            await Tortoise.close_connections()
            current_user_id.reset(context)

    asyncio.run(scenario())
