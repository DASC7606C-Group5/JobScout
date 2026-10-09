"""Encrypt every checkpoint and pending write, including LangGraph's input channel."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from jobscout.config import get_settings
from jobscout.graph.checkpoints import checkpoint_serializer
from jobscout.services.encryption import ProfileDocumentCipher


class CheckpointCipher:
    def __init__(self, cipher: ProfileDocumentCipher) -> None:
        self.cipher = cipher

    def encrypt(self, plaintext: bytes) -> tuple[str, bytes]:
        return "fernet", self.cipher.encrypt_bytes(plaintext)

    def decrypt(self, ciphername: str, ciphertext: bytes) -> bytes:
        if ciphername != "fernet":
            raise ValueError("Unsupported checkpoint cipher")
        return self.cipher.decrypt_bytes(ciphertext)


class EncryptedSqliteSaver(AsyncSqliteSaver):
    def __init__(self, conn: aiosqlite.Connection, cipher: ProfileDocumentCipher) -> None:
        super().__init__(
            conn, serde=EncryptedSerializer(CheckpointCipher(cipher), checkpoint_serializer())
        )

    @classmethod
    @asynccontextmanager
    async def connect_encrypted(
        cls, conn_string: str, cipher: ProfileDocumentCipher
    ) -> AsyncIterator[EncryptedSqliteSaver]:
        async with aiosqlite.connect(conn_string) as conn:
            await conn.execute(f"PRAGMA busy_timeout={get_settings().sqlite_busy_timeout_ms}")
            yield cls(conn, cipher)
