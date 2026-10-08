"""Concurrent login attempts and password changes exercise the actual auth routes."""

import asyncio
from collections import deque

import httpx
import pytest
from cachetools import TTLCache
from fastapi import HTTPException
from fastapi.testclient import TestClient

from jobscout.config import get_settings
from jobscout.replay.app import create_replay_app
from jobscout.services.auth_service import AuthService, Identity, token_hash
from tests.test_account_security import register


def test_ip_rejection_does_not_store_arbitrary_usernames() -> None:
    auth = AuthService(get_settings())
    for _ in range(60):
        auth.reserve_attempt([("login:attacker", 60)])
    for index in range(1000):
        with pytest.raises(HTTPException) as rejected:
            auth.reserve_attempt([(f"username:unknown-{index}", 10), ("login:attacker", 60)])
        assert rejected.value.status_code == 429
    assert set(auth.failures) == {"login:attacker"}


def test_full_rate_limit_state_retains_existing_limits_until_expiry() -> None:
    auth = AuthService(get_settings())
    now = 0.0
    auth.failures = TTLCache[str, deque[float]](maxsize=2, ttl=900, timer=lambda: now)
    auth.reserve_attempt([("username:first", 1)])
    auth.reserve_attempt([("username:second", 1)])
    with pytest.raises(HTTPException) as capacity:
        auth.reserve_attempt([("username:third", 1)])
    assert capacity.value.status_code == 429
    with pytest.raises(HTTPException) as existing:
        auth.reserve_attempt([("username:first", 1)])
    assert existing.value.status_code == 429
    now = 901.0
    auth.reserve_attempt([("username:third", 1)])
    assert set(auth.failures) == {"username:third"}


@pytest.mark.parametrize("limit", [10, 60])
def test_pending_logins_count_toward_username_and_ip_limits(limit: int) -> None:
    application = create_replay_app()
    with TestClient(application) as client:
        auth: AuthService = application.state.auth

        async def scenario() -> None:
            entered = asyncio.Event()
            release = asyncio.Event()
            attempts = 0

            async def verify(hashed: str, password: str) -> bool:
                nonlocal attempts
                attempts += 1
                if attempts == limit:
                    entered.set()
                await release.wait()
                return False

            auth.verify = verify  # type: ignore[method-assign]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(application),
                base_url=get_settings().public_origin,
                headers={"Origin": get_settings().public_origin},
            ) as browser:
                tasks = [
                    asyncio.create_task(
                        browser.post(
                            "/api/v1/auth/login",
                            json={
                                "username": "unknown" if limit == 10 else f"unknown-{index}",
                                "password": "synthetic-wrong-password",
                            },
                        )
                    )
                    for index in range(limit + 3)
                ]
                await asyncio.wait_for(entered.wait(), 2)
                release.set()
                responses = await asyncio.gather(*tasks)
                assert sum(response.status_code == 401 for response in responses) == limit
                assert sum(response.status_code == 429 for response in responses) == 3
                assert attempts == limit
                assert all(
                    response.json()["detail"]["code"]
                    in {"invalid_credentials", "auth_rate_limited"}
                    for response in responses
                )

        assert client.portal is not None
        client.portal.call(scenario)


def test_password_change_revokes_a_login_already_checking_the_old_password() -> None:
    application = create_replay_app()
    with TestClient(application) as client:
        register(client)
        auth: AuthService = application.state.auth
        original_verify = auth.verify

        async def scenario() -> None:
            verifying = asyncio.Event()
            release = asyncio.Event()
            first = True

            async def verify(hashed: str, password: str) -> bool:
                nonlocal first
                if first:
                    first = False
                    verifying.set()
                    await release.wait()
                return await original_verify(hashed, password)

            auth.verify = verify  # type: ignore[method-assign]
            headers = {
                "Origin": get_settings().public_origin,
                "X-CSRF-Token": client.headers["X-CSRF-Token"],
            }
            transport = httpx.ASGITransport(application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=get_settings().public_origin,
                headers=headers,
                cookies={name: client.cookies[name] for name in client.cookies},
            ) as browser:
                login = asyncio.create_task(
                    browser.post(
                        "/api/v1/auth/login",
                        json={"username": "student", "password": "synthetic-password-123"},
                    )
                )
                await asyncio.wait_for(verifying.wait(), 2)
                changed = asyncio.create_task(
                    browser.post(
                        "/api/v1/auth/password",
                        json={
                            "current_password": "synthetic-password-123",
                            "new_password": "changed-password-123",
                        },
                    )
                )
                await asyncio.sleep(0.05)
                release.set()
                login_response, changed_response = await asyncio.gather(login, changed)
                assert login_response.status_code == 200
                assert changed_response.status_code == 204
                old_token = login_response.cookies["jobscout_session"]
                response = await browser.get(
                    "/api/v1/auth/me", headers={"Cookie": "jobscout_session=" + old_token}
                )
                assert response.status_code == 401
                assert response.json()["detail"]["code"] == "authentication_required"

        assert client.portal is not None
        client.portal.call(scenario)


