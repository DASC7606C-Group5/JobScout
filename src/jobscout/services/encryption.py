"""Application-layer encryption for durable applicant documents."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from jobscout.schemas.job import SourceDocument

_CIPHERTEXT_PREFIX = "enc:v1:"


class ProfileDocumentCipher:
    """Encrypts profile document text with the deployment's Fernet credentials key."""

    def __init__(self, credentials_key: str) -> None:
        self._fernet = Fernet(credentials_key.encode()) if credentials_key else None

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt(self, text: str) -> str:
        if self._fernet is None or text.startswith(_CIPHERTEXT_PREFIX):
            return text
        return _CIPHERTEXT_PREFIX + self._fernet.encrypt(text.encode()).decode()

    def decrypt(self, text: str) -> str:
        if self._fernet is None or not text.startswith(_CIPHERTEXT_PREFIX):
            return text
        try:
            return self._fernet.decrypt(text[len(_CIPHERTEXT_PREFIX) :].encode()).decode()
        except InvalidToken as error:
            raise ValueError(
                "Stored resume text cannot be decrypted with the current key."
            ) from error


def encrypt_documents(
    cipher: ProfileDocumentCipher, documents: Sequence[SourceDocument]
) -> list[SourceDocument]:
    return [
        document.model_copy(update={"text": cipher.encrypt(document.text)})
        for document in documents
    ]


def decrypt_documents(
    cipher: ProfileDocumentCipher, documents: Sequence[SourceDocument]
) -> list[SourceDocument]:
    return [
        document.model_copy(update={"text": cipher.decrypt(document.text)})
        for document in documents
    ]


def encrypt_channel_values(
    cipher: ProfileDocumentCipher, channel_values: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy of checkpoint channel values with resume text encrypted."""
    result = dict(channel_values)
    documents = result.get("profile_documents")
    if isinstance(documents, list) and documents:
        result["profile_documents"] = encrypt_documents(
            cipher, [SourceDocument.model_validate(item) for item in documents]
        )
    input_data = result.get("input_data")
    if isinstance(input_data, dict):
        resume = input_data.get("resume")
        if isinstance(resume, dict) and isinstance(resume.get("text"), str):
            result["input_data"] = {
                **input_data,
                "resume": {**resume, "text": cipher.encrypt(resume["text"])},
            }
    return result


def decrypt_channel_values(
    cipher: ProfileDocumentCipher, channel_values: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy of checkpoint channel values with resume text decrypted."""
    result = dict(channel_values)
    documents = result.get("profile_documents")
    if isinstance(documents, list) and documents:
        result["profile_documents"] = decrypt_documents(
            cipher, [SourceDocument.model_validate(item) for item in documents]
        )
    input_data = result.get("input_data")
    if isinstance(input_data, dict):
        resume = input_data.get("resume")
        if isinstance(resume, dict) and isinstance(resume.get("text"), str):
            result["input_data"] = {
                **input_data,
                "resume": {**resume, "text": cipher.decrypt(resume["text"])},
            }
    return result
