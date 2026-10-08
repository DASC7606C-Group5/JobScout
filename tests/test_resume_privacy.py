"""Consent, durable encryption, migration and complete account erasure."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient

from jobscout.config import get_settings
from jobscout.database import encrypt_existing_resume_data
from jobscout.graph.checkpoints import checkpoint_serializer
from jobscout.graph.encrypted_saver import EncryptedSqliteSaver
from jobscout.main import create_app
from jobscout.models import DailyUsage, PersonalModel, SavedJob, SearchSession, WorkspaceDraft
from jobscout.services.encryption import ProfileDocumentCipher
from tests.test_account_security import register
from tests.test_conversation_service import ExtractionProvider
from tests.test_web_scaffold import settled
from tests.test_workspace_persistence import RAW_DRAFT

PRIVATE_TEXT = "enc:v1:synthetic-private-resume-54321"


def test_cipher_requires_key_and_encrypts_prefix_looking_input() -> None:
    with pytest.raises(ValueError, match="CREDENTIALS_KEY"):
        ProfileDocumentCipher("")
    cipher = ProfileDocumentCipher(Fernet.generate_key().decode())
    encrypted = cipher.encrypt(PRIVATE_TEXT)
    assert PRIVATE_TEXT not in encrypted
    assert cipher.decrypt(encrypted) == PRIVATE_TEXT
    with pytest.raises(ValueError, match="cannot be decrypted"):
        ProfileDocumentCipher(Fernet.generate_key().decode()).decrypt(encrypted)


def test_consent_rejects_resume_before_model_calls_or_persistence(tmp_path: Path) -> None:
    provider = ExtractionProvider({"skills": ["Python"]})
    database = tmp_path / "consent.sqlite3"
    with TestClient(
        create_app(provider=provider, database_url=f"sqlite://{database.as_posix()}")
    ) as client:
        register(client)
        response = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "no-consent",
                "resume": {"name": "cv.txt", "text": PRIVATE_TEXT},
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "resume_consent_required"
        assert provider.calls == []
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT session_id FROM workspace_sessions").fetchall() == []
        assert PRIVATE_TEXT.encode() not in database.read_bytes()


def test_resume_round_trip_restart_and_all_checkpoint_writes_are_encrypted(tmp_path: Path) -> None:
    database = tmp_path / "encrypted.sqlite3"
    url = f"sqlite://{database.as_posix()}"
    provider = ExtractionProvider({"skills": ["Python"]})
    draft = {**RAW_DRAFT, "resume": {"name": "cv.txt", "text": PRIVATE_TEXT}}
    with TestClient(create_app(provider=provider, database_url=url)) as client:
        register(client)
        saved = client.put(
            "/api/v1/workspace/draft",
            json={
                "request_id": "draft",
                "expected_revision": 0,
                "data": draft,
            },
        )
        assert saved.status_code == 200
        assert saved.json()["data"] == draft
        response = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "consent",
                "resume": draft["resume"],
                "resume_consent": True,
            },
        )
        assert response.status_code == 202
        session_id = response.json()["session_id"]
        waiting = settled(client, session_id)
        assert waiting["outcome"] == "paused"
        assert PRIVATE_TEXT in json.dumps(provider.calls[0][1])
        with sqlite3.connect(database) as connection:
            state = json.loads(
                connection.execute("SELECT state FROM workspace_sessions").fetchone()[0]
            )
            assert state["input_data"]["resume"] is None
            assert PRIVATE_TEXT not in json.dumps(state)
            writes = connection.execute("SELECT channel, type, value FROM writes").fetchall()
            assert any(channel == "input_data" for channel, _, _ in writes)
            assert all(kind.endswith("+fernet") for _, kind, _ in writes)
            assert all(PRIVATE_TEXT.encode() not in value for _, _, value in writes)
        for file in tmp_path.glob("encrypted.sqlite3*"):
            assert PRIVATE_TEXT.encode() not in file.read_bytes()
    restored_provider = ExtractionProvider({})
    with TestClient(create_app(provider=restored_provider, database_url=url)) as client:
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": get_settings().public_origin},
            json={
                "username": "student",
                "password": "synthetic-password-123",
            },
        )
        assert login.status_code == 200
        assert client.get("/api/v1/workspace/draft").json()["data"] == draft
        assert client.get(f"/api/v1/sessions/{session_id}").json() == waiting
        assert restored_provider.calls == []


def test_migration_encrypts_existing_rows_and_pending_input_writes(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    url = f"sqlite://{database.as_posix()}"
    cipher = ProfileDocumentCipher(get_settings().credentials_key.get_secret_value())
    raw = "legacy-private-resume-98765"
    state = {"input_data": {"resume": {"text": raw}}, "profile_documents": [{"text": raw}]}
    kind, blob = checkpoint_serializer().dumps_typed(state)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE workspace_sessions (state TEXT)")
        connection.execute("CREATE TABLE workspace_drafts (data TEXT)")
        connection.execute("CREATE TABLE checkpoints (type TEXT, checkpoint BLOB)")
        connection.execute("CREATE TABLE writes (type TEXT, value BLOB)")
        connection.execute("INSERT INTO workspace_sessions VALUES (?)", (json.dumps(state),))
        connection.execute(
            "INSERT INTO workspace_drafts VALUES (?)", (json.dumps(state["input_data"]),)
        )
        connection.execute("INSERT INTO checkpoints VALUES (?, ?)", (kind, blob))
        connection.execute("INSERT INTO writes VALUES (?, ?)", (kind, blob))
    encrypt_existing_resume_data(url, cipher)
    encrypt_existing_resume_data(url, cipher)
    with sqlite3.connect(database) as connection:
        migrated = json.loads(
            connection.execute("SELECT state FROM workspace_sessions").fetchone()[0]
        )
        assert cipher.decrypt(migrated["input_data"]["resume"]["text"]) == raw
        assert cipher.decrypt(migrated["profile_documents"][0]["text"]) == raw
        saved_kind, saved_blob = connection.execute("SELECT type, value FROM writes").fetchone()
        assert saved_kind == kind + "+fernet"
        assert cipher.decrypt_bytes(saved_blob) == blob
    assert raw.encode() not in database.read_bytes()
    with pytest.raises((ValueError, InvalidToken)):
        encrypt_existing_resume_data(url, ProfileDocumentCipher(Fernet.generate_key().decode()))


@pytest.mark.parametrize("fail_cleanup", [False, True])
def test_account_deletion_cleans_only_owner_and_can_retry_failed_checkpoint_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_cleanup: bool,
) -> None:
    database = tmp_path / "delete.sqlite3"
    application = create_app(
        provider=ExtractionProvider({"skills": ["Python"]}),
        database_url=f"sqlite://{database.as_posix()}",
    )
    with TestClient(application) as client:
        other = register(client, "other")
        owner = register(client)
        response = client.post(
            "/api/v1/sessions",
            json={
                "request_id": "owned",
                "resume": {"name": "cv.txt", "text": PRIVATE_TEXT},
                "resume_consent": True,
            },
        )
        session_id = response.json()["session_id"]
        settled(client, session_id)
        assert (
            client.put(
                "/api/v1/workspace/draft",
                json={
                    "request_id": "draft",
                    "expected_revision": 0,
                    "data": RAW_DRAFT,
                },
            ).status_code
            == 200
        )

        async def seed_related_rows() -> None:
            await DailyUsage.create(owner_id=owner["user_id"], day="2026-10-08", operations=1)
            await PersonalModel.create(
                owner_id=owner["user_id"],
                role="semantic",
                endpoint_id="deepseek",
                model="synthetic",
                encrypted_key="synthetic-encrypted-key",
            )
            await SavedJob.create(
                owner_id=owner["user_id"],
                job_id="owned-job",
                item={},
                session_id=session_id,
                session_revision=1,
                saved_at=datetime.now(UTC),
            )

        assert client.portal is not None
        client.portal.call(seed_related_rows)
        cleanup = application.state.checkpointer.adelete_thread
        if fail_cleanup:
            monkeypatch.setattr(
                application.state.checkpointer,
                "adelete_thread",
                AsyncMock(side_effect=RuntimeError("private failure")),
            )
            failed = client.delete("/api/v1/auth/account")
            assert failed.status_code == 503
            assert failed.json()["detail"]["code"] == "account_deletion_failed"
            assert client.get("/api/v1/auth/me").status_code == 200
            monkeypatch.setattr(application.state.checkpointer, "adelete_thread", cleanup)
        assert client.delete("/api/v1/auth/account").status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
        assert session_id not in application.state.sessions.sessions
        with sqlite3.connect(database) as connection:
            for table in (
                "workspace_sessions",
                "workspace_drafts",
                "workspace_saved_jobs",
                "workspace_requests",
                "personalmodel",
                "dailyusage",
                "loginsession",
            ):
                assert (
                    connection.execute(
                        f"SELECT owner_id FROM {table} WHERE owner_id = ?", (owner["user_id"],)
                    ).fetchall()
                    == []
                )
            assert connection.execute('SELECT user_id FROM "user"').fetchall() == [
                (other["user_id"],)
            ]
            assert connection.execute("SELECT thread_id FROM checkpoints").fetchall() == []
            assert connection.execute("SELECT thread_id FROM writes").fetchall() == []


def test_encrypted_saver_reads_pending_nested_input_and_lists_checkpoints(tmp_path: Path) -> None:
    from langgraph.checkpoint.base import empty_checkpoint

    async def exercise() -> None:
        cipher = ProfileDocumentCipher(Fernet.generate_key().decode())
        async with EncryptedSqliteSaver.connect_encrypted(
            str(tmp_path / "checkpoint.sqlite3"), cipher
        ) as saver:
            checkpoint = empty_checkpoint()
            value: dict[str, Any] = {"input_data": {"resume": {"text": PRIVATE_TEXT}}}
            checkpoint["channel_values"] = value
            config = await saver.aput(
                {"configurable": {"thread_id": "test", "checkpoint_ns": ""}},
                checkpoint,
                {"source": "input", "step": -1, "parents": {}},
                {},
            )
            await saver.aput_writes(config, [("__start__", value)], "task")
            saved = await saver.aget_tuple(config)
            assert saved is not None
            assert saved.checkpoint["channel_values"] == value
            assert saved.pending_writes == [("task", "__start__", value)]
            listed = [item async for item in saver.alist(config)]
            assert listed[0].checkpoint["channel_values"] == value
            assert listed[0].pending_writes == saved.pending_writes

    asyncio.run(exercise())


@pytest.mark.parametrize("path", ["/api/v1/workspace/draft", "/api/v1/sessions"])
def test_account_deletion_rejects_writes_authenticated_before_deletion(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    async def exercise() -> None:
        app = create_app(provider=ExtractionProvider({"skills": ["Python"]}))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
                headers={"Origin": get_settings().public_origin},
            ) as client:
                registration = await client.post(
                    "/api/v1/auth/register",
                    json={"username": "racing", "password": "synthetic-password-123"},
                )
                client.headers["X-CSRF-Token"] = registration.json()["csrf_token"]
                response = await client.post(
                    "/api/v1/sessions", json={"request_id": "first", "description": "Python"}
                )
                session_id = response.json()["session_id"]
                await app.state.sessions.sessions[session_id].task
                deleting = asyncio.Event()
                release = asyncio.Event()
                authenticated = asyncio.Event()
                original_delete = app.state.sessions.delete
                original_authenticate = app.state.auth.authenticate

                async def delayed_delete(identifier: str) -> None:
                    deleting.set()
                    await release.wait()
                    await original_delete(identifier)

                async def authenticate(token: str) -> Any:
                    identity = await original_authenticate(token)
                    authenticated.set()
                    return identity

                monkeypatch.setattr(app.state.sessions, "delete", delayed_delete)
                deletion = asyncio.create_task(client.delete("/api/v1/auth/account"))
                await asyncio.wait_for(deleting.wait(), timeout=5)
                monkeypatch.setattr(app.state.auth, "authenticate", authenticate)
                payload = (
                    {"request_id": "late", "expected_revision": 0, "data": RAW_DRAFT}
                    if path.endswith("draft")
                    else {"request_id": "late", "description": "Late private data"}
                )
                late = asyncio.create_task(
                    client.request("PUT" if path.endswith("draft") else "POST", path, json=payload)
                )
                await asyncio.wait_for(authenticated.wait(), timeout=5)
                release.set()
                deleted, rejected = await asyncio.wait_for(
                    asyncio.gather(deletion, late), timeout=5
                )
                assert deleted.status_code == 204
                assert rejected.status_code == 401
                assert rejected.json()["detail"]["code"] == "authentication_required"
                assert not await SearchSession.exists()
                assert not await WorkspaceDraft.exists()

    asyncio.run(exercise())