def test_revocation_cannot_miss_an_event_listener_during_authentication() -> None:
    application = create_replay_app()
    with TestClient(application) as client:
        register(client)
        auth: AuthService = application.state.auth
        original_identity = auth.identity
        cookie = client.cookies["jobscout_session"]

        async def scenario() -> None:
            looked_up = asyncio.Event()
            release = asyncio.Event()

            async def identity(token: str) -> Identity:
                result = await original_identity(token)
                looked_up.set()
                await release.wait()
                return result

            auth.identity = identity  # type: ignore[method-assign]
            authenticating = asyncio.create_task(auth.authenticate(cookie))
            await asyncio.wait_for(looked_up.wait(), 2)
            revoking = asyncio.create_task(auth.revoke(token=token_hash(cookie)))
            await asyncio.sleep(0)
            release.set()
            active = await authenticating
            await revoking
            assert active.revoked.is_set()
            with pytest.raises(HTTPException) as rejected:
                await auth.authenticate(cookie)
            assert rejected.value.status_code == 401

        assert client.portal is not None
        client.portal.call(scenario)


def test_a_pending_password_change_rejects_old_password_login_and_revoked_writes() -> None:
    application = create_replay_app()
    with TestClient(application) as client:
        register(client)
        auth: AuthService = application.state.auth
        original_hash = auth.hash_password

        async def scenario() -> None:
            hashing = asyncio.Event()
            release = asyncio.Event()

            async def hash_password(password: str) -> str:
                if password == "changed-password-123":
                    hashing.set()
                    await release.wait()
                return await original_hash(password)

            auth.hash_password = hash_password  # type: ignore[method-assign]
            headers = {
                "Origin": get_settings().public_origin,
                "X-CSRF-Token": client.headers["X-CSRF-Token"],
            }
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(application),
                base_url=get_settings().public_origin,
                headers=headers,
                cookies={name: client.cookies[name] for name in client.cookies},
            ) as browser:
                changed = asyncio.create_task(
                    browser.post(
                        "/api/v1/auth/password",
                        json={
                            "current_password": "synthetic-password-123",
                            "new_password": "changed-password-123",
                        },
                    )
                )
                await asyncio.wait_for(hashing.wait(), 2)
                stale_write = asyncio.create_task(
                    browser.post(
                        "/api/v1/auth/password",
                        json={
                            "current_password": "synthetic-password-123",
                            "new_password": "another-password-123",
                        },
                    )
                )
                old_login = asyncio.create_task(
                    browser.post(
                        "/api/v1/auth/login",
                        json={
                            "username": "student",
                            "password": "synthetic-password-123",
                        },
                    )
                )
                await asyncio.sleep(0.05)
                release.set()
                changed_response, stale_response, login_response = await asyncio.gather(
                    changed, stale_write, old_login
                )
                assert changed_response.status_code == 204
                assert stale_response.status_code == login_response.status_code == 401
                assert stale_response.json()["detail"]["code"] == "authentication_required"
                assert (await browser.get("/api/v1/auth/me")).status_code == 401
                successful = await browser.post(
                    "/api/v1/auth/login",
                    json={"username": "student", "password": "changed-password-123"},
                )
                assert successful.status_code == 200

        assert client.portal is not None
        client.portal.call(scenario)
