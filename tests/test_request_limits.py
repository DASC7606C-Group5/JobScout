"""Reject oversized bodies before JSON parsing or unbounded multipart spooling."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient

from jobscout.api.security import MAX_API_BODY_BYTES, MAX_AUTH_BODY_BYTES, MAX_UPLOAD_BODY_BYTES
from jobscout.config import get_settings
from jobscout.replay.app import create_replay_app
from tests.test_account_security import register


@pytest.mark.parametrize(
    ("path", "content_length", "status", "code"),
    [
        ("/api/v1/auth/login", str(MAX_AUTH_BODY_BYTES + 1), 413, "request_too_large"),
        ("/api/v1/auth/register", "9" * 5000, 413, "request_too_large"),
        ("/api/v1/resumes/parse", str(MAX_UPLOAD_BODY_BYTES + 1), 413, "request_too_large"),
        ("/api/v1/sessions", str(MAX_API_BODY_BYTES + 1), 413, "request_too_large"),
        ("/api/v1/auth/login", "-1", 400, "invalid_content_length"),
    ],
    ids=["login", "huge-length", "upload", "session", "negative-length"],
)
def test_oversized_content_length_is_rejected_before_processing(
    path: str, content_length: str, status: int, code: str
) -> None:
    with TestClient(create_replay_app()) as client:
        response = client.post(path, headers={"Content-Length": content_length})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize("declared_length", [None, "1"])
def test_streamed_json_cannot_bypass_limit_with_missing_or_false_length(
    declared_length: str | None,
) -> None:
    application = create_replay_app()
    with TestClient(application) as client:

        async def scenario() -> None:
            async def chunks() -> AsyncIterator[bytes]:
                yield b'{"username":"'
                yield b"x" * MAX_AUTH_BODY_BYTES
                raise AssertionError("The rejected request must stop reading the body")

            headers = {"Origin": get_settings().public_origin, "Content-Type": "application/json"}
            if declared_length is not None:
                headers["Content-Length"] = declared_length
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(application), base_url=get_settings().public_origin
            ) as browser:
                response = await browser.post(
                    "/api/v1/auth/login", content=chunks(), headers=headers
                )
            assert response.status_code == 413
            assert response.json()["detail"]["code"] == "request_too_large"

        assert client.portal is not None
        client.portal.call(scenario)


def test_auth_body_limit_accepts_exact_boundary_without_registering_oversized_request() -> None:
    credentials = {"username": "boundary-user", "password": "synthetic-password-123"}
    content = json.dumps(credentials).encode().ljust(MAX_AUTH_BODY_BYTES, b" ")
    with TestClient(create_replay_app()) as client:
        headers = {"Origin": get_settings().public_origin, "Content-Type": "application/json"}
        oversized = client.post("/api/v1/auth/register", content=content + b" ", headers=headers)
        assert oversized.status_code == 413
        assert oversized.json()["detail"]["code"] == "request_too_large"
        accepted = client.post("/api/v1/auth/register", content=content, headers=headers)
        assert accepted.status_code == 201
        assert accepted.json()["username"] == credentials["username"]
        identity = client.get("/api/v1/auth/me")
        assert identity.status_code == 200
        assert identity.json()["user_id"] == accepted.json()["user_id"]


def test_streamed_multipart_is_bounded_and_closes_partial_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tempfile import SpooledTemporaryFile
    from typing import Any

    files: list[Any] = []

    def temporary_file(*args: Any, **kwargs: Any) -> Any:
        file = SpooledTemporaryFile(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", temporary_file)
    application = create_replay_app()
    with TestClient(application) as client:
        register(client)

        async def scenario() -> None:
            async def chunks() -> AsyncIterator[bytes]:
                yield (
                    b'--resume\r\nContent-Disposition: form-data; name="file"; filename="resume.txt"'
                    b"\r\nContent-Type: text/plain\r\n\r\n"
                )
                for _ in range(MAX_UPLOAD_BODY_BYTES // 65536 + 1):
                    yield b"x" * 65536
                raise AssertionError("The rejected upload must stop reading the body")

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(application),
                base_url=get_settings().public_origin,
                cookies={name: client.cookies[name] for name in client.cookies},
            ) as browser:
                response = await browser.post(
                    "/api/v1/resumes/parse",
                    content=chunks(),
                    headers={
                        "Origin": get_settings().public_origin,
                        "X-CSRF-Token": client.headers["X-CSRF-Token"],
                        "Content-Type": "multipart/form-data; boundary=resume",
                    },
                )
            assert response.status_code == 413
            assert response.json()["detail"]["code"] == "request_too_large"

        assert client.portal is not None
        client.portal.call(scenario)
    assert files and all(file.closed for file in files)
