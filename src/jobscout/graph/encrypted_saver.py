"""SQLite checkpoint saver that encrypts applicant resume text before it reaches disk."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any, cast

import aiosqlite
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from jobscout.schemas.job import SourceDocument
from jobscout.services.encryption import (
    ProfileDocumentCipher,
    decrypt_channel_values,
    decrypt_documents,
    encrypt_channel_values,
    encrypt_documents,
)


def _encrypt_write(channel: str, value: Any, cipher: ProfileDocumentCipher) -> Any:
    if channel == "profile_documents" and isinstance(value, list) and value:
        return encrypt_documents(cipher, [SourceDocument.model_validate(item) for item in value])
    if channel == "input_data" and isinstance(value, dict):
        resume = value.get("resume")
        if isinstance(resume, dict) and isinstance(resume.get("text"), str):
            return {**value, "resume": {**resume, "text": cipher.encrypt(resume["text"])}}
    return value


def _decrypt_write(channel: str, value: Any, cipher: ProfileDocumentCipher) -> Any:
    if channel == "profile_documents" and isinstance(value, list) and value:
        return decrypt_documents(cipher, [SourceDocument.model_validate(item) for item in value])
    if channel == "input_data" and isinstance(value, dict):
        resume = value.get("resume")
        if isinstance(resume, dict) and isinstance(resume.get("text"), str):
            return {**value, "resume": {**resume, "text": cipher.decrypt(resume["text"])}}
    return value


class EncryptedSqliteSaver(AsyncSqliteSaver):
    """Wraps the async SQLite saver and encrypts resume text in checkpoints and writes."""

    def __init__(
        self,
        conn: aiosqlite.Connection,
        cipher: ProfileDocumentCipher,
        *,
        serde: Any = None,
    ) -> None:
        super().__init__(conn, serde=serde)
        self._cipher = cipher

    @classmethod
    @asynccontextmanager
    async def connect_encrypted(
        cls, conn_string: str, cipher: ProfileDocumentCipher
    ) -> AsyncIterator[EncryptedSqliteSaver]:
        async with aiosqlite.connect(conn_string) as conn:
            yield cls(conn, cipher)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        checkpoint = cast(
            Checkpoint,
            {
                **checkpoint,
                "channel_values": encrypt_channel_values(
                    self._cipher, checkpoint["channel_values"]
                ),
            },
        )
        return await super().aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        encrypted = [
            (channel, _encrypt_write(channel, value, self._cipher)) for channel, value in writes
        ]
        await super().aput_writes(config, encrypted, task_id, task_path)

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        result = await super().aget_tuple(config)
        if result is None:
            return None
        checkpoint = cast(
            Checkpoint,
            {
                **result.checkpoint,
                "channel_values": decrypt_channel_values(
                    self._cipher, result.checkpoint["channel_values"]
                ),
            },
        )
        pending_writes = [
            (task_id, channel, _decrypt_write(channel, value, self._cipher))
            for task_id, channel, value in (result.pending_writes or [])
        ]
        return CheckpointTuple(
            result.config,
            checkpoint,
            result.metadata,
            result.parent_config,
            pending_writes,
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        async for result in super().alist(config, filter=filter, before=before, limit=limit):
            checkpoint = cast(
                Checkpoint,
                {
                    **result.checkpoint,
                    "channel_values": decrypt_channel_values(
                        self._cipher, result.checkpoint["channel_values"]
                    ),
                },
            )
            yield CheckpointTuple(
                result.config,
                checkpoint,
                result.metadata,
                result.parent_config,
                [
                    (task_id, channel, _decrypt_write(channel, value, self._cipher))
                    for task_id, channel, value in (result.pending_writes or [])
                ],
            )
