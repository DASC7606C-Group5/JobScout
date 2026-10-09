"""Admission happens before multipart parsing; cancellation cannot leak parser capacity."""

import asyncio
import tempfile
import threading
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from jobscout.api import resumes
from jobscout.config import get_settings
from jobscout.replay.app import create_replay_app
from jobscout.schemas.session import ResumeInput
from tests.test_account_security import register


def browser(application: Any, client: TestClient) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(application),
        base_url=get_settings().public_origin,
        cookies={name: client.cookies[name] for name in client.cookies},
        headers={
            "Origin": get_settings().public_origin,
            "X-CSRF-Token": client.headers["X-CSRF-Token"],
        },
    )


def test_upload_capacity_rejects_without_consuming_multipart_body() -> None:
    application = create_replay_app()
    with TestClient(application) as client:
        register(client)

        async def scenario() -> None:
            slots = application.state.upload_slots
            consumed: list[bool] = []
            for _ in range(get_settings().upload_concurrency):
                await slots.acquire()

            async def unread() -> AsyncIterator[bytes]:
                consumed.append(True)
                yield b""

            try:
                async with browser(application, client) as api:
                    rejected = await api.post(
                        "/api/v1/resumes/parse",
                        content=unread(),
                        headers={"Content-Type": "multipart/form-data; boundary=resume"},
                    )
                assert rejected.status_code == 429
                assert rejected.json()["detail"]["code"] == "upload_capacity"
                assert rejected.headers["Retry-After"] == "10"
                assert not consumed
            finally:
                for _ in range(get_settings().upload_concurrency):
                    slots.release()

        assert client.portal is not None
        client.portal.call(scenario)


@pytest.mark.parametrize("failure", ["timeout", "disconnect", "cancel"])
def test_partial_uploads_close_spool_files_and_release_admission(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_replay_app()
    files: list[Any] = []
    original_file = tempfile.SpooledTemporaryFile

    def tracked_file(*args: Any, **kwargs: Any) -> Any:
        file = original_file(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", tracked_file)
    monkeypatch.setattr(get_settings(), "upload_timeout_seconds", 0.03)
    with TestClient(application) as client:
        register(client)

        async def scenario() -> None:
            started = asyncio.Event()

            async def chunks() -> AsyncIterator[bytes]:
                yield b'--resume\r\nContent-Disposition: form-data; name="file"; filename="resume.txt"\r\nContent-Type: text/plain\r\n\r\nSynthetic'
                started.set()
                if failure == "disconnect":
                    raise ClientDisconnect()
                await asyncio.Event().wait()

            async with browser(application, client) as api:
                pending = asyncio.create_task(
                    api.post(
                        "/api/v1/resumes/parse",
                        content=chunks(),
                        headers={"Content-Type": "multipart/form-data; boundary=resume"},
                    )
                )
                await started.wait()
                if failure == "cancel":
                    pending.cancel()
                if failure == "timeout":
                    response = await pending
                    assert response.status_code == 408
                    assert response.json()["detail"]["code"] == "upload_timeout"
                else:
                    with pytest.raises(
                        asyncio.CancelledError if failure == "cancel" else ClientDisconnect
                    ):
                        await pending
                assert files and all(file.closed for file in files)
                accepted = await api.post(
                    "/api/v1/resumes/parse", files={"file": ("resume.txt", b"Synthetic")}
                )
                assert accepted.status_code == 200
            assert application.state.upload_slots._value == get_settings().upload_concurrency

        assert client.portal is not None
        client.portal.call(scenario)


def test_cancelled_parser_retains_its_slot_until_thread_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_replay_app()
    started = threading.Event()
    release = threading.Event()

    def parse(name: str, content: bytes) -> ResumeInput:
        started.set()
        assert release.wait(5)
        return ResumeInput(name=name, text="Synthetic")

    monkeypatch.setattr(resumes, "parse_resume", parse)
    with TestClient(application) as client:
        register(client)

        async def scenario() -> None:
            async with browser(application, client) as api:
                task = asyncio.create_task(
                    api.post("/api/v1/resumes/parse", files={"file": ("resume.txt", b"Synthetic")})
                )
                try:
                    async with asyncio.timeout(2):
                        while not started.is_set():
                            await asyncio.sleep(0.001)
                    task.cancel()
                    await asyncio.sleep(0.01)
                    assert not task.done()
                    assert application.state.resume_slots.locked()
                    release.set()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                    assert not application.state.resume_slots.locked()
                    assert (
                        application.state.upload_slots._value == get_settings().upload_concurrency
                    )
                finally:
                    release.set()
                    await asyncio.gather(task, return_exceptions=True)

        assert client.portal is not None
        client.portal.call(scenario)
